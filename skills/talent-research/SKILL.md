---
name: talent-research
description: Research candidates' public work for personal outreach and interview prep, prioritize applicants against a role rubric with evidence, and find researchers to source.
---

# Talent Research

Three jobs, one principle: **candidates should feel individually known**, and
nothing goes out that isn't true.

| Job | Use when someone asks... | Output |
| --- | --- | --- |
| Candidate brief | "research this candidate", "what has she worked on", "help me personalize this email", interviewer prep | 4-sentence brief with links and a suggested opener |
| Prioritize applicants | "who should we look at first for this role", "which applicants match us best" | Grouped reading order with evidence; never a rejection list |
| Research radar | "who should we reach out to", sourcing for a role | Recent researchers in the area, not already in the ATS |

## Candidate brief

1. Get what the candidate gave us from the ATS (Ashby connector if
   available): name, current school or employer, email domain, and every link
   on the application (GitHub, Google Scholar, personal site).
2. Gather sources:
   `python scripts/gather_sources.py --name "<name>" --affiliation "<school/employer>" --github <handle> --link <url> -o sources.json`
   If the scripts can't reach the internet, use web search instead and write
   `sources.json` in the same format by hand, with an honest `confidence`
   for each source (see below).
3. Write `brief.md` in the format in `references/brief-format.md`, using only
   sources in `sources.json`. Prefer "verified", then "likely". Never use an
   "unconfirmed" source unless the user confirms it's the same person.
4. Check it: `python scripts/check_brief.py brief.md --sources sources.json`.
   Fix every error. Then show the user the brief and the sources it used.

Confidence levels:
- **verified**: the link or handle came from the candidate's application
- **likely**: name AND current affiliation match
- **unconfirmed**: name match only. Common names make this a real risk:
  "I couldn't confirm this is the same person" is a correct answer.

## Prioritize applicants (rubric review)

1. The rubric comes from the hiring manager, in their words (see
   `rubrics/ml-data-engineer.toml` for the shape). Check it first:
   `python scripts/lint_rubric.py <rubric.toml>`. Do not proceed with errors.
2. For each applicant, read the application and their public work, and
   rate each criterion `strong` / `some` / `none` / `unclear` **with
   evidence** (a quote or a link). Rate the work, not the person: ignore
   names, photos, age signals, and school prestige unless the rubric has a
   justified criterion for it. Save as `ratings.json` (see `examples/`).
3. Group them: `python scripts/score.py ratings.json --rubric <rubric.toml>`.
4. Before anyone relies on a new rubric, backtest it on 20-30 past applicants
   with known outcomes: `python scripts/backtest.py past_scored.json past_outcomes.csv`.
   Review the "missed" list with the hiring manager and fix the rubric.
   The optional selection-rate check uses self-ID data: never ask for it or
   join it to names yourself. People Ops or legal runs that step on ids only
   and shares the aggregate table.
5. If the user wants notes in the ATS, `--format json` includes an
   `ashby_note` per applicant. Write notes only with the user's go-ahead, and
   never change stages or archive anyone.

The groups are a **reading order**: "Review first", "Review", "Human check".
Missing information never pushes someone down.

## Research radar (sourcing)

`python scripts/radar.py --days 30 --exclude ats_candidates.csv -o radar.md`
Add `--topic` (repeatable) to match the role. Treat the list as leads: verify
each person's current role before outreach, and write the note personally,
using their paper as the specific hook.

## Rules that always apply

- Public, professional work only: papers, code, talks, company pages. No
  personal social media, family, health, age, religion or politics.
- Every factual claim has a link from `sources.json`. No links from memory.
- Never repeat compensation details.
- AI prepares; a person decides and sends. Nothing is auto-rejected or
  auto-sent.
- In California, tools that help make hiring decisions count as
  "automated-decision systems" (effective Oct 1, 2025): keep the rubric,
  ratings and backtest reports, and loop in whoever handles legal before
  using rubric review on live applicants.
