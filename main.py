import argparse
import json
import os
import sqlite3
import subprocess
import time

DEFAULT_DB = os.path.expanduser(
    "~/Library/Application Support/com.meetily.ai/meeting_minutes.sqlite"
)
DEFAULT_INTERVAL = 30
SPEAKER_LABELS = {"mic": "You", "system": "Others"}

# Row types from SQL queries
type MeetingRow = tuple[str, str, str, str | None]  # id, title, created_at, result
type TranscriptRow = tuple[str, float | None, str, str | None]  # transcript, audio_start, timestamp, speaker


def notify(title: str, message: str) -> None:
    """Show a native macOS notification via osascript.

    Silently ignored if osascript is unavailable or times out.

    Args:
        title: Notification title.
        message: Notification body text.
    """
    try:
        subprocess.run(
            ["osascript", "-e", f'display notification "{message}" with title "{title}"'],
            capture_output=True,
            timeout=2,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


def get_db_path(args: argparse.Namespace) -> str:
    """Resolve the database path from args or fall back to the default macOS location."""
    return args.db if args.db else DEFAULT_DB


def get_meetings(
    db: sqlite3.Connection,
    meeting_id: str | None = None,
    since: str | None = None,
) -> list[MeetingRow]:
    """Query meetings that have a completed summary.

    Args:
        db: Open SQLite connection to the Meetily database.
        meeting_id: If provided, filter to this single meeting.
        since: If provided, only return meetings with sp.updated_at after this
            value. Results are ordered by sp.updated_at ASC so the caller can
            use the last value as the next cursor.

    Returns:
        List of meeting rows with id, title, created_at, and summary result JSON.
    """
    sql = """
        SELECT m.id, m.title, m.created_at, sp.result
        FROM meetings m
        JOIN summary_processes sp ON m.id = sp.meeting_id
        WHERE sp.status = 'completed'
    """
    params: list[str] = []
    if meeting_id:
        sql += " AND m.id = ?"
        params.append(meeting_id)
    if since:
        sql += " AND sp.updated_at > ?"
        params.append(since)
    sql += " ORDER BY sp.updated_at ASC"
    return db.execute(sql, params).fetchall()


def get_transcripts(db: sqlite3.Connection, meeting_id: str) -> list[TranscriptRow]:
    """Fetch all transcript segments for a meeting, ordered by audio time.

    Args:
        db: Open SQLite connection to the Meetily database.
        meeting_id: The meeting to fetch transcripts for.

    Returns:
        List of transcript rows with text, audio start time, timestamp, and speaker.
    """
    return db.execute(
        """
        SELECT transcript, audio_start_time, timestamp, speaker
        FROM transcripts
        WHERE meeting_id = ?
        ORDER BY audio_start_time ASC
        """,
        (meeting_id,),
    ).fetchall()


def format_time(seconds: float | None) -> str:
    """Convert seconds to a [MM:SS] display string.

    Args:
        seconds: Elapsed seconds from the start of the recording.

    Returns:
        Formatted string like [02:35], or [??:??] if seconds is None.
    """
    if seconds is None:
        return "[??:??]"
    total = int(seconds)
    mm = total // 60
    ss = total % 60
    return f"[{mm:02d}:{ss:02d}]"


def build_markdown(meeting: MeetingRow, transcripts: list[TranscriptRow]) -> str:
    """Assemble a complete markdown document from a meeting and its transcripts.

    Produces YAML frontmatter, the AI-generated summary, and a timestamped
    transcript with speaker labels.

    Args:
        meeting: A meeting row from get_meetings.
        transcripts: Transcript rows from get_transcripts.

    Returns:
        The full markdown string ready to write to a file.
    """
    mid, title, created_at, result_json = meeting

    lines = [f"---\ntitle: {title}\nmeeting-id: {mid}\n---\n"]
    lines.append("## Summary\n")

    if result_json:
        try:
            result = json.loads(result_json)
            if isinstance(result, dict):
                lines.append(result.get("markdown", result.get("summary", result_json)))
            else:
                lines.append(str(result))
        except json.JSONDecodeError:
            lines.append(result_json)
    else:
        lines.append("*No summary available.*")

    lines.append("\n---\n")
    lines.append("## Transcript\n")

    for transcript, audio_start, timestamp, speaker in transcripts:
        label = SPEAKER_LABELS.get(speaker)
        if label:
            lines.append(f"{format_time(audio_start)} ({label}) {transcript}")
        else:
            lines.append(f"{format_time(audio_start)} {transcript}")

    return "\n".join(lines) + "\n"


def export_meeting(
    meeting: MeetingRow, db: sqlite3.Connection, output_dir: str, force: bool
) -> bool:
    """Export a single meeting to a markdown file.

    Skips writing if the file already exists unless force is True.

    Args:
        meeting: A meeting row from get_meetings.
        db: Open SQLite connection for fetching transcripts.
        output_dir: Directory to write the markdown file into.
        force: If True, overwrite existing files.

    Returns:
        True if a file was written, False if skipped.
    """
    mid = meeting[0]
    filename = f"{mid}.md"
    filepath = os.path.join(output_dir, filename)

    if os.path.exists(filepath) and not force:
        print(f"  skip {filename} (exists)")
        return False

    transcripts = get_transcripts(db, mid)
    md = build_markdown(meeting, transcripts)

    os.makedirs(output_dir, exist_ok=True)
    with open(filepath, "w") as f:
        f.write(md)

    print(f"  wrote {filename}")
    return True


def export_all(
    db: sqlite3.Connection,
    output_dir: str,
    force: bool = False,
    meeting_id: str | None = None,
) -> None:
    """Query completed meetings and export each one as markdown.

    Args:
        db: Open SQLite connection to the Meetily database.
        output_dir: Directory to write markdown files into.
        force: If True, overwrite existing files.
        meeting_id: If provided, export only this meeting.
    """
    meetings = get_meetings(db, meeting_id)
    if not meetings:
        print("No meetings with completed summaries found.")
        return

    print(f"Found {len(meetings)} meeting(s)")
    exported = sum(
        export_meeting(m, db, output_dir, force) for m in meetings
    )
    print(f"Exported {exported} meeting(s)")
    if exported:
        label = "meeting" if exported == 1 else "meetings"
        notify("Recap", f"Exported {exported} {label}")


def cmd_export(args: argparse.Namespace) -> None:
    """Handle the 'export' subcommand.

    Args:
        args: Parsed CLI arguments including output, meeting_id, and force.
    """
    db_path = get_db_path(args)
    if not os.path.exists(db_path):
        print(f"Database not found: {db_path}")
        raise SystemExit(1)

    db = sqlite3.connect(db_path)
    export_all(db, args.output, args.force, args.meeting_id)
    db.close()


def get_latest_cursor(db: sqlite3.Connection) -> str | None:
    """Return the most recent updated_at value for completed summaries.

    Args:
        db: Open SQLite connection to the Meetily database.

    Returns:
        The MAX(updated_at) string, or None if no completed summaries exist.
    """
    row = db.execute(
        "SELECT MAX(sp.updated_at) FROM summary_processes sp WHERE sp.status = 'completed'"
    ).fetchone()
    return row[0] if row else None


def cmd_watch(args: argparse.Namespace) -> None:
    """Handle the 'watch' subcommand.

    Performs an initial bulk export, then polls only for newly-completed
    summaries using a cursor on sp.updated_at.

    Args:
        args: Parsed CLI arguments including output and interval.
    """
    db_path = get_db_path(args)
    if not os.path.exists(db_path):
        print(f"Database not found: {db_path}")
        raise SystemExit(1)

    db = sqlite3.connect(db_path)

    # Initial bulk export
    print(f"Watching for new meetings (every {args.interval}s)...")
    print(f"Output: {args.output}")
    export_all(db, args.output)

    # Seed cursor after initial export
    cursor = get_latest_cursor(db)
    db.close()

    # Poll loop — only fetch meetings newer than cursor
    while True:
        time.sleep(args.interval)
        db = sqlite3.connect(db_path)
        meetings = get_meetings(db, since=cursor)
        for meeting in meetings:
            if export_meeting(meeting, db, args.output, force=False):
                notify("Recap", f"Exported: {meeting[1]}")
        if meetings:
            cursor = get_latest_cursor(db)
        db.close()


def main() -> None:
    """Entry point. Parses CLI arguments and dispatches to export or watch."""
    parser = argparse.ArgumentParser(description="Export Meetily meetings as markdown")
    sub = parser.add_subparsers(dest="command", required=True)

    db_arg = {"flags": ["--db"], "help": "Path to Meetily SQLite database"}

    export_p = sub.add_parser("export", help="Export meetings")
    export_p.add_argument(*db_arg["flags"], help=db_arg["help"])
    export_p.add_argument("--output", required=True, help="Output directory")
    export_p.add_argument("--meeting-id", help="Export a specific meeting")
    export_p.add_argument("--force", action="store_true", help="Overwrite existing files")

    watch_p = sub.add_parser("watch", help="Watch for new meetings")
    watch_p.add_argument(*db_arg["flags"], help=db_arg["help"])
    watch_p.add_argument("--output", required=True, help="Output directory")
    watch_p.add_argument(
        "--interval", type=int, default=DEFAULT_INTERVAL, help="Poll interval in seconds"
    )

    args = parser.parse_args()
    if args.command == "export":
        cmd_export(args)
    elif args.command == "watch":
        cmd_watch(args)


if __name__ == "__main__":
    main()
