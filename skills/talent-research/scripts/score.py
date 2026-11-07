#!/usr/bin/env python3
"""Turn per-criterion ratings into a "who to look at first" list.

Claude (or a person) rates each candidate on each rubric criterion as
strong / some / none / unclear, with evidence. This script does the part that
should be mechanical and auditable:

  * every "strong" or "some" rating must cite evidence (a quote or a link),
    otherwise it is downgraded to "unclear" and flagged
  * a weighted score from the rubric's weights
  * three groups: Review first, Review, Human check. Missing information
    never pushes anyone down: if too little could be assessed, they land in
    "Review" with a note, not in "Human check".
  * nobody is rejected. "Human check" means a person looks before any decision.

    python score.py ratings.json --rubric ../rubrics/ml-data-engineer.toml
"""
from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

VALUES = {"strong": 1.0, "some": 0.5, "none": 0.0}
GROUPS = ["Review first", "Review", "Human check"]


def score_candidate(cand: dict, criteria: list[dict], tiers: dict) -> dict:
    total_w = sum(c["weight"] for c in criteria)
    got, assessed_w, problems, best, gaps = 0.0, 0.0, [], [], []
    for c in criteria:
        r = (cand.get("ratings") or {}).get(c["id"], {"rating": "unclear"})
        rating = str(r.get("rating", "unclear")).lower()
        evidence = [e for e in r.get("evidence", []) if (e.get("text") or e.get("url"))]
        if rating not in (*VALUES, "unclear"):
            problems.append(f"{c['id']}: unknown rating '{rating}', treated as unclear")
            rating = "unclear"
        if rating in ("strong", "some") and not evidence:
            problems.append(f"{c['id']}: rated {rating} with no evidence, treated as unclear")
            rating = "unclear"
        if rating == "unclear":
            gaps.append(f"{c['name']}: couldn't tell")
            continue
        assessed_w += c["weight"]
        got += c["weight"] * VALUES[rating]
        if rating == "strong":
            e = evidence[0]
            best.append((c["weight"], e.get("text") or c["name"], e.get("url", "")))
        elif rating == "none":
            gaps.append(f"{c['name']}: nothing found")
    coverage = assessed_w / total_w if total_w else 0
    # Score only what could be assessed, so "couldn't tell" never lowers anyone's group.
    # Coverage is reported alongside, and low coverage routes to a person instead of a rank.
    score = got / assessed_w if assessed_w else 0
    if coverage < tiers.get("min_coverage", 0.5):
        group, why = "Review", "Not enough information to rank; a person should read this one."
    elif score >= tiers.get("review_first", 0.7):
        group, why = "Review first", ""
    elif score >= tiers.get("review", 0.4):
        group, why = "Review", ""
    else:
        group, why = "Human check", "Low match on this rubric. A person reads it before any decision."
    best.sort(key=lambda x: -x[0])
    return {
        "id": cand.get("id", ""), "name": cand.get("name", ""), "group": group, "score": round(score, 2),
        "coverage": round(coverage, 2), "strongest": [{"text": t, "url": u} for _, t, u in best[:2]],
        "gaps": gaps, "problems": problems, "note": why,
    }


def rank(ratings: dict, rubric: dict) -> list[dict]:
    criteria, tiers = rubric["criteria"], rubric.get("tiers", {})
    rows = [score_candidate(c, criteria, tiers) for c in ratings["candidates"]]
    rows.sort(key=lambda r: (GROUPS.index(r["group"]), -r["score"], r["name"]))
    return rows


def ashby_note(row: dict, role: str) -> str:
    lines = [f"[Rubric review: {role}] Group: {row['group']} (score {row['score']:.2f}, "
             f"{row['coverage']:.0%} of the rubric assessable)."]
    for s in row["strongest"]:
        lines.append(f"Strong: {s['text']}" + (f" ({s['url']})" if s["url"] else ""))
    for g in row["gaps"]:
        lines.append(f"Open: {g}")
    lines.append("Prioritization aid only. A person makes every decision.")
    return "\n".join(lines)


def markdown(rows: list[dict], role: str) -> str:
    out = [f"# Who to look at first: {role}", "",
           "Grouped by how well each applicant's evidence matches the role rubric. This sets reading order, "
           "not decisions: nobody is rejected here, and every \"Human check\" gets read by a person.", "",
           "| # | Applicant | Group | Score | Assessed | Strongest evidence | Open questions |",
           "| --- | --- | --- | --- | --- | --- | --- |"]
    for n, r in enumerate(rows, 1):
        ev = "; ".join(f"[{s['text']}]({s['url']})" if s["url"] else s["text"] for s in r["strongest"]) or "—"
        gaps = "; ".join(r["gaps"]) or "—"
        if r["note"] and r["group"] == "Review" and r["coverage"] < 0.5:
            gaps = f"{r['note']} {gaps}"
        shown = "—" if r["coverage"] < 0.5 else f"{r['score']:.2f}"
        out.append(f"| {n} | {r['name']} | {r['group']} | {shown} | {r['coverage']:.0%} | {ev} | {gaps} |")
    issues = [(r["name"], p) for r in rows for p in r["problems"]]
    if issues:
        out += ["", "**Ratings that need another look:**", ""]
        out += [f"- {name}: {p}" for name, p in issues]
    out.append("")
    return "\n".join(out)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Group applicants by rubric match, with evidence.")
    p.add_argument("ratings", type=Path)
    p.add_argument("--rubric", type=Path, required=True)
    p.add_argument("--format", choices=["markdown", "json"], default="markdown")
    p.add_argument("-o", "--output", type=Path)
    args = p.parse_args(argv)
    rubric = tomllib.loads(args.rubric.read_text())
    ratings = json.loads(args.ratings.read_text())
    role = rubric.get("role", {}).get("title", ratings.get("role", "this role"))
    rows = rank(ratings, rubric)
    if args.format == "json":
        text = json.dumps([{**r, "ashby_note": ashby_note(r, role)} for r in rows], indent=2)
    else:
        text = markdown(rows, role)
    if args.output:
        args.output.write_text(text)
        print(f"Wrote {args.output}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
