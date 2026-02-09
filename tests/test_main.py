import argparse
import json
import os
import sqlite3
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from main import (
    DEFAULT_DB,
    DEFAULT_INTERVAL,
    DEFAULT_OUTPUT,
    build_id_mapping,
    export_all,
    export_meeting,
    get_latest_cursor,
    get_meetings,
    load_config,
    meeting_filename,
    notify,
    read_frontmatter_id,
    resolve_args,
    sanitize_title,
    save_config,
)


def create_test_db(path: str) -> sqlite3.Connection:
    """Create a Meetily-shaped SQLite database with sample data.

    Two meetings have completed summaries (aaa, bbb).
    One meeting is still processing (ccc).
    """
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE meetings (
            id TEXT PRIMARY KEY, title TEXT, created_at TEXT
        );
        CREATE TABLE summary_processes (
            meeting_id TEXT, status TEXT, result TEXT, updated_at TEXT
        );
        CREATE TABLE transcripts (
            meeting_id TEXT, transcript TEXT,
            audio_start_time REAL, timestamp TEXT, speaker TEXT
        );

        INSERT INTO meetings VALUES
            ('meeting-aaa', 'Standup Monday',  '2025-01-06T09:00:00'),
            ('meeting-bbb', 'Design Review',   '2025-01-07T14:00:00'),
            ('meeting-ccc', 'Sprint Retro',    '2025-01-08T16:00:00');

        INSERT INTO summary_processes VALUES
            ('meeting-ccc', 'processing', NULL, '2025-01-08T16:10:00');

        INSERT INTO transcripts VALUES
            ('meeting-aaa', 'Good morning everyone', 0.0,
             '2025-01-06T09:00:00', 'mic'),
            ('meeting-aaa', 'Hi lets get started', 5.5,
             '2025-01-06T09:00:05', 'system'),
            ('meeting-bbb', 'Lets look at the mockups', 0.0,
             '2025-01-07T14:00:00', 'mic'),
            ('meeting-bbb', 'I like option B', 12.3,
             '2025-01-07T14:00:12', 'system');
    """)
    for mid, md, ts in [
        ("meeting-aaa", "## Action Items\n- Fix login bug", "2025-01-06T09:30:00"),
        ("meeting-bbb", "## Decisions\n- Use new color palette", "2025-01-07T14:45:00"),
    ]:
        db.execute(
            "INSERT INTO summary_processes VALUES (?, ?, ?, ?)",
            (mid, "completed", json.dumps({"markdown": md}), ts),
        )
    db.commit()
    return db


@patch("main.notify")
class TestExport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "test.sqlite")
        self.output = os.path.join(self.tmp.name, "output")
        self.db = create_test_db(self.db_path)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_export_all(self, _notify):
        export_all(self.db, self.output)
        files = sorted(os.listdir(self.output))
        self.assertEqual(files, [
            "2025-01-06 0900 - Standup Monday.md",
            "2025-01-07 1400 - Design Review.md",
        ])

    def test_export_all_notifies(self, mock_notify):
        export_all(self.db, self.output)
        mock_notify.assert_called_once_with("Meetily Exporter", "Exported 2 meetings")

    def test_skip_does_not_notify(self, mock_notify):
        export_all(self.db, self.output)
        mock_notify.reset_mock()
        export_all(self.db, self.output)  # all skipped
        mock_notify.assert_not_called()

    def test_skip_existing(self, _notify):
        export_all(self.db, self.output)
        path = os.path.join(self.output, "2025-01-06 0900 - Standup Monday.md")
        mtime = os.path.getmtime(path)

        export_all(self.db, self.output)
        self.assertEqual(os.path.getmtime(path), mtime)

    def test_force_overwrite(self, _notify):
        export_all(self.db, self.output)
        path = os.path.join(self.output, "2025-01-06 0900 - Standup Monday.md")
        mtime = os.path.getmtime(path)

        time.sleep(0.05)
        export_all(self.db, self.output, force=True)
        self.assertGreater(os.path.getmtime(path), mtime)

    def test_single_meeting_id(self, _notify):
        export_all(self.db, self.output, meeting_id="meeting-bbb")
        self.assertEqual(os.listdir(self.output), ["2025-01-07 1400 - Design Review.md"])

    def test_nonexistent_meeting_id(self, _notify):
        export_all(self.db, self.output, meeting_id="meeting-zzz")
        self.assertFalse(os.path.exists(self.output))

    def test_markdown_content(self, _notify):
        meetings = get_meetings(self.db)
        meeting_aaa = next(m for m in meetings if m[0] == "meeting-aaa")
        id_mapping = {}
        used = set()
        export_meeting(meeting_aaa, self.db, self.output, force=False,
                       id_mapping=id_mapping, used_filenames=used)

        with open(os.path.join(self.output, "2025-01-06 0900 - Standup Monday.md")) as f:
            content = f.read()

        self.assertIn("meeting-id: meeting-aaa", content)
        self.assertNotIn("title:", content)
        self.assertIn("## Action Items", content)
        self.assertIn("- Fix login bug", content)
        self.assertIn("[00:00] (You) Good morning everyone", content)
        self.assertIn("[00:05] (Others) Hi lets get started", content)

    def test_transcript_has_blank_lines(self, _notify):
        meetings = get_meetings(self.db)
        meeting_aaa = next(m for m in meetings if m[0] == "meeting-aaa")
        id_mapping = {}
        used = set()
        export_meeting(meeting_aaa, self.db, self.output, force=False,
                       id_mapping=id_mapping, used_filenames=used)

        with open(os.path.join(self.output, "2025-01-06 0900 - Standup Monday.md")) as f:
            content = f.read()

        self.assertIn(
            "[00:00] (You) Good morning everyone\n\n[00:05] (Others) Hi lets get started",
            content,
        )

    def test_force_renames_on_title_change(self, _notify):
        export_all(self.db, self.output)
        old_name = "2025-01-06 0900 - Standup Monday.md"
        self.assertIn(old_name, os.listdir(self.output))

        # Rename meeting in DB
        self.db.execute("UPDATE meetings SET title='Daily Standup' WHERE id='meeting-aaa'")
        self.db.commit()

        export_all(self.db, self.output, force=True)
        files = os.listdir(self.output)
        new_name = "2025-01-06 0900 - Daily Standup.md"
        self.assertIn(new_name, files)
        self.assertNotIn(old_name, files)


@patch("main.notify")
class TestWatchCursor(unittest.TestCase):
    """Test the cursor-based polling mechanism used by watch."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "test.sqlite")
        self.output = os.path.join(self.tmp.name, "output")
        self.db = create_test_db(self.db_path)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_cursor_returns_latest_updated_at(self, _notify):
        cursor = get_latest_cursor(self.db)
        self.assertEqual(cursor, "2025-01-07T14:45:00")

    def test_since_filters_old_meetings(self, _notify):
        meetings = get_meetings(self.db, since="2025-01-07T14:45:00")
        self.assertEqual(len(meetings), 0)

    def test_since_returns_only_newer(self, _notify):
        meetings = get_meetings(self.db, since="2025-01-06T09:30:00")
        self.assertEqual(len(meetings), 1)
        self.assertEqual(meetings[0][0], "meeting-bbb")

    def test_new_meeting_picked_up_after_cursor(self, _notify):
        export_all(self.db, self.output)
        cursor = get_latest_cursor(self.db)
        self.assertEqual(len(os.listdir(self.output)), 2)

        # Simulate meeting-ccc completing after cursor
        self.db.execute(
            "UPDATE summary_processes SET status=?, result=?, updated_at=? "
            "WHERE meeting_id=?",
            ("completed", json.dumps({"markdown": "## Retro"}),
             "2025-01-08T17:00:00", "meeting-ccc"),
        )
        self.db.commit()

        new = get_meetings(self.db, since=cursor)
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0][0], "meeting-ccc")

        id_mapping = build_id_mapping(self.output)
        used = {name.lower() for name in id_mapping.values()}
        for m in new:
            export_meeting(m, self.db, self.output, force=False,
                           id_mapping=id_mapping, used_filenames=used)
        self.assertIn("2025-01-08 1600 - Sprint Retro.md", os.listdir(self.output))

        new_cursor = get_latest_cursor(self.db)
        self.assertEqual(new_cursor, "2025-01-08T17:00:00")
        self.assertGreater(new_cursor, cursor)


class TestSanitizeTitle(unittest.TestCase):
    def test_normal_title_unchanged(self):
        self.assertEqual(sanitize_title("Standup Monday"), "Standup Monday")

    def test_unsafe_chars_removed(self):
        self.assertEqual(sanitize_title('Q&A: Session "Live"'), "Q&A Session Live")

    def test_slashes_removed_and_spaces_collapsed(self):
        self.assertEqual(sanitize_title("Q3 / Q4 Planning"), "Q3 Q4 Planning")

    def test_leading_trailing_dots_stripped(self):
        self.assertEqual(sanitize_title(".hidden."), "hidden")

    def test_empty_returns_empty(self):
        self.assertEqual(sanitize_title(""), "")

    def test_all_unsafe_returns_empty(self):
        self.assertEqual(sanitize_title(':"<>|'), "")

    def test_truncates_to_200(self):
        long_title = "A" * 300
        self.assertEqual(len(sanitize_title(long_title)), 200)

    def test_preserves_capitalization(self):
        self.assertEqual(sanitize_title("My IMPORTANT Meeting"), "My IMPORTANT Meeting")


class TestReadFrontmatterId(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid_frontmatter(self):
        path = os.path.join(self.tmp.name, "test.md")
        with open(path, "w") as f:
            f.write("---\nmeeting-id: meeting-aaa\n---\n# Content\n")
        self.assertEqual(read_frontmatter_id(path), "meeting-aaa")

    def test_no_frontmatter(self):
        path = os.path.join(self.tmp.name, "test.md")
        with open(path, "w") as f:
            f.write("# Just a normal markdown file\n")
        self.assertIsNone(read_frontmatter_id(path))

    def test_frontmatter_without_meeting_id(self):
        path = os.path.join(self.tmp.name, "test.md")
        with open(path, "w") as f:
            f.write("---\ntitle: Something\n---\n")
        self.assertIsNone(read_frontmatter_id(path))

    def test_empty_file(self):
        path = os.path.join(self.tmp.name, "test.md")
        with open(path, "w") as f:
            f.write("")
        self.assertIsNone(read_frontmatter_id(path))

    def test_nonexistent_file(self):
        self.assertIsNone(read_frontmatter_id("/nonexistent/path.md"))


class TestBuildIdMapping(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.output = os.path.join(self.tmp.name, "output")
        os.makedirs(self.output)

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_directory(self):
        self.assertEqual(build_id_mapping(self.output), {})

    def test_nonexistent_directory(self):
        self.assertEqual(build_id_mapping("/nonexistent/dir"), {})

    def test_maps_id_to_filename(self):
        with open(os.path.join(self.output, "My Meeting.md"), "w") as f:
            f.write("---\nmeeting-id: meeting-aaa\n---\n")
        mapping = build_id_mapping(self.output)
        self.assertEqual(mapping, {"meeting-aaa": "My Meeting.md"})

    def test_ignores_non_md_files(self):
        with open(os.path.join(self.output, "notes.txt"), "w") as f:
            f.write("---\nmeeting-id: meeting-aaa\n---\n")
        self.assertEqual(build_id_mapping(self.output), {})

    def test_ignores_files_without_frontmatter(self):
        with open(os.path.join(self.output, "random.md"), "w") as f:
            f.write("# No frontmatter here\n")
        self.assertEqual(build_id_mapping(self.output), {})


class TestMeetingFilename(unittest.TestCase):
    def test_normal_title(self):
        used: set[str] = set()
        result = meeting_filename("Standup Monday", "2025-01-06T09:00:00", "mid", used)
        self.assertEqual(result, "2025-01-06 0900 - Standup Monday.md")

    def test_empty_title_falls_back_to_id(self):
        used: set[str] = set()
        result = meeting_filename("", "2025-01-06T09:00:00", "meeting-aaa", used)
        self.assertEqual(result, "2025-01-06 0900 - meeting-aaa.md")

    def test_duplicate_gets_suffix(self):
        used = {"2025-01-06 0900 - standup.md"}
        result = meeting_filename("Standup", "2025-01-06T09:00:00", "mid", used)
        self.assertEqual(result, "2025-01-06 0900 - Standup (2).md")

    def test_case_insensitive_collision(self):
        used = {"2025-01-06 0900 - standup monday.md"}
        result = meeting_filename("Standup Monday", "2025-01-06T09:00:00", "mid", used)
        self.assertEqual(result, "2025-01-06 0900 - Standup Monday (2).md")


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.tmp.name, "config.toml")

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_missing_file(self):
        config = load_config(os.path.join(self.tmp.name, "nonexistent.toml"))
        self.assertEqual(config, {})

    def test_save_and_load(self):
        save_config({"output": "/tmp/meetings", "interval": 60}, self.config_path)
        config = load_config(self.config_path)
        self.assertEqual(config["output"], "/tmp/meetings")
        self.assertEqual(config["interval"], 60)

    def test_save_creates_parent_dirs(self):
        nested = os.path.join(self.tmp.name, "a", "b", "config.toml")
        save_config({"output": "/tmp/test"}, nested)
        self.assertTrue(os.path.exists(nested))

    def test_resolve_uses_defaults_when_no_config(self):
        args = argparse.Namespace(output=None, db=None, interval=None)
        with patch("main.load_config", return_value={}):
            resolve_args(args)
        self.assertEqual(args.output, DEFAULT_OUTPUT)
        self.assertEqual(args.db, DEFAULT_DB)
        self.assertEqual(args.interval, DEFAULT_INTERVAL)

    def test_resolve_config_overrides_default(self):
        args = argparse.Namespace(output=None, db=None, interval=None)
        with patch("main.load_config", return_value={"output": "/custom/path", "interval": 10}):
            resolve_args(args)
        self.assertEqual(args.output, "/custom/path")
        self.assertEqual(args.interval, 10)
        self.assertEqual(args.db, DEFAULT_DB)  # still default

    def test_resolve_flag_overrides_config(self):
        args = argparse.Namespace(output="/flag/path", db=None, interval=None)
        with patch("main.load_config", return_value={"output": "/config/path"}):
            resolve_args(args)
        self.assertEqual(args.output, "/flag/path")

    def test_resolve_expands_tilde_from_config(self):
        args = argparse.Namespace(output=None, db=None, interval=None)
        with patch("main.load_config", return_value={"output": "~/meetings"}):
            resolve_args(args)
        self.assertEqual(args.output, os.path.expanduser("~/meetings"))


class TestNotify(unittest.TestCase):
    @patch("main.subprocess.run")
    def test_calls_osascript(self, mock_run):
        notify("Meetily Exporter", "Exported 2 meetings")
        mock_run.assert_called_once_with(
            ["osascript", "-e", 'display notification "Exported 2 meetings" with title "Meetily Exporter"'],
            capture_output=True,
            timeout=2,
            check=False,
        )

    @patch("main.subprocess.run", side_effect=FileNotFoundError)
    def test_ignores_missing_osascript(self, _mock_run):
        notify("Meetily Exporter", "test")  # should not raise

    @patch("main.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="", timeout=2))
    def test_ignores_timeout(self, _mock_run):
        notify("Meetily Exporter", "test")  # should not raise


if __name__ == "__main__":
    unittest.main()
