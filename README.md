# Meetily Exporter

[![tests](https://github.com/dino-rodriguez/meetily-exporter/actions/workflows/test.yml/badge.svg)](https://github.com/dino-rodriguez/meetily-exporter/actions/workflows/test.yml)

A simple CLI that exports meetings from [Meetily](https://github.com/Zackriya-Solutions/meeting-minutes) as portable markdown files. **macOS only.**

## Table of contents

- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
- [Output format](#output-format)

## How it works

[Meetily](https://github.com/Zackriya-Solutions/meeting-minutes) is an open-source, local-first meeting assistant that records audio, transcribes it, and generates AI summaries — all stored in a local SQLite database.

This tool reads that database (read-only) and for each meeting with a completed summary, builds a markdown file containing YAML front matter, the AI summary, and a timestamped transcript with speaker labels. Files are date-prefixed with human-readable titles, designed to work well with [Obsidian](https://obsidian.md) and other markdown-based note systems.

## Requirements

- [Meetily](https://github.com/Zackriya-Solutions/meeting-minutes) installed with at least one completed summary
- macOS
- Python 3.12+

## Installation

### Homebrew (recommended)

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

Configure where meetings are exported, then start the background service:

```bash
meetily-exporter config --output ~/Obsidian/Meetings  # set output directory
brew services start meetily-exporter                   # start and run on login
```

That's it — new meetings will be exported automatically and a macOS notification will appear for each one. Settings are stored in `~/.config/meetily-exporter/config.toml`.

```bash
brew services info meetily-exporter    # check status
brew services stop meetily-exporter    # stop
```

You can also export manually or run the watcher in the foreground:

```bash
meetily-exporter export               # one-time export of all meetings
meetily-exporter export --force       # re-export, overwriting existing files
meetily-exporter watch                # poll for new meetings in the foreground
```

Run `meetily-exporter <command> --help` for all available flags.

## Output format

Each meeting becomes a markdown file named by its date and title (e.g. `2025-01-07 1400 - Design Review.md`):

```markdown
---
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

Existing files are detected by the `meeting-id` in front matter, so renaming a file won't cause duplicates. Re-exporting with `--force` after a title change in Meetily will rename the file to match.
