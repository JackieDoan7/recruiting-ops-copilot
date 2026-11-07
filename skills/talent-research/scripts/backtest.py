#!/usr/bin/env python3
"""Backtest a rubric against decisions the team already made.

Run score.py on 20-30 past applicants (rated the same way as new ones), then
compare its groups with what actually happened. Disagreements are how you fix
the rubric before trusting it:

  * "missed": advanced in real life but scored "Human check". The rubric is
    missing something the team values. These matter most.
  * "over-ranked": scored "Review first" but didn't advance. The rubric
    rewards something the team doesn't.

Optional fairness check: if the outcomes file has a `group` column, it reports
how often each group lands in the top two groups and flags any impact ratio
under 0.8 (the "four-fifths rule" used in US adverse-impact analysis). Small
samples are labeled as such. This is a screening signal, not a legal conclusion.

Who runs the fairness check matters: voluntary self-ID data must never sit next
to candidate names in a coordinator's working files. People Ops or legal runs
this step on data they already hold (ids only, no names), and shares only the
aggregate table.

    python score.py past_ratings.json --rubric r.toml --format json -o past_scored.json
    python backtest.py past_scored.json past_outcomes.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

YES = {"yes", "y", "true", "1", "advanced", "hired", "onsite"}


def load_outcomes(path: Path) -> dict[str, dict]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return {row["id"].strip(): row for row in csv.DictReader(f)}


def backtest(scored: list[dict], outcomes: dict[str, dict]) -> dict:
    matched = [(s, outcomes[s["id"]]) for s in scored if s["id"] in outcomes]
    if not matched:
        raise SystemExit("No ids in common between the scored file and the outcomes file.")
    cells = {(p, a): 0 for p in (True, False) for a in (True, False)}
    missed, over = [], []
    for s, o in matched:
        advanced = o.get("advanced", "").strip().lower() in YES
        predicted = s["group"] in ("Review first", "Review")
        cells[(predicted, advanced)] += 1
        if advanced and s["group"] == "Human check":
            missed.append(s)
        if not advanced and s["group"] == "Review first":
            over.append(s)
    n = len(matched)
    agree = (cells[(True, True)] + cells[(False, False)]) / n
    advanced_total = cells[(True, True)] + cells[(False, True)]
    recall = cells[(True, True)] / advanced_total if advanced_total else None

    rates = {}
    if any("group" in o and o["group"].strip() for _, o in matched):
        for s, o in matched:
            g = o.get("group", "").strip() or "not reported"
            top = s["group"] in ("Review first", "Review")
            n_g, k_g = rates.get(g, (0, 0))
            rates[g] = (n_g + 1, k_g + top)
    fairness = []
    reported = {g: v for g, v in rates.items() if g != "not reported" and v[0] > 0}
    if reported:
        best = max(k / n_g for n_g, k in reported.values()) or 1
        for g, (n_g, k) in sorted(reported.items()):
            rate = k / n_g
            ratio = rate / best if best else 1
            fairness.append({"group": g, "n": n_g, "selected": k, "rate": round(rate, 2),
                             "impact_ratio": round(ratio, 2), "flag": ratio < 0.8, "small_sample": n_g < 30})
    return {"n": n, "agreement": round(agree, 2), "advanced_caught": None if recall is None else round(recall, 2),
            "matrix": {f"{'top two' if p else 'human check'} / {'advanced' if a else 'did not advance'}": v
                       for (p, a), v in cells.items()},
            "missed": [{"id": s["id"], "name": s["name"], "gaps": s["gaps"]} for s in missed],
            "over_ranked": [{"id": s["id"], "name": s["name"], "strongest": s["strongest"]} for s in over],
            "fairness": fairness}


def markdown(r: dict) -> str:
    caught = "n/a" if r["advanced_caught"] is None else f"{r['advanced_caught']:.0%}"
    out = ["# Rubric backtest", "",
           f"Compared with {r['n']} past decisions, the rubric agreed **{r['agreement']:.0%}** of the time and put "
           f"**{caught}** of the people who actually advanced in its top two groups.", "",
           "| Rubric said | Advanced | Did not advance |", "| --- | --- | --- |",
           f"| Top two groups | {r['matrix']['top two / advanced']} | {r['matrix']['top two / did not advance']} |",
           f"| Human check | {r['matrix']['human check / advanced']} | {r['matrix']['human check / did not advance']} |",
           ""]
    out += ["## Missed (advanced, but the rubric put them in Human check)", ""]
    out += [f"- {m['name']}: {'; '.join(m['gaps']) or 'no gaps listed'}. What did the team see that the "
            "rubric doesn't measure?" for m in r["missed"]] or ["None."]
    out += ["", "## Over-ranked (Review first, but didn't advance)", ""]
    out += [f"- {o['name']}: strongest evidence was "
            f"{'; '.join(s['text'] for s in o['strongest']) or 'n/a'}. Is that criterion weighted too high?"
            for o in r["over_ranked"]] or ["None."]
    if r["fairness"]:
        out += ["", "## Selection rates by group", "",
                "Share of each group placed in the top two groups. An impact ratio under 0.80 is a signal to "
                "look closer at which criteria drive the difference.", "",
                "| Group | n | In top two | Rate | Impact ratio | Note |", "| --- | --- | --- | --- | --- | --- |"]
        for f in r["fairness"]:
            note = "Look closer" if f["flag"] else ""
            if f["small_sample"]:
                note = (note + "; " if note else "") + "small sample"
            out.append(f"| {f['group']} | {f['n']} | {f['selected']} | {f['rate']:.0%} | {f['impact_ratio']:.2f} | "
                       f"{note} |")
    out += ["", "_Keep this report with the rubric version it tested. Not legal advice._", ""]
    return "\n".join(out)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Compare rubric groups with past hiring decisions.")
    p.add_argument("scored", type=Path, help="score.py --format json output for past applicants")
    p.add_argument("outcomes", type=Path, help="CSV with id, advanced (yes/no), optional group")
    p.add_argument("--format", choices=["markdown", "json"], default="markdown")
    args = p.parse_args(argv)
    result = backtest(json.loads(args.scored.read_text()), load_outcomes(args.outcomes))
    print(json.dumps(result, indent=2) if args.format == "json" else markdown(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
