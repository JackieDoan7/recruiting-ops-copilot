import json
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest

import schedule as sch
from conftest import SKILLS

REQUEST = SKILLS / "onsite-scheduler" / "examples" / "request.json"
PT = ZoneInfo("America/Los_Angeles")


@pytest.fixture(scope="module")
def solved():
    settings, free, cands = sch.load_request(json.loads(REQUEST.read_text()))
    return settings, free, cands, {r.candidate.name: r for r in sch.schedule(settings, free, cands)}


def local(p, tz=PT):
    return p.slot.start.astimezone(tz).strftime("%a %H:%M")


def test_every_booking_respects_every_calendar(solved):
    settings, free, _, results = solved
    seen = {}
    for r in results.values():
        for p in r.placed:
            assert any(p.slot.within(a) for a in r.candidate.availability), p.round.name
            for person in p.people:
                assert any(p.slot.within(b) for b in free[person]), (person, p.round.name)
                for other in seen.get(person, []):
                    assert not p.slot.overlaps(other), f"{person} double-booked"
                seen.setdefault(person, []).append(p.slot)
            start = p.slot.start.astimezone(PT).time()
            assert settings["day_start"] <= start and p.slot.end.astimezone(PT).time() <= settings["day_end"]


def test_onsites_are_one_day_without_overlaps(solved):
    *_, results = solved
    for name in ("Victor Hale", "Clara Novak"):
        placed = results[name].placed
        assert len({p.slot.start.astimezone(PT).date() for p in placed}) == 1
        for a, b in zip(placed, placed[1:]):
            assert a.slot.end <= b.slot.start


def test_hardest_schedules_book_first(solved):
    *_, results = solved
    assert list(results) == ["Tom Fischer", "Aisha Bello", "Clara Novak", "Victor Hale"]


def test_london_screen_leaves_wednesday_for_the_onsite(solved):
    *_, results = solved
    tom = results["Tom Fischer"].placed[0]
    # 9:00 PT on Thursday is 17:00 in London, inside working hours, and it keeps
    # Felix's Wednesday morning free for Victor's onsite.
    assert local(tom) == "Thu 09:00"
    assert local(tom, ZoneInfo("Europe/London")) == "Thu 17:00"
    assert len(results["Victor Hale"].placed) == 4


def test_keeps_the_panel_and_moves_the_one_on_one(solved):
    *_, results = solved
    elena = results["Clara Novak"]
    assert "Presentation" in {p.round.name for p in elena.placed}
    (missing, why), = elena.missing
    assert missing.name == "GM interview"
    assert "Mon Nov 23, 10 AM–10:45 AM PST" in why  # Hana's next free time, converted from Eastern


def test_backup_plan_for_every_interviewer(solved):
    *_, results = solved
    tom = results["Tom Fischer"].placed[0]
    assert tom.if_dropped == ["If Felix drops, Owen covers at the same time."]
    marco = {p.round.name: p for p in results["Victor Hale"].placed}
    assert any("can do it alone" in n for n in marco["Coffee chat"].if_dropped)
    assert any("No backup named for Felix, Isaac, Nadia" in n for n in marco["Presentation"].if_dropped)


def test_fixed_order_is_respected():
    data = json.loads(REQUEST.read_text())
    marco = next(c for c in data["candidates"] if c["name"] == "Victor Hale")
    marco["fixed_order"] = True
    data["candidates"] = [marco]
    settings, free, cands = sch.load_request(data)
    placed = sch.schedule(settings, free, cands)[0].placed
    order = [r["name"] for r in marco["rounds"]]
    got = [p.round.name for p in placed]
    assert got == [n for n in order if n in got]


def test_unknown_interviewer_is_a_clear_error():
    data = json.loads(REQUEST.read_text())
    data["candidates"][0]["rounds"][0]["interviewers"] = ["Nobody"]
    with pytest.raises(ValueError, match="Nobody"):
        sch.load_request(data)


def test_outputs(tmp_path, solved):
    assert sch.main([str(REQUEST), "--out", str(tmp_path)]) == 0
    files = sorted(p.name for p in tmp_path.iterdir())
    assert "schedule.md" in files and "victor-hale-itinerary.md" in files and "aisha-bello.ics" in files
    assert "aisha-bello-itinerary.md" not in files  # remote screens don't get travel itineraries
    ics = (tmp_path / "victor-hale.ics").read_bytes().decode()
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert ics.count("BEGIN:VEVENT") == 4
    email = (tmp_path / "clara-novak-itinerary.md").read_text()
    assert "resolve the flagged rounds" in email  # unresolved flag blocks a clean send
    assert "shoes-off office" in (tmp_path / "victor-hale-itinerary.md").read_text()


def test_remote_loop_over_several_days_shows_each_date():
    data = {"hq_timezone": "America/Los_Angeles",
            "interviewers": {"A": {"free": [{"start": "2026-11-17T09:00", "end": "2026-11-17T10:00"}]},
                             "B": {"free": [{"start": "2026-11-19T09:00", "end": "2026-11-19T10:00"}]}},
            "candidates": [{"name": "R", "type": "remote", "timezone": "America/New_York",
                            "availability": [{"start": "2026-11-17T08:00", "end": "2026-11-19T18:00"}],
                            "rounds": [{"name": "One", "minutes": 45, "interviewers": ["A"]},
                                       {"name": "Two", "minutes": 45, "interviewers": ["B"]}]}]}
    settings, free, cands = sch.load_request(data)
    md = sch.summary_markdown(sch.schedule(settings, free, cands), settings)
    assert "**Tuesday, November 17**" in md and "**Thursday, November 19**" in md


def test_finds_a_full_onsite_on_a_later_day_quickly():
    """Eight one-person rounds; only the third day fits them all."""
    import time as _t
    people = [f"P{i}" for i in range(8)]
    interviewers = {}
    for i, p in enumerate(people):
        blocks = [{"start": "2026-11-18T09:00", "end": "2026-11-18T17:00"}]
        if i < 7:  # P7 is only free on the 18th, P0..P6 are free all three days...
            blocks = [{"start": f"2026-11-{d}T09:00", "end": f"2026-11-{d}T17:00"} for d in (16, 17, 18)]
        interviewers[p] = {"free": blocks}
    data = {"hq_timezone": "America/Los_Angeles", "interviewers": interviewers,
            "candidates": [{"name": "C", "type": "onsite",
                            "availability": [{"start": f"2026-11-{d}T09:00", "end": f"2026-11-{d}T17:00"}
                                             for d in (16, 17, 18)],
                            "rounds": [{"name": f"R{i}", "minutes": 45, "interviewers": [p]}
                                       for i, p in enumerate(people)]}]}
    settings, free, cands = sch.load_request(data)
    t0 = _t.time()
    (res,) = sch.schedule(settings, free, cands)
    assert _t.time() - t0 < 10
    assert len(res.placed) == 8
    assert {p.slot.start.astimezone(PT).day for p in res.placed} == {18}


def test_video_call_suggestion_is_on_a_weekday_in_office_hours():
    data = {"hq_timezone": "America/Los_Angeles",
            "interviewers": {"H": {"free": [{"start": "2026-11-21T00:00", "end": "2026-11-23T23:00"}]}},
            "candidates": [{"name": "C", "type": "onsite",
                            "availability": [{"start": "2026-11-20T09:00", "end": "2026-11-20T17:00"}],
                            "rounds": [{"name": "GM", "minutes": 45, "interviewers": ["H"]}]}]}
    settings, free, cands = sch.load_request(data)
    (res,) = sch.schedule(settings, free, cands)
    (_, why), = res.missing
    assert "Mon Nov 23, 9 AM–9:45 AM PST" in why  # not Saturday at midnight


def test_no_availability_is_a_clear_error():
    data = json.loads(REQUEST.read_text())
    data["candidates"][0]["availability"] = []
    with pytest.raises(ValueError, match="availability"):
        sch.load_request(data)


def test_calendar_lines_are_folded():
    long = sch.fold("DESCRIPTION:" + "x" * 200)
    assert all(len(part.encode()) <= 75 for part in long.split("\r\n"))
