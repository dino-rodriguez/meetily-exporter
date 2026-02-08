import json
import os
import sqlite3
import tempfile
import time
import unittest

from main import (
    export_all,
    export_meeting,
    get_latest_cursor,
    get_meetings,
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


class TestExport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "test.sqlite")
        self.output = os.path.join(self.tmp.name, "output")
        self.db = create_test_db(self.db_path)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_export_all(self):
        export_all(self.db, self.output)
        files = sorted(os.listdir(self.output))
        self.assertEqual(files, ["meeting-aaa.md", "meeting-bbb.md"])

    def test_skip_existing(self):
        export_all(self.db, self.output)
        mtime = os.path.getmtime(os.path.join(self.output, "meeting-aaa.md"))

        export_all(self.db, self.output)
        self.assertEqual(
            os.path.getmtime(os.path.join(self.output, "meeting-aaa.md")), mtime
        )

    def test_force_overwrite(self):
        export_all(self.db, self.output)
        path = os.path.join(self.output, "meeting-aaa.md")
        mtime = os.path.getmtime(path)

        time.sleep(0.05)
        export_all(self.db, self.output, force=True)
        self.assertGreater(os.path.getmtime(path), mtime)

    def test_single_meeting_id(self):
        export_all(self.db, self.output, meeting_id="meeting-bbb")
        self.assertEqual(os.listdir(self.output), ["meeting-bbb.md"])

    def test_nonexistent_meeting_id(self):
        export_all(self.db, self.output, meeting_id="meeting-zzz")
        self.assertFalse(os.path.exists(self.output))

    def test_markdown_content(self):
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

    def test_cursor_returns_latest_updated_at(self):
        cursor = get_latest_cursor(self.db)
        self.assertEqual(cursor, "2025-01-07T14:45:00")

    def test_since_filters_old_meetings(self):
        meetings = get_meetings(self.db, since="2025-01-07T14:45:00")
        self.assertEqual(len(meetings), 0)

    def test_since_returns_only_newer(self):
        meetings = get_meetings(self.db, since="2025-01-06T09:30:00")
        self.assertEqual(len(meetings), 1)
        self.assertEqual(meetings[0][0], "meeting-bbb")

    def test_new_meeting_picked_up_after_cursor(self):
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


if __name__ == "__main__":
    unittest.main()
