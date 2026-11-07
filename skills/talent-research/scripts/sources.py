"""Shared helpers: fetch a person's public professional work from arXiv, GitHub
and Semantic Scholar, and decide how sure we are that it's the right person.

Every fetcher takes an `http_get(url) -> bytes` function so tests can swap in
saved responses. Standard library only.
"""
from __future__ import annotations

import json
import os
import re
import time
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field

USER_AGENT = "recruiting-ops-copilot/1.0"
ATOM = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


@dataclass
class Source:
    kind: str  # paper | repo | profile
    title: str
    url: str
    date: str = ""  # YYYY-MM-DD or YYYY
    venue: str = ""
    citations: int | None = None
    stars: int | None = None
    summary: str = ""
    authors: list[str] = field(default_factory=list)
    confidence: str = "unconfirmed"  # verified | likely | unconfirmed
    why: str = ""  # how we tied it to the candidate

    def to_dict(self) -> dict:
        return asdict(self)


def default_get(url: str, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text.lower())).strip()


def same_name(a: str, b: str) -> bool:
    """'Jane Q. Doe' matches 'Jane Doe' and 'J. Doe'; different last names never match."""
    pa, pb = norm(a).split(), norm(b).split()
    if not pa or not pb or pa[-1] != pb[-1]:
        return False
    return pa[0] == pb[0] or pa[0][0] == pb[0][0] and (len(pa[0]) == 1 or len(pb[0]) == 1)


def affiliation_matches(hint: str, field: str) -> bool:
    """Whole-word match of the application's school/employer against an affiliation field.
    'MIT' must not match 'transmitted' or 'Smith College'."""
    h, f = norm(hint), norm(field)
    return bool(h) and bool(re.search(rf"(?<![a-z0-9]){re.escape(h)}(?![a-z0-9])", f))


def hostname_is(url: str, domains) -> bool:
    """True if the link's host is one of `domains` or a subdomain of one (x.com, not dropbox.com)."""
    host = (urllib.parse.urlparse(url if "://" in url else f"https://{url}").hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in domains)


def norm_url(url: str) -> str:
    url = url.strip().rstrip("/").lower()
    url = re.sub(r"^https?://(www\.)?", "", url)
    url = re.sub(r"v\d+$", "", url) if "arxiv.org/abs/" in url else url  # ignore arXiv versions
    return url.replace("arxiv.org/pdf/", "arxiv.org/abs/")


# --------------------------------------------------------------------------- arXiv


def arxiv_query_url(search: str, max_results: int = 25) -> str:
    q = urllib.parse.urlencode({"search_query": search, "sortBy": "submittedDate",
                                "sortOrder": "descending", "max_results": max_results})
    return f"https://export.arxiv.org/api/query?{q}"


def parse_arxiv(xml_bytes: bytes) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    out = []
    for e in root.findall("a:entry", ATOM):
        authors, affils = [], []
        for a in e.findall("a:author", ATOM):
            authors.append((a.findtext("a:name", "", ATOM) or "").strip())
            affils.append(" ".join(x.text or "" for x in a.findall("arxiv:affiliation", ATOM)))
        link = e.findtext("a:id", "", ATOM).strip().replace("http://", "https://")
        out.append({
            "title": " ".join((e.findtext("a:title", "", ATOM) or "").split()),
            "url": re.sub(r"v\d+$", "", link),
            "date": (e.findtext("a:published", "", ATOM) or "")[:10],
            "summary": " ".join((e.findtext("a:summary", "", ATOM) or "").split()),
            "authors": authors,
            "affiliations": affils,
            "categories": [c.get("term") for c in e.findall("a:category", ATOM)],
        })
    return out


def arxiv_papers(name: str, affiliation: str = "", http_get=default_get, max_results: int = 25) -> list[Source]:
    entries = parse_arxiv(http_get(arxiv_query_url(f'au:"{name}"', max_results)))
    out = []
    for e in entries:
        idx = next((i for i, a in enumerate(e["authors"]) if same_name(a, name)), None)
        if idx is None:
            continue
        aff = e["affiliations"][idx] if idx < len(e["affiliations"]) else ""
        if affiliation and affiliation_matches(affiliation, aff):
            conf, why = "likely", f"name and affiliation ({affiliation}) match"
        else:
            conf, why = "unconfirmed", "name match only: check before using"
        out.append(Source("paper", e["title"], e["url"], e["date"], "arXiv", summary=e["summary"][:400],
                          authors=e["authors"], confidence=conf, why=why))
    return out


# --------------------------------------------------------------------------- GitHub


def github_repos(handle: str, http_get=default_get, top: int = 5) -> list[Source]:
    headers = {"Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    url = f"https://api.github.com/users/{urllib.parse.quote(handle)}/repos?per_page=100&sort=pushed"
    repos = json.loads(_get(http_get, url, headers))
    own = [r for r in repos if not r.get("fork")]
    by_stars = sorted(own, key=lambda r: r.get("stargazers_count", 0), reverse=True)[:top]
    recent = sorted(own, key=lambda r: r.get("pushed_at") or "", reverse=True)[:2]
    picked = {r["html_url"]: r for r in by_stars + recent}
    return [Source("repo", r["full_name"], r["html_url"], (r.get("pushed_at") or "")[:10],
                   "GitHub", stars=r.get("stargazers_count", 0), summary=r.get("description") or "",
                   confidence="verified", why=f"GitHub handle '{handle}' from the application")
            for r in picked.values()]


def _get(http_get, url, headers):
    try:
        return http_get(url, headers)
    except TypeError:  # simple test doubles take only the url
        return http_get(url)


# --------------------------------------------------------------------------- Semantic Scholar

S2 = "https://api.semanticscholar.org/graph/v1"


def s2_headers() -> dict:
    key = os.environ.get("S2_API_KEY")
    return {"x-api-key": key} if key else {}


def s2_find_author(name: str, affiliation: str = "", http_get=default_get) -> tuple[dict | None, str, list[dict]]:
    """Return (author, confidence, all name matches). Never guesses between namesakes."""
    q = urllib.parse.urlencode({"query": name, "limit": 10,
                                "fields": "name,affiliations,paperCount,citationCount,hIndex,url"})
    data = json.loads(_get(http_get, f"{S2}/author/search?{q}", s2_headers()))
    matches = [a for a in data.get("data", []) if same_name(a.get("name", ""), name)]
    if affiliation:
        hit = [a for a in matches if any(affiliation_matches(affiliation, x) for x in a.get("affiliations") or [])]
        if len(hit) == 1:
            return hit[0], "likely", matches
    if len(matches) == 1 and not affiliation:
        return matches[0], "unconfirmed", matches
    return None, "ambiguous" if matches else "not found", matches


def s2_papers(author_id: str, http_get=default_get) -> list[dict]:
    q = urllib.parse.urlencode({"fields": "title,year,venue,citationCount,url,externalIds,publicationDate",
                                "limit": 100})
    time.sleep(0 if http_get is not default_get else 1.1)  # be polite to the free API
    return json.loads(_get(http_get, f"{S2}/author/{author_id}/papers?{q}", s2_headers())).get("data", [])


def paper_url(p: dict) -> str:
    arxiv = (p.get("externalIds") or {}).get("ArXiv")
    return f"https://arxiv.org/abs/{arxiv}" if arxiv else p.get("url", "")


def s2_sources(name: str, affiliation: str = "", http_get=default_get, top: int = 3) -> tuple[list[Source], str]:
    author, conf, matches = s2_find_author(name, affiliation, http_get)
    if not author:
        note = (f"{len(matches)} Semantic Scholar authors share this name and none could be tied to the "
                f"application. Skipped rather than guessing." if matches else "No Semantic Scholar profile found.")
        return [], note
    papers = s2_papers(author["authorId"], http_get)
    cited = sorted(papers, key=lambda p: p.get("citationCount") or 0, reverse=True)[:top]
    recent = sorted(papers, key=lambda p: p.get("publicationDate") or str(p.get("year") or ""), reverse=True)[:2]
    why = f"Semantic Scholar profile matched on name{' and affiliation' if conf == 'likely' else ' only'}"
    out = {paper_url(p): Source("paper", p["title"], paper_url(p), p.get("publicationDate") or str(p.get("year") or ""),
                                p.get("venue") or "", citations=p.get("citationCount"), confidence=conf, why=why)
           for p in cited + recent if paper_url(p)}
    profile = Source("profile", f"{author['name']} on Semantic Scholar", author.get("url", ""),
                     summary=f"{author.get('paperCount', 0)} papers, {author.get('citationCount', 0)} citations, "
                             f"h-index {author.get('hIndex', 0)}", confidence=conf, why=why)
    return [profile, *out.values()], f"Matched Semantic Scholar author {author['authorId']} ({conf})."
