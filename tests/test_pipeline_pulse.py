import io
import json
from datetime import datetime, timedelta, timezone

import ashby_export
import pipeline_pulse as pp
from conftest import SKILLS

EXAMPLES = SKILLS / "pipeline-pulse" / "examples"
NOW = datetime.fromisoformat("2026-11-09T09:00-08:00")


def run_example():
    cfg = pp.load_config(SKILLS / "pipeline-pulse" / "config.toml")
    apps = pp.to_applications(pp.load_rows(EXAMPLES / "pipeline.csv"), NOW)
    return apps, pp.run(apps, NOW, cfg)


def codes(flags):
    return {(f.candidate, f.code) for f in flags}


def test_example_flags_each_problem_once():
    _, flags = run_example()
    assert codes(flags) == {
        ("Maya Okonkwo", "strong_stalled"),
        ("Sam Rivera", "feedback_overdue_escalate"),
        ("Nora Lind", "passed_still_active"),
        ("Ana Lima", "duplicate_conflict"),
        ("Grace Huang", "availability_waiting"),
        ("Ivy Chen", "feedback_overdue"),
        ("Omar Haddad", "stale"),
        ("Omar Haddad", "comp_in_notes"),
    }


def test_strong_stalled_candidate_leads():
    _, flags = run_example()
    assert flags[0].candidate == "Maya Okonkwo" and flags[0].decision


def test_passed_tech_is_not_a_rejection():
    # "Passed tech" means the candidate cleared the round.
    _, flags = run_example()
    assert ("Maya Okonkwo", "passed_still_active") not in codes(flags)


def test_upcoming_interview_and_hired_are_quiet():
    _, flags = run_example()
    quiet = {"Leo Martins", "Ethan Park", "Ben Carter", "Zoe Patel"}
    assert not quiet & {f.candidate for f in flags}


def test_older_duplicate_gets_no_separate_nags():
    _, flags = run_example()
    ana = [f for f in flags if f.candidate == "Ana Lima"]
    assert [f.code for f in ana] == ["duplicate_conflict"]
    assert len(ana[0].rows) == 2


def test_compensation_never_appears_in_output():
    apps, flags = run_example()
    md = pp.to_markdown(flags, apps, NOW)
    assert "240" not in md and "$" not in md
    assert pp.redact("expects $240k base") == "expects [comp redacted] base"
    assert pp.redact("asking 180k") == "asking [comp redacted]"


def test_markdown_groups_decisions_and_fixes():
    apps, flags = run_example()
    md = pp.to_markdown(flags, apps, NOW)
    assert md.index("## Needs a decision") < md.index("## Quick fixes")
    assert "4 need a decision" in md and "4 are quick fixes" in md


def test_relative_dates_and_config_override(tmp_path):
    rows = [{"candidate": "A", "role": "R", "stage": "Recruiter Screen", "last_activity": "2 days ago",
             "owner": "Jo"}]
    apps = pp.to_applications(rows, NOW)
    assert apps[0].last_activity == NOW - timedelta(days=2)
    assert pp.run(apps, NOW, pp.load_config(None)) == []
    cfg_file = tmp_path / "c.toml"
    cfg_file.write_text("[sla]\nstale_hours = 24\n")
    assert [f.code for f in pp.run(apps, NOW, pp.load_config(cfg_file))] == ["stale"]


def test_cli_json(capsys):
    assert pp.main([str(EXAMPLES / "pipeline.csv"), "--now", "2026-11-09T09:00-08:00", "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data[0]["candidate"] == "Maya Okonkwo"


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_ashby_export_pages_and_maps_fields():
    pages = {
        ("application.list", None): {"success": True, "moreDataAvailable": True, "nextCursor": "c2", "results": [
            {"id": "a1", "status": "Active", "updatedAt": "2026-11-01T10:00:00Z",
             "candidate": {"name": "Maya Okonkwo", "primaryEmailAddress": {"value": "maya@example.com"}},
             "job": {"title": "ML Engineer"}, "currentInterviewStage": {"title": "On Site"},
             "hiringTeam": [{"firstName": "Jordan", "lastName": "Lee", "role": "Recruiter"}]}]},
        ("application.list", "c2"): {"success": True, "moreDataAvailable": False, "results": [
            {"id": "a2", "status": "Active", "candidate": {"name": "Ben"}, "job": {}, "hiringTeam": []}]},
        ("applicationFeedback.list", None): {"success": True, "moreDataAvailable": False, "results": [{}, {}]},
    }
    sent = []

    def opener(req, timeout=30):
        body = json.loads(req.data)
        sent.append((req.full_url, body, dict(req.header_items())))
        endpoint = req.full_url.rsplit("/", 1)[1]
        return FakeResponse(json.dumps(pages[(endpoint, body.get("cursor"))]).encode())

    rows = ashby_export.export(ashby_export.Ashby("secret", opener))
    assert [r["candidate"] for r in rows] == ["Maya Okonkwo", "Ben"]
    assert rows[0] == {"application_id": "a1", "candidate": "Maya Okonkwo", "email": "maya@example.com",
                       "role": "ML Engineer", "stage": "On Site", "last_activity": "2026-11-01T10:00:00Z",
                       "feedback_count": 2, "owner": "Jordan Lee", "status": "Active"}
    assert sent[0][2]["Authorization"].startswith("Basic ")
    assert all(url.startswith("https://api.ashbyhq.com/") for url, _, _ in sent)
    # The export must only ever call read endpoints.
    assert {url.rsplit("/", 1)[1] for url, _, _ in sent} <= {"application.list", "applicationFeedback.list"}


# --------------------------------------------------------------------------- edge cases from review


def flags_for(rows, cfg=None):
    apps = pp.to_applications(rows, NOW)
    return pp.run(apps, NOW, cfg or pp.load_config(None))


def row(**kw):
    base = {"candidate": "A", "role": "R", "stage": "Recruiter Screen", "last_activity": "5 days ago", "owner": "Jo"}
    return {**base, **kw}


def test_signals_match_whole_words_only():
    # "top" inside "Stopped" is not a strong signal.
    assert [f.code for f in flags_for([row(notes="Stopped responding")])] == ["stale"]


def test_notes_about_scheduling_are_not_a_rejection():
    got = [f.code for f in flags_for([row(notes="Declined the Tuesday slot, asked for Thursday")])]
    assert got == ["stale"]


def test_namesakes_with_different_emails_are_different_people():
    rows = [row(candidate="Wei Zhang", email="wei.z@a.example", last_activity="38 days ago"),
            row(candidate="Wei Zhang", email="zhang.wei@b.example", last_activity="1 day ago")]
    codes_ = [(f.code, f.rows) for f in flags_for(rows)]
    assert codes_ == [("stale", [2])]  # no merge suggestion; the old one still gets its nudge


def test_same_name_without_email_is_only_a_possible_duplicate():
    rows = [row(candidate="Wei Zhang", email="wei.z@a.example", last_activity="38 days ago"),
            row(candidate="Wei Zhang", last_activity="1 day ago")]
    got = {f.code for f in flags_for(rows)}
    assert got == {"possible_duplicate", "stale"}


def test_comp_detection_needs_a_comp_word_or_currency():
    assert not pp.mentions_comp("Trained a 7B base model on 300k clips")
    assert pp.mentions_comp("wants 1.2M in equity")
    assert pp.mentions_comp("salary 150000")
    assert pp.mentions_comp("Comp expectation $240k base")


def test_one_bad_date_skips_the_row_not_the_run():
    warnings = []
    apps = pp.to_applications([row(last_activity="last Tuesday"), row(candidate="B")], NOW, warnings)
    assert [a.candidate for a in apps] == ["B"] and "Row 2" in warnings[0]
