#!/usr/bin/env python3
"""Pipeline Pulse: a morning check of the recruiting pipeline.

Reads a normalized pipeline export (CSV or JSON, one row per application),
applies the team's SLAs, and writes a ranked digest of what needs attention:

  * decisions only a person can make (a strong candidate stalled, a "pass"
    that is still marked active, conflicting duplicate records), and
  * quick fixes the coordinator can just do (nudge for scorecards, book the
    interview, merge an obvious duplicate, assign an owner).

It never changes anything in the ATS. It only reads and reports.

Usage:
    python pipeline_pulse.py examples/pipeline.csv --now 2026-11-09T09:00
    python pipeline_pulse.py pipeline.json --config config.toml --format json

Standard library only (Python 3.11+).
"""
from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
import sys
import tomllib
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_CONFIG = {
    "sla": {
        # Hours a candidate can go without any update (the 72-hour promise).
        "stale_hours": 72,
        # Hours after an onsite or interview ends before scorecards are late.
        "feedback_hours": 24,
        # Hours an "availability submitted" candidate can wait to be booked.
        "availability_hours": 48,
        # Days of missing feedback after which it becomes an escalation.
        "feedback_escalate_days": 7,
    },
    "stages": {
        # Map your ATS stage names (lowercase) to a kind and a weight.
        # Later stages weigh more: a stalled finalist costs more than a stalled applicant.
        "kinds": {
            "application review": "review",
            "initial screen": "screen",
            "recruiter screen": "screen",
            "availability submitted": "availability",
            "role specific tech": "interview",
            "vertical aligned tech interview": "interview",
            "technical interview": "interview",
            "on site": "onsite",
            "onsite": "onsite",
            "gm interview": "final",
            "final interview": "final",
            "reference check": "offer",
            "offer": "offer",
        },
        "weights": {
            "review": 1,
            "screen": 2,
            "availability": 3,
            "interview": 3,
            "onsite": 4,
            "final": 5,
            "offer": 6,
            "other": 2,
        },
    },
    "signals": {
        "strong": ["strong", "liked", "top candidate", "priority", "excited", "great"],
        # Phrases that mean "we're saying no." Avoid bare "pass": in recruiting,
        # "passed tech" means the candidate cleared the round.
        # Read from the feedback column only: a note like "declined the Tuesday slot" isn't a no.
        "passed": ["not a fit", "no hire", "no-hire", "rejected", "reject", "passing on", "pass on them",
                   "decided to pass", "we'll pass"],
    },
}

FLAG_INFO = {
    # code: (base urgency, needs a decision?)
    "strong_stalled": (60, True),
    "passed_still_active": (45, True),
    "duplicate_conflict": (40, True),
    "feedback_overdue_escalate": (50, True),
    "feedback_overdue": (35, False),
    "availability_waiting": (35, False),
    "stale": (25, False),
    "duplicate": (20, False),
    "possible_duplicate": (12, False),
    "no_owner": (15, False),
    "comp_in_notes": (5, False),
}

WHY_FIRST = {
    "strong_stalled": "a strong candidate going quiet is the easiest way to lose a hire to another offer",
    "feedback_overdue_escalate": "the candidate finished an onsite and is still waiting on us for an answer",
    "passed_still_active": "we already have the answer, and the candidate is still waiting to hear it",
    "duplicate_conflict": "two records disagree, so nobody can trust where this candidate stands",
    "feedback_overdue": "late scorecards delay the decision for a candidate who already gave us a full day",
    "availability_waiting": "the candidate did their part and we haven't done ours",
    "stale": "the candidate hasn't heard from us within the promised window",
}

# Money-looking amounts: $240k, 240k, 1.2M, 150000, 150,000.
COMP_PATTERN = re.compile(
    r"\$\s?\d[\d,.]*\s?[kKmM]?\b|\b\d{2,3}(?:\.\d)?\s?[kK]\b|\b\d{1,2}(?:\.\d+)?\s?[mM]\b"
    r"|\b\d{2,3},\d{3}\b|\b\d{5,7}\b"
)
# Words that make a nearby amount compensation (not "a 7B base model on 300k clips").
COMP_WORDS = re.compile(r"\b(comp|compensation|salary|base salary|base pay|equity|ote|total comp|tc|"
                        r"expect\w*|asking|offer)\b", re.I)


def mentions_comp(text: str) -> bool:
    """True when a money-looking amount sits within a few words of a compensation word."""
    for m in COMP_PATTERN.finditer(text):
        window = text[max(0, m.start() - 40): m.end() + 40]
        if COMP_WORDS.search(window) or m.group(0).lstrip().startswith("$"):
            return True
    return False


@dataclass
class Application:
    candidate: str
    role: str
    stage: str
    last_activity: datetime | None
    owner: str = ""
    email: str = ""
    status: str = "Active"
    feedback_count: int | None = None
    feedback: str = ""
    notes: str = ""
    next_interview: datetime | None = None
    interview_completed_at: datetime | None = None
    application_id: str = ""
    row: int = 0

    @property
    def text(self) -> str:
        return f"{self.feedback} {self.notes}".lower()


@dataclass
class Flag:
    code: str
    candidate: str
    role: str
    stage: str
    owner: str
    issue: str
    action: str
    urgency: int
    decision: bool
    rows: list[int] = field(default_factory=list)


# --------------------------------------------------------------------------- parsing


def parse_when(value: str | None, now: datetime) -> datetime | None:
    """Parse an ISO date/datetime, or a relative phrase like '24 days ago' / 'today'."""
    if value is None:
        return None
    value = str(value).strip()
    if not value or value in {"—", "-", "none", "None", "n/a"}:
        return None
    low = value.lower()
    if low == "today":
        return now
    if low == "yesterday":
        return now - timedelta(days=1)
    rel = re.fullmatch(r"(\d+)\s*(minute|hour|day|week)s?\s+ago", low)
    if rel:
        n, unit = int(rel.group(1)), rel.group(2)
        return now - timedelta(**{f"{unit}s": n})
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"Can't read the date {value!r}. Use ISO format like 2026-11-05T14:00.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=now.tzinfo)
    return dt


def parse_count(value) -> int | None:
    if value is None or str(value).strip() in {"", "—", "-"}:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def load_rows(path: Path) -> list[dict]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text())
        return data["applications"] if isinstance(data, dict) else data
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def norm_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")


ALIASES = {
    "name": "candidate",
    "candidate_name": "candidate",
    "job": "role",
    "job_title": "role",
    "current_stage": "stage",
    "interview_stage": "stage",
    "last_activity_at": "last_activity",
    "updated_at": "last_activity",
    "recruiter": "owner",
    "feedback_scorecards": "feedback",
    "scorecards": "feedback_count",
    "next_interview_at": "next_interview",
    "onsite_completed_at": "interview_completed_at",
    "interview_ended_at": "interview_completed_at",
    "id": "application_id",
}


def to_applications(rows: list[dict], now: datetime, warnings: list[str] | None = None) -> list[Application]:
    apps = []
    warnings = warnings if warnings is not None else []
    for i, raw in enumerate(rows, start=2):  # row 1 is the header in a CSV
        r = {}
        for k, v in raw.items():
            if k is None:
                continue
            nk = norm_key(k)
            r[ALIASES.get(nk, nk)] = "" if v is None else str(v).strip()
        if not r.get("candidate"):
            continue
        feedback = r.get("feedback", "")
        count = parse_count(r.get("feedback_count"))
        if count is None and feedback:
            # A text column like "Passed tech" counts as one piece of feedback.
            count = 0 if feedback.lower() in {"none", "—", "-", ""} else 1
        try:
            last, nxt, done = (parse_when(r.get(k), now) for k in ("last_activity", "next_interview",
                                                                  "interview_completed_at"))
        except ValueError as e:
            warnings.append(f"Row {i} ({r['candidate']}) skipped: {e}")
            continue
        apps.append(
            Application(
                candidate=r["candidate"],
                role=r.get("role", ""),
                stage=r.get("stage", ""),
                last_activity=last,
                owner="" if r.get("owner", "").lower() in {"(none)", "none", "—"} else r.get("owner", ""),
                email=r.get("email", "").lower(),
                status=r.get("status", "Active") or "Active",
                feedback_count=count,
                feedback="" if feedback.lower() in {"none", "—", "-"} else feedback,
                notes=r.get("notes", ""),
                next_interview=nxt,
                interview_completed_at=done,
                application_id=r.get("application_id", ""),
                row=i,
            )
        )
    return apps


# --------------------------------------------------------------------------- rules


def stage_kind(stage: str, cfg: dict) -> str:
    return cfg["stages"]["kinds"].get(stage.strip().lower(), "other")


def stage_weight(stage: str, cfg: dict) -> int:
    return cfg["stages"]["weights"].get(stage_kind(stage, cfg), 2)


def has_signal(text: str, words: list[str]) -> bool:
    """Whole-word match, so "top" doesn't fire on "Stopped responding"."""
    return any(re.search(rf"(?<![a-z]){re.escape(w.lower())}(?![a-z])", text) for w in words)


def fmt_age(delta: timedelta) -> str:
    hours = delta.total_seconds() / 3600
    if hours < 48:
        return f"{hours:.0f} hours"
    return f"{hours / 24:.0f} days"


def norm_name(name: str) -> str:
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z ]", "", name.lower()).strip()


def make_flag(code: str, app: Application, issue: str, action: str, cfg: dict, extra: int = 0) -> Flag:
    base, decision = FLAG_INFO[code]
    urgency = base + 5 * stage_weight(app.stage, cfg) + extra
    if has_signal(app.text, cfg["signals"]["strong"]):
        urgency += 10
    return Flag(code, app.candidate, app.role, app.stage, app.owner or "unassigned",
                issue, action, urgency, decision, [app.row])


def check_application(app: Application, now: datetime, cfg: dict) -> list[Flag]:
    sla = cfg["sla"]
    flags: list[Flag] = []
    if app.status.lower() not in {"active", "lead", ""}:
        return flags
    kind = stage_kind(app.stage, cfg)
    text = app.text
    strong = has_signal(text, cfg["signals"]["strong"])
    passed = has_signal(app.feedback.lower(), cfg["signals"]["passed"])
    idle = (now - app.last_activity) if app.last_activity else None
    upcoming = app.next_interview is not None and app.next_interview > now
    overdue_by = (idle - timedelta(hours=sla["stale_hours"])) if idle else None
    extra = int(overdue_by.total_seconds() // 86400) if overdue_by and overdue_by > timedelta(0) else 0

    # 1. A pass that was never closed out.
    if passed:
        flags.append(make_flag(
            "passed_still_active", app,
            "Feedback says pass, but the application is still active.",
            "Confirm the decision with the owner, archive with the right reason, and send a warm, personal close-out.",
            cfg))
        return flags  # Other nudges don't matter once the answer is no.

    # 2. Feedback missing after an interview or onsite.
    finished = app.interview_completed_at
    if finished is None and kind == "onsite" and not upcoming and app.feedback_count == 0 and idle:
        finished = app.last_activity  # best guess: the last activity was the onsite itself
    if finished and finished < now and app.feedback_count == 0:
        late = now - finished - timedelta(hours=sla["feedback_hours"])
        if late > timedelta(0):
            if late > timedelta(days=sla["feedback_escalate_days"]):
                flags.append(make_flag(
                    "feedback_overdue_escalate", app,
                    f"No scorecards {fmt_age(now - finished)} after the interview.",
                    "Find out what's blocking feedback (missing interviewer? unclear rubric?), then book the debrief. "
                    "The candidate is waiting on us.",
                    cfg, extra))
            else:
                flags.append(make_flag(
                    "feedback_overdue", app,
                    f"Scorecards are {fmt_age(late)} past the {sla['feedback_hours']}-hour mark.",
                    "Send each interviewer a direct link to their scorecard and book the debrief.",
                    cfg))

    # 3. Availability submitted but nothing booked.
    if kind == "availability" and idle and idle > timedelta(hours=sla["availability_hours"]) and not upcoming:
        flags.append(make_flag(
            "availability_waiting", app,
            f"Gave availability {fmt_age(idle)} ago and nothing is booked.",
            "Their windows have probably passed: apologize, ask for fresh times, and book within the same week.",
            cfg, extra))

    # 4. Stalled. Strong candidates who stall need a decision, not a reminder.
    already = {f.code for f in flags}
    if idle and idle > timedelta(hours=sla["stale_hours"]) and not upcoming \
            and not already & {"availability_waiting", "feedback_overdue", "feedback_overdue_escalate"}:
        if strong:
            flags.append(make_flag(
                "strong_stalled", app,
                f"Strong signal in the notes, but no activity for {fmt_age(idle)}.",
                "Ask the owner what's holding it up today and agree on the next step. "
                "Strong candidates usually have other offers.",
                cfg, extra))
        else:
            flags.append(make_flag(
                "stale", app,
                f"No activity for {fmt_age(idle)} (promise is {sla['stale_hours']} hours).",
                "Send the candidate a status update and nudge the owner for the next step.",
                cfg, extra))

    if not app.owner:
        flags.append(make_flag(
            "no_owner", app, "No owner on this application.",
            "Assign an owner so it can't slip through the cracks.", cfg))

    if mentions_comp(app.notes):
        flags.append(make_flag(
            "comp_in_notes", app, "Compensation details are sitting in a general notes field.",
            "Move them to a private field visible only to the hiring team.", cfg))
    return flags


def check_duplicates(apps: list[Application], cfg: dict) -> tuple[list[Flag], set[int]]:
    """Return duplicate flags, plus the rows of the older copies (to skip other checks on them).

    Same email = the same person. Same name and role with one email missing = maybe;
    it's flagged for a look but nothing is suppressed. Different emails = different people
    (common names are routine in ML hiring).
    """
    flags = []
    older_rows: set[int] = set()
    for i, a in enumerate(apps):
        for b in apps[i + 1:]:
            same_email = bool(a.email) and a.email == b.email
            similar = difflib.SequenceMatcher(None, norm_name(a.candidate), norm_name(b.candidate)).ratio() >= 0.92
            maybe = similar and a.role.lower() == b.role.lower() and not (a.email and b.email)
            if not (same_email or maybe):
                continue
            newer, older = sorted([a, b], key=lambda x: x.last_activity or datetime.min.replace(tzinfo=timezone.utc),
                                  reverse=True)
            if maybe:
                flag = make_flag(
                    "possible_duplicate", newer,
                    "Same name and role, but one record has no email, so it may or may not be the same person.",
                    "Open both records and compare resumes or contact details before merging.", cfg)
            elif a.stage.lower() != b.stage.lower() or (a.owner and b.owner and a.owner != b.owner):
                flag = make_flag(
                    "duplicate_conflict", newer,
                    f"Two records (same email) disagree: '{newer.stage}' (owner {newer.owner or 'none'}) vs "
                    f"'{older.stage}' (owner {older.owner or 'none'}).",
                    f"Confirm with the owners which is current (likely '{newer.stage}', the most recent), "
                    "merge into that record, and keep all feedback.",
                    cfg)
                older_rows.add(older.row)
            else:
                flag = make_flag(
                    "duplicate", newer, "Duplicate profile (same email).",
                    "Merge the two records in the ATS, keeping the most recent activity and all feedback.", cfg)
                older_rows.add(older.row)
            flag.rows = sorted({a.row, b.row})
            flags.append(flag)
    return flags, older_rows


def run(apps: list[Application], now: datetime, cfg: dict) -> list[Flag]:
    flags, older_rows = check_duplicates(apps, cfg)
    for app in apps:
        app_flags = check_application(app, now, cfg)
        if app.row in older_rows:
            # The old copy of a duplicate gets merged away; only keep the privacy flag.
            app_flags = [f for f in app_flags if f.code == "comp_in_notes"]
        flags.extend(app_flags)
    flags.sort(key=lambda f: (-f.urgency, f.candidate))
    return flags


# --------------------------------------------------------------------------- output


def redact(text: str) -> str:
    return COMP_PATTERN.sub("[comp redacted]", text)


def to_markdown(flags: list[Flag], apps: list[Application], now: datetime, warnings: list[str] | None = None) -> str:
    decisions = [f for f in flags if f.decision]
    fixes = [f for f in flags if not f.decision]
    active = [a for a in apps if a.status.lower() in {"active", "lead", ""}]
    flagged = {f.candidate for f in flags}
    lines = [
        f"# Pipeline Pulse: {now:%A, %B} {now.day}",
        "",
        f"{len(active)} active applications checked. {len(flags)} items across {len(flagged)} candidates: "
        f"**{len(decisions)} need a decision** and **{len(fixes)} are quick fixes**.",
        "",
    ]
    for title, group, blurb in [
        ("Needs a decision", decisions, "Only the owner or hiring manager can resolve these."),
        ("Quick fixes", fixes, "The coordinator can take care of these today."),
    ]:
        lines += [f"## {title}", "", blurb, ""]
        if not group:
            lines += ["Nothing here today.", ""]
            continue
        lines += ["| # | Candidate | Stage | Owner | What's wrong | Next step |",
                  "| --- | --- | --- | --- | --- | --- |"]
        for n, f in enumerate(group, 1):
            who = f"{f.candidate} ({f.role})" if f.role else f.candidate
            lines.append(f"| {n} | {who} | {f.stage} | {f.owner} | {redact(f.issue)} | {redact(f.action)} |")
        lines.append("")
    top = flags[0] if flags else None
    if top:
        lines += ["## Why the top item leads", "",
                  f"**{top.candidate}** is first: {WHY_FIRST.get(top.code, 'it carries the most risk today')}. "
                  f"Items are ranked by issue type, how late in the process the candidate is, how far past the "
                  f"promise we are, and whether the notes show a strong signal.", ""]
    if warnings:
        lines += ["## Rows that couldn't be read", ""] + [f"- {w}" for w in warnings] + [""]
    lines += ["_Read-only report. Nothing was changed in the ATS. Notes are never printed, and compensation "
              "figures are redacted from everything that is._", ""]
    return "\n".join(lines)


def load_config(path: Path | None) -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    if path:
        user = tomllib.loads(path.read_text())
        for section, values in user.items():
            if isinstance(values, dict) and section in cfg:
                for k, v in values.items():
                    if isinstance(v, dict) and isinstance(cfg[section].get(k), dict):
                        cfg[section][k].update({kk.lower(): vv for kk, vv in v.items()})
                    else:
                        cfg[section][k] = v
            else:
                cfg[section] = values
    return cfg


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("export", type=Path, help="Pipeline export (.csv or .json)")
    p.add_argument("--config", type=Path, help="TOML file with SLAs and stage names")
    p.add_argument("--now", help="Check as of this time (ISO). Default: now.")
    p.add_argument("--tz", default="America/Los_Angeles", help="HQ time zone for dates without an offset")
    p.add_argument("--format", choices=["markdown", "json"], default="markdown")
    p.add_argument("-o", "--output", type=Path)
    args = p.parse_args(argv)

    hq = ZoneInfo(args.tz)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(hq)
    now = now.replace(tzinfo=hq) if now.tzinfo is None else now.astimezone(hq)
    cfg = load_config(args.config)
    warnings: list[str] = []
    apps = to_applications(load_rows(args.export), now, warnings)
    flags = run(apps, now, cfg)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    if args.format == "json":
        out = json.dumps([{**asdict(f), "issue": redact(f.issue), "action": redact(f.action)} for f in flags],
                         indent=2)
    else:
        out = to_markdown(flags, apps, now, warnings)
    if args.output:
        args.output.write_text(out)
        print(f"Wrote {args.output} ({len(flags)} items).", file=sys.stderr)
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
