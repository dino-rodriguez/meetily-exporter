# Meetily Exporter

[![tests](https://github.com/dino-rodriguez/meetily-exporter/actions/workflows/test.yml/badge.svg)](https://github.com/dino-rodriguez/meetily-exporter/actions/workflows/test.yml)

A simple CLI that exports meetings from [Meetily](https://github.com/Zackriya-Solutions/meeting-minutes) as portable markdown files. **macOS only.**

## Table of contents

- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
  - [Export](#export)
  - [Watch](#watch)
- [Output format](#output-format)

## How it works

[Meetily](https://github.com/Zackriya-Solutions/meeting-minutes) is an open-source, local-first meeting assistant that records audio, transcribes it, and generates AI summaries — all stored in a local SQLite database.

This tool reads that database (read-only) and for each meeting with a completed summary, builds a markdown file containing YAML front matter, the AI summary, and a timestamped transcript with speaker labels.

## Requirements

- [Meetily](https://github.com/Zackriya-Solutions/meeting-minutes) installed with at least one completed summary
- macOS
- Python 3.12+

## Installation

### Homebrew

```bash
brew tap dino-rodriguez/meetily-exporter https://github.com/dino-rodriguez/meetily-exporter
brew install meetily-exporter
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

To run the watcher as a persistent background service that starts on login (Homebrew only):

```bash
brew services start meetily-exporter   # start and run on login
brew services stop meetily-exporter    # stop
brew services info meetily-exporter    # check status
```

### Export options

| Flag | Description | Default |
|------|-------------|---------|
| `--output` | Output directory | `~/Documents/MeetilyExporter` |
| `--db` | Meetily SQLite database | Meetily's default location |
| `--meeting-id` | Export a single meeting | All |
| `--force` | Overwrite existing files | Off |

### Watch options

| Flag | Description | Default |
|------|-------------|---------|
| `--output` | Output directory | `~/Documents/MeetilyExporter` |
| `--db` | Meetily SQLite database | Meetily's default location |
| `--interval` | Poll interval in seconds | 30 |

## Output format

Each meeting becomes a markdown file named by its meeting ID:

```markdown
---
title: Design Review
meeting-id: meeting-fa7efe8b-c721-4396-8630-20d91fdcd1aa
---

## Summary

The team reviewed the latest mockups for the dashboard redesign...

## Action Items
- Update color palette based on brand guidelines
- Schedule follow-up with design team

---

## Transcript

[00:00] (You) Let's look at the mockups for the dashboard
[00:12] (Others) I think option B is the strongest
[00:25] (You) Agreed, let's go with that direction
```

The YAML front matter includes the meeting title, which works with the [Obsidian Front Matter Title](https://github.com/snezhig/obsidian-front-matter-title) plugin if you point your output directory to an Obsidian vault.
