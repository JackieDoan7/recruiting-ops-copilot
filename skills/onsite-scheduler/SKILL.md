---
name: onsite-scheduler
description: Build interview schedules across time zones and calendars, with a backup for every round, itinerary emails and calendar files. Use for onsite loops, remote screens, reschedules.
---

# Onsite Scheduler

Turns interviewer calendars and candidate availability into a proposed
schedule, then drafts everything that goes out with it. It **proposes**; the
coordinator reviews and sends.

What it does that's easy to get wrong by hand:

- **Locks in the hardest schedules first.** Candidates with the fewest
  workable times are booked first, and each one avoids taking slots the
  others still need.
- **Keeps an onsite on one day,** back to back where possible, inside office
  hours, with an optional buffer between rounds.
- **Keeps the hard rounds when not everything fits.** A three-person panel
  stays onsite; a 1:1 moves to a video call, with a concrete time when that
  person is free.
- **Decides the backup plan up front** for every interviewer in every round.
- **Uses office time (PT) everywhere** on our side. Candidate time zones are only used to read their availability; calendar invites carry the time zone, so candidates see their own local time automatically.

## Steps

1. **Collect the inputs** into a request JSON (see `examples/request.json`):
   - interviewer free blocks: from Google Calendar free/busy or what the
     team tells you. Free/busy returns *busy* times, so invert them: for each
     interviewer and each day, the free blocks are office hours minus busy
     events (and minus their "no meetings" holds). HQ time unless a
     `timezone` is given.
   - each candidate's availability in their own time zone, their type
     (`onsite` or `remote`), and their rounds
   - optional `office_notes`: anything a first-time visitor should know
     (e.g. a shoes-off office, with a request for their shoe size)
   - per round: `minutes`, required `interviewers`, or a pool with
     `any_of` + `min`/`max`; optional `backups` and a `window` (e.g.
     mornings only, 09:00–12:00)
2. **Run:** `python scripts/schedule.py request.json --out out/`
3. **Review `out/schedule.md`** with the user. Resolve every "Flag before
   sending" and every "No backup named" line before anything goes out.
4. **Send** after the user approves: the `*-itinerary.md` drafts (onsite
   candidates) and the `.ics` files, or create the events in Google Calendar
   if that connector is available. Never send invites without approval.

## Same-day changes

If an interviewer drops out, read that round's backup plan in the last
`schedule.md`. If there's a same-time cover, confirm with them and update
the invite. If not, build a request with **only the affected candidate**:
keep the rounds that already happened out of it, remove the absent person's
free time, and add everyone else's existing interviews as busy time. Never
rerun the whole week; that would reshuffle invites that already went out.
Then use the "Same-day reschedule" note in `references/templates.md`.

## Email voice

Use `references/templates.md` for the itinerary, same-day reschedule and warm
rejection. Warm, short, respectfully direct. Times always include a time zone.
