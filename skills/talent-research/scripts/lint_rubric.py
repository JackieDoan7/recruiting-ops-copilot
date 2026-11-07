#!/usr/bin/env python3
"""Check a role rubric before it's used to prioritize anyone.

A rubric is a short list of job-related criteria, each with what "strong"
looks like. This catches the common ways rubrics go wrong:

  errors    criteria that name a protected characteristic (age, gender,
            race, religion, national origin, disability, family status...)
  warnings  common proxies for those (school prestige, graduation year,
            employment gaps, "culture fit", native speaker). Allowed only
            with a written `justification` from the hiring manager.
  structure every criterion needs an id, a weight, and an observable "strong"
            description; 3 to 8 criteria; tier cutoffs in order.

California's rules on automated-decision systems in hiring (effective
Oct 1, 2025) make this kind of check, and keeping its records, part of doing
this responsibly. This is not legal advice.

    python lint_rubric.py rubrics/ml-data-engineer.toml
"""
from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

PROTECTED = {
    "age": r"\b(age|aged|young|youthful|digital native|recent grad(uate)?s?|energetic|years young)\b",
    "sex or gender": r"\b(male|female|man|woman|men|women|gender|he|she)\b",
    "race or ethnicity": r"\b(race|racial|ethnic\w*|white(?![- ](paper|box|list|board|space))|black(?![- ]box)|asian|hispanic|"
                         r"latin[oax])\b",
    "national origin or citizenship": r"\b(nationality|citizen(ship)?|born in|native country|accent)\b",
    "religion": r"\b(religio\w*|christian|muslim|jewish|hindu|church)\b",
    "disability or health": r"\b(disab\w*|able-bodied|physical(ly)? fit|good health)\b",
    "family status": r"\b(married|children|kids|pregnan\w*|family plans?)\b",
}
PROXIES = {
    "school prestige": r"\b(top[- ]?(tier|\d+)? (school|universit\w*|program)|ivy|prestigious|elite|pedigree)\b",
    "graduation year": r"\b(graduat(ed|ion) (year|after|before|in)|class of)\b",
    "employment gaps": r"\b((employment|resume|career|work) gaps?|continuous employment|no breaks)\b",
    "culture fit": r"\bculture[- ]fit\b",
    "native speaker": r"\bnative([- ]level)?[- ](english|speaker)\b",
    "named elite schools": r"\b(stanford|mit|cmu|carnegie mellon|berkeley|harvard|princeton|caltech|oxford|"
                           r"cambridge|yale|tsinghua)\b",
}
RATING_WORDS = ("strong",)


def lint(rubric: dict) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    criteria = rubric.get("criteria", [])
    if not 3 <= len(criteria) <= 8:
        errors.append(f"Use 3 to 8 criteria (found {len(criteria)}). Fewer is too vague; more and nobody can apply it consistently.")
    ids = set()
    for i, c in enumerate(criteria, 1):
        cid = c.get("id") or f"#{i}"
        if not c.get("id"):
            errors.append(f"Criterion {i} needs an id.")
        elif cid in ids:
            errors.append(f"Duplicate criterion id '{cid}'.")
        ids.add(cid)
        w = c.get("weight")
        if not isinstance(w, (int, float)) or w <= 0:
            errors.append(f"'{cid}' needs a positive weight.")
        if len(c.get("strong", "")) < 20:
            errors.append(f"'{cid}' needs an observable description of what 'strong' looks like.")
        text = " ".join(str(c.get(k, "")) for k in ("name", "strong", "some", "look_for"))
        for label, pattern in PROTECTED.items():
            if re.search(pattern, text, re.I):
                errors.append(f"'{cid}' mentions {label}. Criteria must be about the work, not the person.")
        for label, pattern in PROXIES.items():
            if re.search(pattern, text, re.I):
                if c.get("justification"):
                    warnings.append(f"'{cid}' uses {label} (justified: {c['justification']}). "
                                    "Re-check this in the backtest's selection-rate report.")
                else:
                    errors.append(f"'{cid}' uses {label}, a common proxy for protected traits. Remove it, or "
                                  "add a `justification` from the hiring manager explaining why the job needs it.")
    tiers = rubric.get("tiers", {})
    hi, lo = tiers.get("review_first", 0.7), tiers.get("review", 0.4)
    if not 0 < lo < hi <= 1:
        errors.append("Tier cutoffs must satisfy 0 < review < review_first <= 1.")
    return errors, warnings


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Check a role rubric for structure and bias risks.")
    p.add_argument("rubric", type=Path)
    args = p.parse_args(argv)
    errors, warnings = lint(tomllib.loads(args.rubric.read_text()))
    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"error: {e}")
    if errors:
        return 1
    print("Rubric passes. Next: backtest it against past decisions before relying on it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
