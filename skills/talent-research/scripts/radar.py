#!/usr/bin/env python3
"""Research Radar: find people doing recent work in the team's area, for sourcing.

Searches arXiv for recent papers on the topics you care about, groups them by
author, skips anyone already in your ATS, and lists who's worth a personal
note, with the papers that make the note specific.

    python radar.py --days 30 --exclude ats_candidates.csv -o radar.md
    python radar.py --topic "video dataset curation" --topic "multimodal data filtering"

It ranks first authors (usually the person who did the hands-on work) above
middle authors. It does not look anyone up beyond their public papers.
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from sources import arxiv_query_url, default_get, norm, parse_arxiv

DEFAULT_TOPICS = [
    "video dataset",
    "video data curation",
    "multimodal pretraining data",
    "data filtering for video models",
    "video captioning dataset",
    "egocentric video dataset",
]
CATEGORIES = ["cs.CV", "cs.LG", "cs.CL", "cs.MM", "cs.RO"]


def topic_query(topic: str) -> str:
    cats = " OR ".join(f"cat:{c}" for c in CATEGORIES)
    return f'abs:"{topic}" AND ({cats})'


def scan(topics: list[str], days: int, today: date, exclude: set[str], http_get=default_get,
         per_topic: int = 50) -> list[dict]:
    since = (today - timedelta(days=days)).isoformat()
    papers: dict[str, dict] = {}
    for t in topics:
        for e in parse_arxiv(http_get(arxiv_query_url(topic_query(t), per_topic))):
            if e["date"] >= since:
                papers.setdefault(e["url"], {**e, "topics": set()})["topics"].add(t)
    people: dict[str, dict] = defaultdict(lambda: {"papers": [], "score": 0.0, "first": 0})
    for p in papers.values():
        authors = p["authors"]
        for i, a in enumerate(authors):
            if norm(a) in exclude:
                continue
            weight = 1.0 if i == 0 else (0.6 if i == len(authors) - 1 else 0.3)
            rec = people[a]
            rec["name"] = a
            rec["papers"].append(p)
            rec["score"] += weight
            rec["first"] += i == 0
    ranked = sorted(people.values(), key=lambda r: (-r["score"], -r["first"], r["name"]))
    return [r for r in ranked if r["first"] or len(r["papers"]) > 1]


def load_exclude(path: Path | None) -> set[str]:
    if not path:
        return set()
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    key = next((k for k in (rows[0].keys() if rows else []) if k.lower() in {"name", "candidate"}), None)
    return {norm(r[key]) for r in rows if key and r.get(key)}


def markdown(people: list[dict], topics: list[str], days: int, today: date, limit: int) -> str:
    out = [f"# Research Radar: {today:%B} {today.day}, {today.year}", "",
           f"People with recent arXiv work (last {days} days) on: {', '.join(topics)}. "
           "Already in the ATS: skipped. First authors ranked higher.", "",
           "| # | Person | Recent work | Angle for a personal note |", "| --- | --- | --- | --- |"]
    for n, r in enumerate(people[:limit], 1):
        ps = sorted(r["papers"], key=lambda p: p["date"], reverse=True)
        work = "<br>".join(f"[{p['title']}]({p['url']}) ({p['date']})" for p in ps[:3])
        lead = ps[0]
        role = "first author on" if lead["authors"] and lead["authors"][0] == r["name"] else "co-author on"
        angle = f"{role.capitalize()} \"{lead['title']}\"; connects to {sorted(lead.get('topics', {'our work'}))[0]}."
        out.append(f"| {n} | {r['name']} | {work} | {angle} |")
    out += ["", "_Public papers only. Verify identity and current role before reaching out; "
            "write the note yourself, using the paper as the specific hook._", ""]
    return "\n".join(out)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Find recent researchers in your area for sourcing.")
    p.add_argument("--topic", action="append", help="Search phrase (repeatable). Defaults to video/multimodal data.")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--exclude", type=Path, help="CSV with a name/candidate column (people already in the ATS)")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--today", help="YYYY-MM-DD (default: today)")
    p.add_argument("-o", "--output", type=Path)
    args = p.parse_args(argv)
    today = date.fromisoformat(args.today) if args.today else date.today()
    topics = args.topic or DEFAULT_TOPICS
    people = scan(topics, args.days, today, load_exclude(args.exclude))
    text = markdown(people, topics, args.days, today, args.limit)
    if args.output:
        args.output.write_text(text)
        print(f"Wrote {args.output} ({min(len(people), args.limit)} people)", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
