#!/usr/bin/env python3
"""Onsite Scheduler: build interview loops across calendars and time zones.

Given interviewer free time, each candidate's availability and the rounds they
need, it:

  1. books candidates in order of how few options they have (lock in the
     hardest schedules first, before easier ones take the scarce slots),
  2. places every round of an onsite on the same day, back to back where
     possible, with optional buffers and time windows,
  3. tries listed backup interviewers when a primary can't make it,
  4. explains anything it couldn't place and suggests the next move, and
  5. writes a schedule summary, a candidate itinerary email draft, and an
     .ics calendar file per candidate.

It proposes a schedule. A person reviews it before any invite goes out.

Usage:
    python schedule.py examples/request.json --out examples/output

Standard library only (Python 3.11+).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

MAX_NODES = 200_000  # per day; if hit, the plan is still valid and the summary says so


# --------------------------------------------------------------------------- model


@dataclass(frozen=True)
class Slot:
    start: datetime  # aware, UTC
    end: datetime

    def overlaps(self, other: "Slot", buffer: timedelta = timedelta(0)) -> bool:
        return self.start < other.end + buffer and other.start < self.end + buffer

    def within(self, other: "Slot") -> bool:
        return other.start <= self.start and self.end <= other.end


@dataclass
class Round:
    name: str
    minutes: int
    interviewers: list[str] = field(default_factory=list)  # all required
    any_of: list[str] = field(default_factory=list)  # pool, at least min_any
    min_any: int = 1
    max_any: int | None = None
    window: tuple[time, time] | None = None  # HQ local time window (e.g. mornings only)
    backups: list[str] = field(default_factory=list)


@dataclass
class Candidate:
    name: str
    tz: ZoneInfo
    kind: str  # "onsite" or "remote"
    availability: list[Slot]
    rounds: list[Round]
    email: str = ""
    role: str = ""
    fixed_order: bool = False


@dataclass
class Placement:
    round: Round
    slot: Slot
    people: tuple[str, ...]
    used_backup: str | None = None
    if_dropped: list[str] = field(default_factory=list)  # backup plan per interviewer


@dataclass
class Result:
    candidate: Candidate
    placed: list[Placement]
    missing: list[tuple[Round, str]]
    options: int  # how many feasible starts it had before booking (for ordering)
    capped: bool = False  # search stopped at its limit; plan is good but may not be the best


# --------------------------------------------------------------------------- parsing


def parse_dt(value: str, tz: ZoneInfo) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(timezone.utc)


def parse_blocks(blocks: list, tz: ZoneInfo) -> list[Slot]:
    out = []
    for b in blocks:
        btz = ZoneInfo(b["timezone"]) if "timezone" in b else tz
        s = Slot(parse_dt(b["start"], btz), parse_dt(b["end"], btz))
        if s.end <= s.start:
            raise ValueError(f"Block ends before it starts: {b}")
        out.append(s)
    return sorted(out, key=lambda s: s.start)


def parse_hhmm(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def load_request(data: dict):
    hq = ZoneInfo(data.get("hq_timezone", "America/Los_Angeles"))
    settings = {
        "hq": hq,
        "slot": timedelta(minutes=data.get("slot_minutes", 15)),
        "buffer": timedelta(minutes=data.get("buffer_minutes", 0)),
        "day_start": parse_hhmm(data.get("day_start", "09:00")),
        "day_end": parse_hhmm(data.get("day_end", "17:30")),
        "company": data.get("company", ""),
        "office_address": data.get("office_address", ""),
        "coordinator": data.get("coordinator", "Your recruiting coordinator"),
        "hotels": data.get("hotels", []),
        "travel_link": data.get("travel_link", ""),
        "office_notes": data.get("office_notes", ""),
        "stamp": datetime.now(timezone.utc),
    }
    free = {}
    for person, info in data["interviewers"].items():
        ptz = ZoneInfo(info["timezone"]) if "timezone" in info else hq
        free[person] = parse_blocks(info["free"], ptz)
    candidates = []
    for c in data["candidates"]:
        ctz = ZoneInfo(c.get("timezone", data.get("hq_timezone", "America/Los_Angeles")))
        rounds = []
        for r in c["rounds"]:
            window = tuple(parse_hhmm(x) for x in r["window"]) if r.get("window") else None
            rounds.append(Round(
                name=r["name"], minutes=int(r["minutes"]),
                interviewers=list(r.get("interviewers", [])),
                any_of=list(r.get("any_of", [])), min_any=int(r.get("min", 1)),
                max_any=r.get("max"), window=window, backups=list(r.get("backups", [])),
            ))
        for person in {p for r in rounds for p in r.interviewers + r.any_of + r.backups}:
            if person not in free:
                raise ValueError(f"{c['name']}: interviewer {person!r} has no calendar in 'interviewers'.")
        if not c.get("availability"):
            raise ValueError(f"{c['name']}: add at least one availability window.")
        candidates.append(Candidate(
            name=c["name"], tz=ctz, kind=c.get("type", "onsite"),
            availability=parse_blocks(c["availability"], ctz), rounds=rounds,
            email=c.get("email", ""), role=c.get("role", ""), fixed_order=bool(c.get("fixed_order", False)),
        ))
    return settings, free, candidates


# --------------------------------------------------------------------------- search


def is_free(person: str, slot: Slot, free: dict, booked: dict) -> bool:
    if not any(slot.within(b) for b in free[person]):
        return False
    return not any(slot.overlaps(b) for b in booked.get(person, []))


def candidate_starts(cand: Candidate, rnd: Round, s: dict):
    """Every aligned start time inside the candidate's availability and office hours."""
    hq, step, dur = s["hq"], s["slot"], timedelta(minutes=rnd.minutes)
    for block in cand.availability:
        local = block.start.astimezone(hq)
        # Align to the grid in HQ local time (e.g. :00, :15, :30, :45).
        minutes = local.hour * 60 + local.minute
        step_min = int(step.total_seconds() // 60)
        pad = (-minutes) % step_min
        t = block.start + timedelta(minutes=pad)
        while t + dur <= block.end:
            lt, le = t.astimezone(hq), (t + dur).astimezone(hq)
            day_open = datetime.combine(lt.date(), s["day_start"], hq)
            day_close = datetime.combine(lt.date(), s["day_end"], hq)
            ok = day_open <= lt and le <= day_close
            if ok and rnd.window:
                w0 = datetime.combine(lt.date(), rnd.window[0], hq)
                w1 = datetime.combine(lt.date(), rnd.window[1], hq)
                ok = w0 <= lt and le <= w1
            if ok:
                yield Slot(t, t + dur)
            t += step


def options_for(cand: Candidate, rnd: Round, s: dict, free: dict, booked: dict,
                use_backups: bool = False) -> list[Placement]:
    """All feasible placements for one round, given what's already booked."""
    out = []
    for slot in candidate_starts(cand, rnd, s):
        required = list(rnd.interviewers)
        swapped = None
        missing = [p for p in required if not is_free(p, slot, free, booked)]
        if missing:
            if not use_backups or len(missing) > 1:
                continue
            backup = next((b for b in rnd.backups if b not in required and is_free(b, slot, free, booked)), None)
            if not backup:
                continue
            swapped = f"{backup} (backup for {missing[0]})"
            required = [backup if p == missing[0] else p for p in required]
        pool = [p for p in rnd.any_of
                if p not in required and is_free(p, slot, free, booked)]
        if rnd.any_of and len(pool) < rnd.min_any:
            continue
        if rnd.max_any is not None:
            pool = pool[: int(rnd.max_any)]
        out.append(Placement(rnd, slot, tuple(required + pool), swapped))
    return out


def reschedule_cost(rnd: Round) -> int:
    """How painful a round is to move: minutes times the people who must all be there."""
    return rnd.minutes * (1 + len(rnd.interviewers) + rnd.min_any * bool(rnd.any_of))


def hq_day(slot: Slot, hq: ZoneInfo) -> date:
    return slot.start.astimezone(hq).date()


def solve_candidate(cand: Candidate, s: dict, free: dict, booked: dict,
                    pending: list[Placement] | None = None) -> tuple[list[Placement], list[Round], bool]:
    """Place as many rounds as possible. Among plans that place the same number, keep the rounds
    that are hardest to redo, then take the fewest slots other candidates still need, then the
    shortest day, then the listed round order, then the earliest start.

    An onsite happens on one day, so each day is searched on its own (much smaller searches) and
    the best day wins. Returns (placed, missing, capped)."""
    opts = {r.name: options_for(cand, r, s, free, booked) for r in cand.rounds}
    # Rounds that can't be placed with their primary interviewers get their backups considered.
    for r in cand.rounds:
        if not opts[r.name] and r.backups:
            opts[r.name] = options_for(cand, r, s, free, booked, use_backups=True)
    pending = pending or []
    harm = {id(p): sum(1 for q in pending if set(p.people) & set(q.people) and p.slot.overlaps(q.slot))
            for r in cand.rounds for p in opts[r.name]}
    index = {r.name: i for i, r in enumerate(cand.rounds)}

    def score(plan: list[Placement]):
        if not plan:
            return (0, 0, 0, 0, 0, 0)
        span = (max(p.slot.end for p in plan) - min(p.slot.start for p in plan)).total_seconds()
        seq = sorted(plan, key=lambda p: p.slot.start)
        inversions = sum(1 for a, b in zip(seq, seq[1:]) if index[a.round.name] > index[b.round.name])
        taken = sum(harm[id(p)] for p in plan)
        # When not everything fits, keep the rounds that are hardest to redo later (long, many people);
        # a 1:1 can move to a video call more easily than a three-person panel.
        value = sum(reschedule_cost(p.round) for p in plan)
        return (-len(plan), -value, taken, span, inversions, min(p.slot.start for p in plan).timestamp())

    def consistent(p: Placement, plan: list[Placement]) -> bool:
        for q in plan:
            if p.slot.overlaps(q.slot, s["buffer"]):
                return False
            if set(p.people) & set(q.people) and p.slot.overlaps(q.slot):
                return False
            if cand.fixed_order and (index[p.round.name] < index[q.round.name]) != (p.slot.start < q.slot.start):
                return False
        return True

    def search(day_opts: dict[str, list[Placement]]) -> tuple[tuple | None, list[Placement], bool]:
        order = sorted(cand.rounds, key=lambda r: len(day_opts[r.name]))  # most constrained first
        best: dict = {"key": None, "plan": []}
        nodes = 0
        # Seed with a quick greedy plan so the exhaustive search can prune from the start.
        seed: list[Placement] = []
        for r in order:
            p = next((p for p in day_opts[r.name] if consistent(p, seed)), None)
            if p:
                seed.append(p)
        best["key"], best["plan"] = score(seed), list(seed)
        placeable = [r for r in order if day_opts[r.name]]
        # A plan that places everything, back to back, in the listed order, taking nothing others
        # need, can't be beaten on anything but start time: stop searching once we have one.
        tight = sum(r.minutes for r in placeable) * 60 + s["buffer"].total_seconds() * max(len(placeable) - 1, 0)

        def perfect(key) -> bool:
            return -key[0] == len(placeable) and key[2] == 0 and key[3] <= tight and key[4] == 0

        def dfs(i: int, plan: list[Placement]):
            nonlocal nodes
            nodes += 1
            if nodes > MAX_NODES or perfect(best["key"]):
                return
            if len(plan) + (len(order) - i) < -best["key"][0]:
                return  # can't place as many rounds as the best plan so far
            if i == len(order):
                key = score(plan)
                if key < best["key"]:
                    best["key"], best["plan"] = key, list(plan)
                return
            r = order[i]
            for p in day_opts[r.name]:
                if consistent(p, plan):
                    plan.append(p)
                    dfs(i + 1, plan)
                    plan.pop()
            dfs(i + 1, plan)  # leave this round unplaced

        dfs(0, [])
        return best["key"], best["plan"], nodes > MAX_NODES

    if cand.kind == "onsite":
        days = sorted({hq_day(p.slot, s["hq"]) for ps in opts.values() for p in ps})
        groups = [{n: [p for p in ps if hq_day(p.slot, s["hq"]) == d] for n, ps in opts.items()} for d in days]
    else:
        groups = [opts]
    # Try the days that can fit the most rounds first, and skip days that can't beat the best so far.
    groups.sort(key=lambda g: -sum(1 for ps in g.values() if ps))
    best_key, best_plan, capped = None, [], False
    for g in groups or [opts]:
        if best_key is not None and sum(1 for ps in g.values() if ps) < -best_key[0]:
            continue
        key, plan, hit = search(g)
        capped = capped or hit
        if best_key is None or key < best_key:
            best_key, best_plan = key, plan
    placed = sorted(best_plan, key=lambda p: p.slot.start)
    placed_names = {p.round.name for p in placed}
    return placed, [r for r in cand.rounds if r.name not in placed_names], capped


def next_joint_slot(people: list[str], minutes: int, after: datetime, free: dict, booked: dict,
                    s: dict) -> Slot | None:
    """Earliest weekday slot in office hours after `after` when everyone in `people` is free together."""
    if not people:
        return None
    dur, hq = timedelta(minutes=minutes), s["hq"]
    for block in free[people[0]]:
        t = max(block.start, after)
        while t + dur <= block.end:
            slot = Slot(t, t + dur)
            a, b = t.astimezone(hq), (t + dur).astimezone(hq)
            in_hours = a.weekday() < 5 and s["day_start"] <= a.time() and b.time() <= s["day_end"] \
                and a.date() == b.date()
            if in_hours and all(is_free(p, slot, free, booked) for p in people):
                return slot
            t += s["slot"]
    return None


def explain(cand: Candidate, rnd: Round, s: dict, free: dict, booked: dict, placed: list[Placement]) -> str:
    """Say why a round couldn't be placed, and what to do about it."""
    hq = s["hq"]
    people = rnd.interviewers or rnd.any_of
    reasons = []
    for person in people:
        solo = Round(rnd.name, rnd.minutes, [person], window=rnd.window)
        if not options_for(cand, solo, s, free, {}):
            if any(b.overlaps(a) for b in free[person] for a in cand.availability):
                reasons.append(f"{person} isn't free for a full {rnd.minutes} minutes while {cand.name} is here.")
            else:
                reasons.append(f"{person} has no free time while {cand.name} is here.")
        elif not options_for(cand, solo, s, free, booked):
            own = [p.round.name for p in placed if person in p.people]
            if own:
                reasons.append(f"{person}'s only open time goes to the {' and '.join(own)}, which is harder "
                               "to move to another day.")
            else:
                reasons.append(f"{person}'s open time is already booked for another candidate.")
    if not reasons:
        reasons.append("Every open time conflicts with another round on this schedule.")
    required = rnd.interviewers or rnd.any_of[: rnd.min_any]
    after = cand.availability[-1].end if cand.availability else datetime.now(timezone.utc)
    later = next_joint_slot(required, rnd.minutes, after, free, booked, s)
    if later:
        move = f"offer a video call on {fmt_range(later, hq)}, when {', '.join(required)} " \
               f"{'is' if len(required) == 1 else 'are'} free"
    elif cand.kind == "onsite":
        move = "offer a video call in the following days, or swap in another qualified interviewer"
    else:
        move = "ask the candidate for more times, or add another qualified interviewer"
    if rnd.backups:
        move += f" (backups tried: {', '.join(rnd.backups)})"
    return " ".join(reasons) + f" Next move: {move}."


def plan_backups(results: list[Result], free: dict, booked: dict) -> None:
    """For every booked round, decide now what happens if each interviewer drops out that day."""
    for res in results:
        onsite = res.candidate.kind == "onsite"
        for p in res.placed:
            notes, uncovered = [], []
            for person in p.people:
                others = [x for x in p.people if x != person]
                pool_left = [x for x in others if x in p.round.any_of]
                if person in p.round.any_of and len(pool_left) >= p.round.min_any:
                    notes.append(f"If {person} drops, {' and '.join(pool_left)} can do it alone.")
                    continue
                pool = p.round.any_of if person in p.round.any_of else []
                cover = next((x for x in list(pool) + p.round.backups
                              if x not in p.people and is_free(x, p.slot, free, booked)), None)
                if cover:
                    notes.append(f"If {person} drops, {cover} covers at the same time.")
                elif p.round.backups or pool:
                    notes.append(f"If {person} drops, the backups are busy then: "
                                 + ("move a later round up or add a video call later in the week."
                                    if onsite else "reschedule with the candidate right away."))
                else:
                    uncovered.append(person)
            if uncovered:
                notes.append(f"No backup named for {', '.join(uncovered)}. Pick one before sending.")
            p.if_dropped = notes


def schedule(settings: dict, free: dict, candidates: list[Candidate]) -> list[Result]:
    booked: dict[str, list[Slot]] = {}
    counts = {c.name: sum(len(options_for(c, r, settings, free, {})) for r in c.rounds) for c in candidates}
    # Lock in the hardest schedules first: fewest options, then most rounds.
    ordered = sorted(candidates, key=lambda c: (counts[c.name], -len(c.rounds)))
    results = []
    for n, cand in enumerate(ordered):
        # What the candidates still waiting could use, so this one avoids taking it when it can.
        pending = [p for other in ordered[n + 1:] for r in other.rounds
                   for p in options_for(other, r, settings, free, booked)]
        placed, missing, capped = solve_candidate(cand, settings, free, booked, pending)
        for p in placed:
            for person in p.people:
                booked.setdefault(person, []).append(p.slot)
        reasons = [(r, explain(cand, r, settings, free, booked, placed)) for r in missing]
        results.append(Result(cand, placed, reasons, counts[cand.name], capped))
    plan_backups(results, free, booked)
    return results


# --------------------------------------------------------------------------- output


def fmt_time(dt: datetime, tz: ZoneInfo) -> str:
    local = dt.astimezone(tz)
    hour = local.hour % 12 or 12
    suffix = "AM" if local.hour < 12 else "PM"
    return f"{hour} {suffix}" if local.minute == 0 else f"{hour}:{local.minute:02d} {suffix}"


def fmt_range(slot: Slot | None, tz: ZoneInfo) -> str:
    if slot is None:
        return ""
    a, b = slot.start.astimezone(tz), slot.end.astimezone(tz)
    return f"{a:%a %b} {a.day}, {fmt_time(slot.start, tz)}–{fmt_time(slot.end, tz)} {a.tzname()}"


def tzlabel(dt: datetime, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).tzname() or str(tz)


ZONE_LABELS = {"America/Los_Angeles": "PT", "America/Denver": "MT", "America/Chicago": "CT", "America/New_York": "ET"}


def zone_label(dt: datetime, tz: ZoneInfo) -> str:
    """'PT' rather than 'PST'/'PDT', so the label doesn't change with daylight saving."""
    return ZONE_LABELS.get(getattr(tz, "key", ""), tzlabel(dt, tz))


def summary_markdown(results: list[Result], s: dict) -> str:
    hq = s["hq"]
    lines = ["# Interview schedule (proposed)", "",
             "Booked in order of fewest options first, so the hardest schedules got first pick.", "",
             "All times are office time. Calendar invites carry the time zone, so each candidate's "
             "calendar shows them in their own time.", "",
             "| Order | Candidate | Type | Open start times before booking | Rounds placed |",
             "| --- | --- | --- | --- | --- |"]
    for n, r in enumerate(results, 1):
        lines.append(f"| {n} | {r.candidate.name} | {r.candidate.kind} | {r.options} | "
                     f"{len(r.placed)} of {len(r.candidate.rounds)} |")
    lines.append("")
    for r in results:
        c = r.candidate
        lines += [f"## {c.name}" + (f" ({c.role})" if c.role else ""), ""]
        if r.placed:
            hq_tz = zone_label(r.placed[0].slot.start, hq)
            days = sorted({p.slot.start.astimezone(hq).date() for p in r.placed})
            for d in days:  # one table per day, so multi-day remote loops show the right dates
                lines += [f"**{d:%A, %B} {d.day}**", "",
                          f"| Round | {hq_tz} | With | Note |",
                          "| --- | --- | --- | --- |"]
                for p in (p for p in r.placed if p.slot.start.astimezone(hq).date() == d):
                    hq_t = f"{fmt_time(p.slot.start, hq)}–{fmt_time(p.slot.end, hq)}"
                    note = f"Using {p.used_backup}" if p.used_backup else ""
                    lines.append(f"| {p.round.name} | {hq_t} | {', '.join(p.people) or '—'} | {note} |")
                lines.append("")
        if r.capped:
            lines += ["_The search hit its time limit for this candidate. The plan above is valid, but a "
                      "better one may exist: give it a quick look._", ""]
        if r.missing:
            lines += ["**Flag before sending:**", ""]
            for rnd, why in r.missing:
                lines.append(f"- **{rnd.name}** couldn't be placed. {why}")
            lines.append("")
        backups = [p for p in r.placed if p.used_backup]
        for p in backups:
            lines.append(f"- {p.round.name} uses a backup interviewer: {p.used_backup}. Confirm with them first.")
        if backups:
            lines.append("")
        plans = [(p, note) for p in r.placed for note in p.if_dropped]
        if plans:
            lines += ["**Backup plan (decided before anyone drops out):**", ""]
            lines += [f"- **{p.round.name}:** {note}" for p, note in plans]
            lines.append("")
    return "\n".join(lines)


def itinerary_email(r: Result, s: dict) -> str:
    c, hq = r.candidate, s["hq"]
    first = c.name.split()[0]
    if not r.placed:
        return ""
    day = r.placed[0].slot.start.astimezone(hq)
    lines = [f"Subject: Your {s['company'] + ' ' if s['company'] else ''}onsite on {day:%A, %B} {day.day}", "",
             f"Hi {first},", "",
             f"We're excited to host you on {day:%A, %B} {day.day}. Here's the plan "
             f"(times are {zone_label(r.placed[0].slot.start, hq)}, local to our office; the calendar invites will show "
             "in your own time zone):", ""]
    for p in r.placed:
        names = ", ".join(p.people)
        who = "" if not p.people else (f" ({names})" if " with " in p.round.name.lower() else f" with {names}")
        lines.append(f"- {fmt_time(p.slot.start, hq)}–{fmt_time(p.slot.end, hq)}: {p.round.name}{who}")
    lines.append("")
    if s["office_address"]:
        lines += [f"**Where:** {s['office_address']}. I'll meet you in the lobby.", ""]
    if c.kind == "onsite":
        if s["travel_link"]:
            lines += [f"**Travel:** book flights and your hotel here, and we'll cover it directly: {s['travel_link']}. "
                      "Please use your legal name exactly as it appears on your ID.", ""]
        if s["hotels"]:
            lines += ["**Hotels close to the office:** " + "; ".join(s["hotels"]) + ".", ""]
        if s["office_notes"]:
            lines += [f"**Good to know:** {s['office_notes']}", ""]
        lines += ["**Before you come:** please reply with any dietary restrictions or accessibility needs, "
                  "and anything that would make the day easier for you.", ""]
    if r.missing:
        lines += ["[Coordinator: resolve the flagged rounds before sending.]", ""]
    lines += ["If anything changes, just reply here and I'll take care of it.", "", "Best,", s["coordinator"]]
    return "\n".join(lines)


def fold(line: str) -> str:
    """Fold a content line at 75 octets, as calendar apps expect."""
    raw, out = line.encode(), []
    while len(raw) > 75:
        cut = 75 if not out else 74
        while cut and (raw[cut] & 0xC0) == 0x80:  # don't split a UTF-8 character
            cut -= 1
        out.append(raw[:cut].decode())
        raw = raw[cut:]
    out.append(raw.decode())
    return "\r\n ".join(out)


def ics(r: Result, s: dict) -> str:
    def stamp(dt: datetime) -> str:
        return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def esc(text: str) -> str:
        return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

    out = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//recruiting-ops-copilot//onsite-scheduler//EN",
           "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    for p in r.placed:
        uid = hashlib.sha1(f"{r.candidate.name}|{p.round.name}|{p.slot.start}".encode()).hexdigest()[:16]
        out += ["BEGIN:VEVENT", f"UID:{uid}@recruiting-ops-copilot",
                f"DTSTAMP:{stamp(s['stamp'])}", f"DTSTART:{stamp(p.slot.start)}", f"DTEND:{stamp(p.slot.end)}",
                f"SUMMARY:{esc(p.round.name + ': ' + r.candidate.name)}",
                f"DESCRIPTION:{esc('Interviewers: ' + (', '.join(p.people) or 'none'))}"]
        if s["office_address"] and r.candidate.kind == "onsite":
            out.append(f"LOCATION:{esc(s['office_address'])}")
        out.append("END:VEVENT")
    out.append("END:VCALENDAR")
    return "\r\n".join(fold(line) for line in out) + "\r\n"


def slug(name: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in name.lower()).strip("-")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Build interview schedules across time zones.")
    p.add_argument("request", type=Path, help="JSON request (see examples/request.json)")
    p.add_argument("--out", type=Path, help="Folder for schedule.md, itineraries and .ics files")
    p.add_argument("--stamp", help="Calendar creation time (ISO, UTC). Default: now.")
    args = p.parse_args(argv)
    settings, free, candidates = load_request(json.loads(args.request.read_text()))
    settings["stamp"] = datetime.fromisoformat(args.stamp.replace("Z", "+00:00")) if args.stamp \
        else datetime.now(timezone.utc)
    results = schedule(settings, free, candidates)
    summary = summary_markdown(results, settings)
    if not args.out:
        print(summary)
        return 0
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "schedule.md").write_text(summary)
    for r in results:
        if r.placed:
            (args.out / f"{slug(r.candidate.name)}.ics").write_bytes(ics(r, settings).encode())  # keep CRLF exactly
            if r.candidate.kind == "onsite":
                (args.out / f"{slug(r.candidate.name)}-itinerary.md").write_text(itinerary_email(r, settings))
    print(summary)
    print(f"\nWrote files to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
