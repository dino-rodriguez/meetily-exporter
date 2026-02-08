# Meetily Exporter

## Overview

A standalone Python CLI that reads Meetily's SQLite database and exports meetings as markdown files containing the AI summary and full transcript.

Single file (`main.py`), zero external dependencies.

## Usage

```bash
# Export all meetings with completed summaries
meetily-exporter export

# Export one specific meeting
meetily-exporter export --meeting-id meeting-fa7efe8b-c721-4396-8630-20d91fdcd1aa

# Re-export, overwriting existing files
meetily-exporter export --force

# Watch for new completed summaries, auto-export
meetily-exporter watch

# Custom DB path / poll interval
meetily-exporter watch --db /path/to/db.sqlite --interval 10
```

## Output

### Filename

Named by meeting ID: `meeting-fa7efe8b-c721-4396-8630-20d91fdcd1aa.md`

### Format

```markdown
---
title: Testing Meeting Discussion
meeting-id: meeting-fa7efe8b-c721-4396-8630-20d91fdcd1aa
---

## Summary

{markdown from summary_processes.result JSON}

---

## Transcript

[00:00] (You) First transcript segment
[00:15] (Others) Second transcript segment
...
```

## Skip Logic

If the output file exists, skip it. `--force` overwrites. Watch mode exports only meetings without an existing file.

## Database

**Path:** `~/Library/Application Support/com.meetily.ai/meeting_minutes.sqlite`

**Meetings with completed summaries:**
```sql
SELECT m.id, m.title, m.created_at, sp.result
FROM meetings m
JOIN summary_processes sp ON m.id = sp.meeting_id
WHERE sp.status = 'completed'
```

**Meetings completed since a cursor (used by watch polling):**
```sql
SELECT m.id, m.title, m.created_at, sp.result
FROM meetings m
JOIN summary_processes sp ON m.id = sp.meeting_id
WHERE sp.status = 'completed'
  AND sp.updated_at > ?
ORDER BY sp.updated_at ASC
```

**Transcript segments for a meeting:**
```sql
SELECT transcript, audio_start_time, timestamp, speaker
FROM transcripts
WHERE meeting_id = ?
ORDER BY audio_start_time ASC
```

## Functions

| Function | Purpose |
|----------|---------|
| `get_db_path(args)` | Default macOS path or `--db` override |
| `get_meetings(db, meeting_id=None, since=None)` | Query meetings with completed summaries (optionally after a cursor) |
| `get_transcripts(db, meeting_id)` | All segments ordered by time |
| `build_markdown(meeting, transcripts)` | Frontmatter + summary + transcript |
| `format_time(seconds)` | `audio_start_time` float to `[MM:SS]` |
| `export_meeting(meeting, db, output_dir, force)` | Export one meeting, skip if exists |
| `export_all(db, output_dir, force, meeting_id)` | Query and export all matching meetings |
| `get_latest_cursor(db)` | MAX(updated_at) for completed summaries |
| `cmd_export(args)` | Export subcommand handler |
| `cmd_watch(args)` | Initial bulk export then cursor-based poll loop |
| `main()` | Argparse with `export` and `watch` subcommands |

## Defaults

- **DB:** `~/Library/Application Support/com.meetily.ai/meeting_minutes.sqlite`
- **Output:** `~/Documents/MeetilyExporter`
- **Poll interval:** 30 seconds
- **Force:** off
