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
    export_all,
    export_meeting,
    get_latest_cursor,
    get_meetings,
    load_config,
    notify,
    resolve_args,
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
        self.assertEqual(files, ["meeting-aaa.md", "meeting-bbb.md"])

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
        mtime = os.path.getmtime(os.path.join(self.output, "meeting-aaa.md"))

        export_all(self.db, self.output)
        self.assertEqual(
            os.path.getmtime(os.path.join(self.output, "meeting-aaa.md")), mtime
        )

    def test_force_overwrite(self, _notify):
        export_all(self.db, self.output)
        path = os.path.join(self.output, "meeting-aaa.md")
        mtime = os.path.getmtime(path)

        time.sleep(0.05)
        export_all(self.db, self.output, force=True)
        self.assertGreater(os.path.getmtime(path), mtime)

    def test_single_meeting_id(self, _notify):
        export_all(self.db, self.output, meeting_id="meeting-bbb")
        self.assertEqual(os.listdir(self.output), ["meeting-bbb.md"])

    def test_nonexistent_meeting_id(self, _notify):
        export_all(self.db, self.output, meeting_id="meeting-zzz")
        self.assertFalse(os.path.exists(self.output))

    def test_markdown_content(self, _notify):
        meetings = get_meetings(self.db)
        meeting_aaa = next(m for m in meetings if m[0] == "meeting-aaa")
        export_meeting(meeting_aaa, self.db, self.output, force=False)

        with open(os.path.join(self.output, "meeting-aaa.md")) as f:
            content = f.read()

        self.assertIn("title: Standup Monday", content)
        self.assertIn("meeting-id: meeting-aaa", content)
        self.assertIn("## Action Items", content)
        self.assertIn("- Fix login bug", content)
        self.assertIn("[00:00] (You) Good morning everyone", content)
        self.assertIn("[00:05] (Others) Hi lets get started", content)


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

        for m in new:
            export_meeting(m, self.db, self.output, force=False)
        self.assertIn("meeting-ccc.md", os.listdir(self.output))

        new_cursor = get_latest_cursor(self.db)
        self.assertEqual(new_cursor, "2025-01-08T17:00:00")
        self.assertGreater(new_cursor, cursor)


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
