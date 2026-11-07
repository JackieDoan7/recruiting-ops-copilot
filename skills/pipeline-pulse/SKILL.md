---
name: pipeline-pulse
description: Daily recruiting pipeline check. Use when asked what's slipping in Ashby, who is stale, missing scorecards, duplicate candidates, or for the morning pipeline digest.
---

# Pipeline Pulse

A read-only morning check of the recruiting pipeline. It applies the team's
promises (no candidate goes 72 hours without an update, scorecards within 24
hours, availability booked within 48) and returns a ranked list split into
**decisions** (only the owner or hiring manager can resolve) and **quick fixes**
(the coordinator can just do).

## Steps

1. **Get the pipeline data.** In order of preference:
   - The Ashby connector, if it's connected: list active applications with
     candidate name, email, job title, current stage, last activity, scorecard
     count, recruiter, and any next interview time. Save them as a CSV with
     the columns in "Input format" below.
   - `python scripts/ashby_export.py -o pipeline.csv` when `ASHBY_API_KEY` is set.
     This export has no upcoming-interview times and counts feedback across all
     rounds (see the script's notes), so booked candidates can show as stale.
     Tell the user that when you deliver a digest built from it.
   - A CSV or JSON export the user attaches.
2. **Run the check:**
   `python scripts/pipeline_pulse.py pipeline.csv --config config.toml --tz America/Los_Angeles`
   (add `--now <ISO time>` to check as of a specific time). Rows with a date
   the script can't read are skipped and listed at the end of the digest.
   Use `--format json` if you need to post-process.
3. **Review before sending.** Read the digest and sanity-check the top three
   items against the source data. If a flag looks wrong, say so and fix the
   config (stage names, SLAs) rather than editing the output by hand.
4. **Deliver** the digest as-is to the coordinator (Slack DM, email, or chat).
   Do not post it in a public channel: it names candidates.

## Rules

- **Never change anything in the ATS.** No stage moves, archives, emails or
  merges. Suggest them; a person does them.
- **Never repeat compensation.** The script redacts amounts; keep it that way
  in anything you write around it.
- A strong candidate who stalls is a **decision**, not a reminder: the owner
  needs to say what's holding it up.
- If a stage name isn't recognized, it's treated as a mid-pipeline stage.
  Add it to `config.toml` under `[stages.kinds]`.

## Input format

CSV or JSON with one row per application. Column names are flexible (common
Ashby export names are mapped), but these are what the script looks for:

| Column | Needed | Example |
| --- | --- | --- |
| candidate | yes (rows without it are ignored) | Maya Okonkwo |
| role | for most checks | ML Engineer |
| stage | for most checks | Technical Interview |
| last_activity | for stale checks | 2026-11-04T10:00-08:00, or "24 days ago" |
| owner | | Jordan |
| email | | maya@example.com (best duplicate detection) |
| feedback / feedback_count | | "Passed tech", "Not a fit per GM", or 2 (text is scanned for "not a fit" and similar) |
| next_interview | | ISO time of the next booked interview |
| interview_completed_at | | ISO time the last interview or onsite ended |
| notes | | free text (scanned for strong signals and comp details; never printed) |
| status | | Active / Archived / Hired |

See `examples/pipeline.csv` and the output in `examples/digest.md`.
