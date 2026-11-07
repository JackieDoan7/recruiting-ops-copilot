#!/usr/bin/env python3
"""Check a candidate brief before anyone uses it in an email or interview packet.

The brief must:
  * have every section (Now, Best known for, Why it connects, Suggested opener, Confidence)
  * cite a link for each factual section, and every link must be one that
    gather_sources.py actually found (no links from memory, no made-up papers)
  * not lean on sources marked "unconfirmed" unless a person has checked them
  * stay short: the summary is 4 sentences or fewer
  * stay professional: no compensation, age, family, health, religion or
    personal social media

Exit code 0 = ready for a human skim, 1 = fix the problems listed.

    python check_brief.py brief.md --sources sources.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from sources import hostname_is, norm_url

SECTIONS = ["Now", "Best known for", "Why it connects", "Suggested opener", "Confidence"]
FACT_SECTIONS = ["Now", "Best known for"]
LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)|(?<!\()(https?://[^\s)\]]+)")
# Patterns are written to avoid false alarms on research topics: "equity in ML",
# "healthcare imaging", "Temple University", "a Reddit dataset", an author named Church.
OFF_LIMITS = {
    "compensation": r"\$\s?\d|\b(salary|compensation|comp expectations?|offer amount|equity (grant|stake|package))\b",
    "age or life stage": r"\b(\d{2}[- ]?years?[- ]old|aged \d{2}\b|(she|he|they) (is|are) \d{2}\b|retire(d|ment)?|"
                         r"graduated (in )?(19|20)\d\d|class of (19|20)\d\d)",
    "family": r"\b(married|wife|husband|spouse|(mother|father|parent) of|his kids|her kids|their kids|"
              r"pregnan\w*|maternity|paternity|newborn)\b",
    "health": r"\b(illness|disabilit\w*|diagnosed|medical leave|sick leave)\b",
    "religion or politics": r"\b(attends (church|mosque|synagogue|temple)|catholic|christian|muslim|jewish|hindu|"
                            r"buddhist|religio\w*|democrat|republican)\b",
}
SOCIAL = ("instagram.com", "facebook.com", "tiktok.com", "twitter.com", "x.com", "threads.net", "snapchat.com")
HYPE = r"\b(genius|rockstar|ninja|legendary|world-class|incredible|amazing|superstar)\b"


def parse(text: str) -> tuple[str, dict[str, str]]:
    title = next((l[3:].strip() for l in text.splitlines() if l.startswith("## ")), "")
    found = {}
    for name in SECTIONS:
        m = re.search(rf"\*\*{re.escape(name)}:\*\*\s*(.+?)(?=\n\*\*[A-Z][^*]+:\*\*|\Z)", text, re.S)
        if m:
            found[name] = m.group(1).strip()
    return title, found


def sentences(text: str) -> int:
    text = LINK.sub(lambda m: m.group(1) or "link", text)
    text = re.sub(r"\b(e\.g|i\.e|et al|vs|Dr|Mr|Ms)\.", r"\1", text)
    return len([s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s])


def check(text: str, sources: dict) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    title, sec = parse(text)
    if not title:
        errors.append("Start the brief with '## <Candidate name>'.")
    for name in SECTIONS:
        if name not in sec:
            errors.append(f"Missing the **{name}:** section.")
    known = {norm_url(s["url"]): s for s in sources.get("sources", [])}
    for name in FACT_SECTIONS:
        links = [m.group(2) or m.group(3) for m in LINK.finditer(sec.get(name, ""))]
        if name in sec and not links:
            errors.append(f"**{name}** states facts but cites no link.")
    for m in LINK.finditer(text):
        url = m.group(2) or m.group(3)
        src = known.get(norm_url(url))
        if src is None:
            errors.append(f"Link not found in sources.json (possible made-up source): {url}")
        elif src["confidence"] == "unconfirmed":
            errors.append(f"Uses an unconfirmed source (name match only). Confirm it's the same person, "
                          f"then mark it verified in sources.json: {url}")
    summary = " ".join(sec.get(k, "") for k in ["Now", "Best known for", "Why it connects"])
    n = sentences(summary)
    if n > 4:
        errors.append(f"The summary is {n} sentences. Keep Now + Best known for + Why it connects to 4 or fewer.")
    opener = sec.get("Suggested opener", "")
    if len(opener.split()) > 35:
        warnings.append("The opener is long. One sentence that names their work is enough.")
    for label, pattern in OFF_LIMITS.items():
        if re.search(pattern, text, re.I):
            errors.append(f"Mentions {label}. Keep briefs to professional work only.")
    for m in LINK.finditer(text):
        url = m.group(2) or m.group(3)
        if hostname_is(url, SOCIAL) or re.search(r"reddit\.com/u(ser)?/", url, re.I):
            errors.append(f"Links personal social media ({url}). Keep briefs to professional work only.")
    if re.search(HYPE, text, re.I):
        warnings.append("Hype words read as generic. Name the specific work instead.")
    conf = sec.get("Confidence", "").lower()
    if conf and not conf.startswith(("verified", "likely")):
        errors.append("Confidence must be 'verified' or 'likely' (unconfirmed briefs don't go out).")
    return errors, warnings


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Check a candidate brief against its sources.")
    p.add_argument("brief", type=Path)
    p.add_argument("--sources", type=Path, required=True)
    args = p.parse_args(argv)
    errors, warnings = check(args.brief.read_text(), json.loads(args.sources.read_text()))
    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"error: {e}")
    if errors:
        print(f"\n{len(errors)} problem(s). Fix them before the brief is used.")
        return 1
    print("Brief passes. Give it a final human read before it goes anywhere.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
