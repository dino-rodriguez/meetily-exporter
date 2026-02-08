# Meetily Exporter

A simple CLI that exports meetings from [Meetily](https://github.com/Zackriya-Solutions/meeting-minutes) as markdown files. **macOS only.**

[Meetily](https://github.com/Zackriya-Solutions/meeting-minutes) is an open-source, local-first meeting assistant that records audio, transcribes it, and generates AI summaries. The summaries and transcripts are stored in its internal SQLite database. This tool reads that database (read-only) and exports meetings as clean, portable markdown files you can use anywhere.

## Requirements

- [Meetily](https://github.com/Zackriya-Solutions/meeting-minutes) installed with at least one meeting that has a completed summary (transcription alone is not enough — Meetily must finish generating the summary)
- macOS (uses Meetily's macOS database path and native notifications)
- Python 3.12+

## Installation

### pipx

```bash
pipx install git+https://github.com/dino-rodriguez/meetily-exporter
```

### uv

```bash
uv tool install git+https://github.com/dino-rodriguez/meetily-exporter
```

### From source

```bash
git clone https://github.com/dino-rodriguez/meetily-exporter
cd meetily-exporter
uv sync
uv run meetily-exporter --help
```

## Usage

### Export

```bash
meetily-exporter export                # export all meetings
meetily-exporter export --force        # re-export, overwriting existing files
meetily-exporter export --meeting-id <id>  # export a single meeting
```

Exports all meetings with completed summaries to `~/Documents/MeetilyExporter`. Existing files are skipped unless `--force` is used.

### Watch

```bash
meetily-exporter watch                 # poll every 30s for new meetings
meetily-exporter watch --interval 60   # custom poll interval
```

Continuously polls for newly completed meetings and exports them. A macOS notification appears when a meeting is exported.

### Options

Both commands accept `--output` and `--db` to override defaults:

```bash
meetily-exporter export --output ~/vault/meetings --db /path/to/db.sqlite
```

| Flag | Description | Default |
|------|-------------|---------|
| `--output` | Output directory | `~/Documents/MeetilyExporter` |
| `--db` | Meetily SQLite database | Meetily's default location |
| `--meeting-id` | Export a single meeting (export only) | All |
| `--force` | Overwrite existing files (export only) | Off |
| `--interval` | Poll interval in seconds (watch only) | 30 |

## Output format

Each meeting becomes a markdown file named by its meeting ID:

```markdown
---
title: Design Review
meeting-id: meeting-fa7efe8b-c721-4396-8630-20d91fdcd1aa
---

## Summary

## Action Items
- Update color palette
- Schedule follow-up with design team

---

## Transcript

[00:00] (You) Let's look at the mockups
[00:12] (Others) I like option B
```

The YAML front matter includes the meeting title, which works with the [Obsidian Front Matter Title](https://github.com/snezhig/obsidian-front-matter-title) plugin if you point your output directory to an Obsidian vault.
