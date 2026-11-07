#!/usr/bin/env python3
"""Gather a candidate's public, professional work into sources.json.

Pulls from the places research engineers actually publish: arXiv, Semantic
Scholar and GitHub. Every source is labeled with how sure we are it belongs to
this person:

  verified     the link or handle came from their application
  likely       name AND affiliation match
  unconfirmed  name match only: never used in an email without a human check

When several researchers share a name and nothing ties one to the
application, it skips them instead of guessing.

    python gather_sources.py --name "Jane Doe" --affiliation "Stanford" \\
        --github janedoe --link https://janedoe.dev -o sources.json

Personal social media is deliberately not supported.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sources import Source, arxiv_papers, default_get, github_repos, hostname_is, norm_url, s2_sources

BLOCKED_DOMAINS = ("instagram.com", "facebook.com", "tiktok.com", "x.com", "twitter.com", "threads.net",
                   "snapchat.com", "reddit.com")


def gather(name: str, affiliation: str = "", github: str = "", links: list[str] | None = None,
           http_get=default_get) -> dict:
    sources: list[Source] = []
    notes: list[str] = []
    for link in links or []:
        if hostname_is(link, BLOCKED_DOMAINS):
            notes.append(f"Skipped {link}: personal social media is out of scope.")
            continue
        sources.append(Source("profile", "Link from the application", link, confidence="verified",
                              why="provided by the candidate"))
    if github:
        try:
            sources += github_repos(github, http_get)
        except Exception as e:  # network or rate limit: say so, keep going
            notes.append(f"GitHub lookup failed: {e}")
    try:
        found, note = s2_sources(name, affiliation, http_get)
        sources += found
        notes.append(note)
    except Exception as e:
        notes.append(f"Semantic Scholar lookup failed: {e}")
    try:
        sources += arxiv_papers(name, affiliation, http_get)
    except Exception as e:
        notes.append(f"arXiv lookup failed: {e}")

    # De-duplicate (the same paper often comes from two places); keep the most confident copy.
    rank = {"verified": 0, "likely": 1, "unconfirmed": 2}
    best: dict[str, Source] = {}
    for s in sources:
        key = norm_url(s.url)
        if key not in best or rank[s.confidence] < rank[best[key].confidence]:
            if key in best:  # carry over citation counts from the other copy
                s.citations = s.citations if s.citations is not None else best[key].citations
            best[key] = s
    ordered = sorted(best.values(), key=lambda s: (rank[s.confidence], s.kind != "profile",
                                                   -(s.citations or s.stars or 0)))
    return {"name": name, "affiliation": affiliation, "sources": [s.to_dict() for s in ordered], "notes": notes}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Gather public professional work for a candidate brief.")
    p.add_argument("--name", required=True)
    p.add_argument("--affiliation", default="", help="Current school or employer from the application")
    p.add_argument("--github", default="", help="GitHub handle from the application")
    p.add_argument("--link", action="append", default=[], help="Any link from the application (repeatable)")
    p.add_argument("-o", "--output", type=Path, default=Path("sources.json"))
    args = p.parse_args(argv)
    result = gather(args.name, args.affiliation, args.github, args.link)
    args.output.write_text(json.dumps(result, indent=2))
    counts = {}
    for s in result["sources"]:
        counts[s["confidence"]] = counts.get(s["confidence"], 0) + 1
    print(f"Wrote {len(result['sources'])} sources to {args.output}: {counts}", file=sys.stderr)
    for n in result["notes"]:
        print(f"  note: {n}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
