import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import tomllib
from datetime import datetime

DEFAULT_DB = os.path.expanduser(
    "~/Library/Application Support/com.meetily.ai/meeting_minutes.sqlite"
)
DEFAULT_OUTPUT = os.path.expanduser("~/Documents/MeetilyExporter")
DEFAULT_INTERVAL = 30
CONFIG_PATH = os.path.expanduser("~/.config/meetily-exporter/config.toml")
SPEAKER_LABELS = {"mic": "You", "system": "Others"}
_UNSAFE_CHARS = re.compile(r'[/\\:*?"<>|]')


def sanitize_title(title: str) -> str:
    """Remove filesystem-unsafe characters from a meeting title.

    Strips characters that are illegal on common filesystems, collapses
    double spaces that may result, and truncates to 200 characters.
    Capitalization, unicode, and internal spacing are preserved.

    Args:
        title: Raw meeting title.

    Returns:
        A filesystem-safe string, or empty string if nothing remains.
    """
    s = _UNSAFE_CHARS.sub("", title)
    s = re.sub(r"  +", " ", s)
    s = s.strip(" .")
    return s[:200]


def read_frontmatter_id(path: str) -> str | None:
    """Extract the meeting-id from a markdown file's YAML frontmatter.

    Expects frontmatter delimited by ``---`` on the first line. Returns
    None if the file has no frontmatter or no meeting-id field.

    Args:
        path: Absolute path to a markdown file.

    Returns:
        The meeting-id value, or None.
    """
    try:
        with open(path) as f:
            if f.readline().rstrip("\n") != "---":
                return None
            for line in f:
                if line.rstrip("\n") == "---":
                    return None
                if line.startswith("meeting-id:"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        return None
    return None


def build_id_mapping(output_dir: str) -> dict[str, str]:
    """Scan markdown files and map meeting IDs to filenames.

    Reads the YAML frontmatter of each ``.md`` file in *output_dir* to
    extract the ``meeting-id`` field.

    Args:
        output_dir: Directory containing exported markdown files.

    Returns:
        Dict mapping meeting-id values to filenames (basename only).
    """
    mapping: dict[str, str] = {}
    if not os.path.isdir(output_dir):
        return mapping
    for name in os.listdir(output_dir):
        if not name.endswith(".md"):
            continue
        mid = read_frontmatter_id(os.path.join(output_dir, name))
        if mid:
            mapping[mid] = name
    return mapping


def meeting_filename(
    title: str, created_at: str, mid: str, used: set[str]
) -> str:
    """Build a unique ``.md`` filename from a meeting title and date.

    Format: ``YYYY-MM-DD HHmm - Title.md``. Falls back to the meeting
    ID when the title sanitizes to empty. Appends ``(2)``, ``(3)`` etc.
    to avoid collisions within the current export run.

    Args:
        title: Raw meeting title.
        created_at: ISO-format creation timestamp from the database.
        mid: Meeting ID, used as fallback.
        used: Set of lowercased filenames already claimed.

    Returns:
        A unique filename ending in ``.md``.
    """
    stem = sanitize_title(title) or mid
    dt = datetime.fromisoformat(created_at)
    prefix = dt.strftime("%Y-%m-%d %H%M")
    base = f"{prefix} - {stem}.md"
    if base.lower() not in used:
        return base
    n = 2
    while True:
        candidate = f"{prefix} - {stem} ({n}).md"
        if candidate.lower() not in used:
            return candidate
        n += 1


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


def load_config(path: str = CONFIG_PATH) -> dict[str, str | int]:
    """Read the config file and return its contents as a dict.

    Args:
        path: Path to the TOML config file.

    Returns:
        Parsed config dict, or empty dict if the file doesn't exist.
    """
    if not os.path.exists(path):
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def save_config(config: dict[str, str | int], path: str = CONFIG_PATH) -> None:
    """Write the config dict to a TOML file.

    Creates the parent directory if it doesn't exist.

    Args:
        config: Config key-value pairs to write.
        path: Path to the TOML config file.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = []
    for key, value in config.items():
        if isinstance(value, int):
            lines.append(f"{key} = {value}")
        else:
            lines.append(f'{key} = "{value}"')
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def resolve_args(args: argparse.Namespace) -> None:
    """Fill in unset CLI args from the config file, then from built-in defaults.

    Modifies args in place. Resolution order: CLI flag > config file > default.

    Args:
        args: Parsed CLI arguments. None values are treated as "not provided".
    """
    config = load_config()
    defaults = {"output": DEFAULT_OUTPUT, "db": DEFAULT_DB, "interval": DEFAULT_INTERVAL}

    for key, default in defaults.items():
        if not hasattr(args, key):
            continue
        val = getattr(args, key)
        if val is None:
            val = config.get(key, default)
            if isinstance(default, str) and isinstance(val, str):
                val = os.path.expanduser(val)
            setattr(args, key, val)


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
    mid, _title, created_at, result_json = meeting

    lines = [f"---\nmeeting-id: {mid}\n---\n"]
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
        lines.append("")

    return "\n".join(lines) + "\n"


def export_meeting(
    meeting: MeetingRow,
    db: sqlite3.Connection,
    output_dir: str,
    force: bool,
    id_mapping: dict[str, str],
    used_filenames: set[str],
) -> bool:
    """Export a single meeting to a markdown file.

    Uses *id_mapping* (built from frontmatter) to detect previously
    exported files. Skips writing if already exported unless *force* is
    True. When force-overwriting a meeting whose title changed, the old
    file is removed.

    Args:
        meeting: A meeting row from get_meetings.
        db: Open SQLite connection for fetching transcripts.
        output_dir: Directory to write the markdown file into.
        force: If True, overwrite existing files.
        id_mapping: Meeting-ID → filename mapping from existing files.
        used_filenames: Lowercased filenames already claimed in this run.

    Returns:
        True if a file was written, False if skipped.
    """
    mid, title, created_at = meeting[0], meeting[1], meeting[2]

    old_filename = id_mapping.get(mid)
    if old_filename and not force:
        print(f"  skip {old_filename} (exists)")
        return False

    # Free the old name so it doesn't cause a false collision
    if old_filename:
        used_filenames.discard(old_filename.lower())

    filename = meeting_filename(title, created_at, mid, used_filenames)

    if old_filename and old_filename != filename:
        old_path = os.path.join(output_dir, old_filename)
        if os.path.exists(old_path):
            os.remove(old_path)
            print(f"  rename {old_filename} -> {filename}")

    transcripts = get_transcripts(db, mid)
    md = build_markdown(meeting, transcripts)

    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w") as f:
        f.write(md)

    used_filenames.add(filename.lower())
    id_mapping[mid] = filename

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

    id_mapping = build_id_mapping(output_dir)
    used_filenames = {name.lower() for name in id_mapping.values()}

    print(f"Found {len(meetings)} meeting(s)")
    exported = sum(
        export_meeting(m, db, output_dir, force, id_mapping, used_filenames)
        for m in meetings
    )
    print(f"Exported {exported} meeting(s)")
    if exported:
        label = "meeting" if exported == 1 else "meetings"
        notify("Meetily Exporter", f"Exported {exported} {label}")


def cmd_config(args: argparse.Namespace) -> None:
    """Handle the 'config' subcommand.

    With flags, updates the config file. Always prints the current effective
    configuration showing where each value comes from.

    Args:
        args: Parsed CLI arguments including optional output, db, and interval.
    """
    config = load_config()
    changed = False

    for key in ("output", "db", "interval"):
        val = getattr(args, key, None)
        if val is not None:
            config[key] = val
            changed = True

    if changed:
        save_config(config)
        print(f"Config saved to {CONFIG_PATH}")

    defaults = {"output": DEFAULT_OUTPUT, "db": DEFAULT_DB, "interval": DEFAULT_INTERVAL}
    print("\nCurrent settings:")
    for key, default in defaults.items():
        if key in config:
            val = config[key]
            if isinstance(val, str):
                val = os.path.expanduser(val)
            print(f"  {key} = {val} (from config)")
        else:
            print(f"  {key} = {default} (default)")


def cmd_export(args: argparse.Namespace) -> None:
    """Handle the 'export' subcommand.

    Args:
        args: Parsed CLI arguments including output, meeting_id, and force.
    """
    resolve_args(args)
    if not os.path.exists(args.db):
        print(f"Database not found: {args.db}")
        raise SystemExit(1)

    db = sqlite3.connect(args.db)
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
    resolve_args(args)
    if not os.path.exists(args.db):
        print(f"Database not found: {args.db}")
        raise SystemExit(1)

    db = sqlite3.connect(args.db)

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
        db = sqlite3.connect(args.db)
        meetings = get_meetings(db, since=cursor)
        if meetings:
            id_mapping = build_id_mapping(args.output)
            used_filenames = {name.lower() for name in id_mapping.values()}
            for meeting in meetings:
                if export_meeting(
                    meeting, db, args.output, force=False,
                    id_mapping=id_mapping, used_filenames=used_filenames,
                ):
                    notify("Meetily Exporter", f"Exported: {meeting[1]}")
            cursor = get_latest_cursor(db)
        db.close()


def main() -> None:
    """Entry point. Parses CLI arguments and dispatches to export or watch."""
    # Disable stdout buffering so logs flush immediately when running as a service
    sys.stdout.reconfigure(line_buffering=True)

    parser = argparse.ArgumentParser(prog="meetily-exporter", description="Export Meetily meetings as markdown")
    sub = parser.add_subparsers(dest="command", required=True)

    export_p = sub.add_parser("export", help="Export meetings")
    export_p.add_argument("--db", help="Path to Meetily SQLite database")
    export_p.add_argument("--output", help="Output directory")
    export_p.add_argument("--meeting-id", help="Export a specific meeting")
    export_p.add_argument("--force", action="store_true", help="Overwrite existing files")

    watch_p = sub.add_parser("watch", help="Watch for new meetings")
    watch_p.add_argument("--db", help="Path to Meetily SQLite database")
    watch_p.add_argument("--output", help="Output directory")
    watch_p.add_argument("--interval", type=int, help="Poll interval in seconds")

    config_p = sub.add_parser("config", help="View or update settings")
    config_p.add_argument("--db", help="Set default database path")
    config_p.add_argument("--output", help="Set default output directory")
    config_p.add_argument("--interval", type=int, help="Set default poll interval")

    args = parser.parse_args()
    if args.command == "export":
        cmd_export(args)
    elif args.command == "watch":
        cmd_watch(args)
    elif args.command == "config":
        cmd_config(args)


if __name__ == "__main__":
    main()
