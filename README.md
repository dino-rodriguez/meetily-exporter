# Meetily Exporter

A simple CLI that exports meetings from [Meetily](https://github.com/Zackriya-Solutions/meeting-minutes) as markdown files. **macOS only.**

[Meetily](https://github.com/Zackriya-Solutions/meeting-minutes) is an open-source, local-first meeting assistant that records audio, transcribes it, and generates AI summaries. The summaries and transcripts are stored in its internal SQLite database. This tool reads that database (read-only) and exports meetings as clean, portable markdown files you can use anywhere.

## Requirements

- [Meetily](https://github.com/Zackriya-Solutions/meeting-minutes) installed with at least one meeting that has a completed summary (transcription alone is not enough — Meetily must finish generating the summary)
- macOS (uses Meetily's macOS database path and native notifications)
- Python 3.12+

## Installation

### pip

```bash
pip install git+https://github.com/dino-rodriguez/meetily-exporter
```

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
pip install .
```

## Usage

### Export all meetings

```bash
meetily-exporter export
```

Exports all meetings with completed summaries to `~/Documents/MeetilyExporter`. Existing files are skipped.

### Export a specific meeting

```bash
meetily-exporter export --meeting-id meeting-fa7efe8b-c721-4396-8630-20d91fdcd1aa
```

### Re-export everything

```bash
meetily-exporter export --force
```

### Watch for new meetings

```bash
meetily-exporter watch
```

Polls the database every 30 seconds and exports newly completed meetings. A macOS notification appears when a meeting is exported.

### Options

| Flag | Description | Default |
|------|-------------|---------|
| `--output DIR` | Output directory | `~/Documents/MeetilyExporter` |
| `--db PATH` | Path to Meetily SQLite database | Meetily's default macOS location |
| `--meeting-id ID` | Export a single meeting | All meetings |
| `--force` | Overwrite existing files | Off |
| `--interval SECS` | Poll interval for watch mode | 30 |

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

## License

MIT
