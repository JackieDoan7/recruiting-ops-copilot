import json
import tomllib
from datetime import date

import backtest
import check_brief
import gather_sources
import lint_rubric
import radar
import score
import sources
from conftest import SKILLS

TR = SKILLS / "talent-research"
RUBRIC = tomllib.loads((TR / "rubrics" / "ml-data-engineer.toml").read_text())


# --------------------------------------------------------------------------- rubric


def test_example_rubric_passes():
    assert lint_rubric.lint(RUBRIC) == ([], [])


def test_rubric_catches_protected_traits_and_proxies():
    bad = {"criteria": [
        {"id": "a", "weight": 1, "strong": "Young, energetic engineer who ships quickly every week."},
        {"id": "b", "weight": 1, "strong": "Degree from a top-tier university, plus great culture fit."},
        {"id": "c", "weight": 1, "strong": "Debugs black-box models and fills gaps in noisy datasets."},
    ]}
    errors, _ = lint_rubric.lint(bad)
    text = " ".join(errors)
    assert "'a' mentions age" in text
    assert "'b' uses school prestige" in text and "'b' uses culture fit" in text
    assert "'c'" not in text  # "black-box" and "gaps in datasets" are about the work


def test_justified_proxy_is_a_warning_not_an_error():
    rubric = {"criteria": RUBRIC["criteria"] + [
        {"id": "deg", "weight": 1, "strong": "Graduated from an accredited program in a required field.",
         "name": "class of 2026 rotation", "justification": "New-grad rotation program with a fixed start date"}]}
    errors, warnings = lint_rubric.lint(rubric)
    assert not errors and "graduation year" in warnings[0]


# --------------------------------------------------------------------------- scoring


def test_scoring_groups_and_evidence_rules():
    rows = {r["name"]: r for r in score.rank(json.loads((TR / "examples" / "ratings.json").read_text()), RUBRIC)}
    assert rows["Applicant A"]["group"] == "Review first"
    assert rows["Applicant B"]["group"] == "Review"
    assert rows["Applicant C"]["group"] == "Human check"
    d = rows["Applicant D"]
    assert d["group"] == "Review"  # too little information never pushes someone down
    assert any("no evidence" in p for p in d["problems"])  # "strong" without evidence is not counted


def test_nobody_is_labeled_rejected():
    md = score.markdown(score.rank(json.loads((TR / "examples" / "ratings.json").read_text()), RUBRIC), "Role")
    assert "reject" not in md.lower().replace("nobody is rejected", "")


def test_backtest_finds_misses_and_reports_rates():
    scored = score.rank(json.loads((TR / "examples" / "past_ratings.json").read_text()), RUBRIC)
    result = backtest.backtest(scored, backtest.load_outcomes(TR / "examples" / "past_outcomes.csv"))
    assert result["n"] == 24
    assert result["agreement"] == 0.88
    assert [m["id"] for m in result["missed"]] == ["past-011"]
    assert [o["id"] for o in result["over_ranked"]] == ["past-012"]
    assert {f["group"] for f in result["fairness"]} == {"A", "B"}
    assert all(f["small_sample"] for f in result["fairness"])


def test_four_fifths_flag():
    scored = [{"id": str(i), "name": str(i), "group": "Review" if i < 10 or i % 3 == 0 else "Human check",
               "gaps": [], "strongest": []} for i in range(40)]
    outcomes = {str(i): {"advanced": "no", "group": "A" if i < 20 else "B"} for i in range(40)}
    flags = {f["group"]: f["flag"] for f in backtest.backtest(scored, outcomes)["fairness"]}
    assert flags == {"A": False, "B": True}


# --------------------------------------------------------------------------- briefs


def test_example_brief_passes():
    errors, warnings = check_brief.check((TR / "examples" / "brief.md").read_text(),
                                         json.loads((TR / "examples" / "sources.json").read_text()))
    assert errors == [] and warnings == []


def test_brief_rejects_made_up_unconfirmed_and_personal_details():
    srcs = json.loads((TR / "examples" / "sources.json").read_text())
    brief = (TR / "examples" / "brief.md").read_text()
    made_up = brief.replace("https://papers.example.org/cheap-captions", "https://papers.example.org/does-not-exist")
    assert any("possible made-up source" in e for e in check_brief.check(made_up, srcs)[0])
    unconfirmed = brief.replace("https://papers.example.org/cheap-captions", "https://papers.example.org/noisy-clinics-asr")
    assert any("unconfirmed" in e for e in check_brief.check(unconfirmed, srcs)[0])
    personal = brief.replace("Finishing a PhD", "Recently married and finishing a PhD")
    assert any("family" in e for e in check_brief.check(personal, srcs)[0])
    no_link = brief.replace("([paper](https://papers.example.org/motion-aware-filtering))", "")
    assert any("**Now** states facts but cites no link" in e for e in check_brief.check(no_link, srcs)[0])


def test_research_topics_dont_trip_the_personal_filter():
    srcs = {"sources": [{"url": "https://arxiv.org/abs/1", "confidence": "verified"}]}
    brief = ("## X\n\n**Now:** Healthcare video models at Temple University [p](https://arxiv.org/abs/1).\n\n"
             "**Best known for:** Older baselines for aging-in-place video [p](https://arxiv.org/abs/1).\n\n"
             "**Why it connects:** Video data.\n\n**Suggested opener:** \"Hi.\"\n\n**Confidence:** verified")
    assert check_brief.check(brief, srcs)[0] == []


def test_brief_length_limit():
    srcs = {"sources": [{"url": "https://arxiv.org/abs/1", "confidence": "verified"}]}
    long = "One. Two. Three."
    brief = (f"## X\n\n**Now:** {long} [p](https://arxiv.org/abs/1)\n\n**Best known for:** {long} "
             f"[p](https://arxiv.org/abs/1)\n\n**Why it connects:** Fine.\n\n**Suggested opener:** \"Hi.\"\n\n"
             "**Confidence:** verified")
    assert any("sentences" in e for e in check_brief.check(brief, srcs)[0])


# --------------------------------------------------------------------------- sources


def test_name_matching():
    assert sources.same_name("Jane Q. Doe", "Jane Doe")
    assert sources.same_name("J. Doe", "Jane Doe")
    assert not sources.same_name("Jane Doe", "Jane Smith")
    assert not sources.same_name("John Doe", "Jane Doe")


def test_arxiv_affiliation_sets_confidence(fake_http):
    got = sources.arxiv_papers("Jane Doe", "Example University", fake_http({"export.arxiv.org": "arxiv_author.xml"}))
    by_url = {s.url: s for s in got}
    assert by_url["https://arxiv.org/abs/2699.04211"].confidence == "likely"
    assert by_url["https://arxiv.org/abs/2699.00117"].confidence == "unconfirmed"
    assert len(got) == 2  # "John Smith" excluded


def test_semantic_scholar_never_guesses_between_namesakes(fake_http):
    http = fake_http({"author/search": "s2_search.json", "/papers": "s2_papers.json"})
    found, note = sources.s2_sources("Jane Doe", "", http)
    assert found == [] and "2 Semantic Scholar authors share this name" in note
    found, note = sources.s2_sources("Jane Doe", "Example University", http)
    assert "111" in note and found[0].kind == "profile"
    assert {s.url for s in found[1:]} >= {"https://arxiv.org/abs/2699.09981", "https://arxiv.org/abs/2699.04211"}


def test_gather_merges_and_skips_social(fake_http):
    http = fake_http({"api.github.com": "github_repos.json", "author/search": "s2_search.json",
                      "/papers": "s2_papers.json", "export.arxiv.org": "arxiv_author.xml"})
    out = gather_sources.gather("Jane Doe", "Example University", "jane-doe-example",
                                ["https://jane-doe-example.dev", "https://instagram.com/jane-doe-example"], http)
    urls = [s["url"] for s in out["sources"]]
    assert "https://instagram.com/jane-doe-example" not in urls
    assert any("social media" in n for n in out["notes"])
    assert "https://github.com/jane-doe-example/pytorch" not in urls  # forks aren't their work
    assert urls.count("https://arxiv.org/abs/2699.04211") == 1  # same paper from two sources, kept once
    assert out["sources"][0]["confidence"] == "verified"


def test_gather_survives_a_failing_source(fake_http):
    def flaky(url, headers=None):
        if "github" in url:
            raise OSError("rate limited")
        return fake_http({"author/search": "s2_search.json", "/papers": "s2_papers.json",
                          "export.arxiv.org": "arxiv_author.xml"})(url)
    out = gather_sources.gather("Jane Doe", "Example University", "jane-doe-example", [], flaky)
    assert any("GitHub lookup failed" in n for n in out["notes"]) and out["sources"]


def test_radar_ranks_first_authors_and_skips_known_people(fake_http):
    http = fake_http({"export.arxiv.org": "arxiv_topics.xml"})
    people = radar.scan(["video dataset"], 30, date(2026, 11, 9), {sources.norm("Maya Okonkwo")}, http)
    names = [p["name"] for p in people]
    assert names[0] == "Ana Ruiz"  # first author on two recent papers
    assert "Maya Okonkwo" not in names  # already in the ATS
    assert "Old Author" not in names  # outside the 30-day window
    md = radar.markdown(people, ["video dataset"], 30, date(2026, 11, 9), 10)
    assert "https://arxiv.org/abs/2699.20010" in md


# --------------------------------------------------------------------------- edge cases from review


def test_missing_information_never_lowers_the_group():
    crit = RUBRIC["criteria"]
    strong_where_known = {"ratings": {c["id"]: ({"rating": "strong", "evidence": [{"text": "x"}]}
                                                if i < 3 else {"rating": "unclear"}) for i, c in enumerate(crit)}}
    r = score.score_candidate(strong_where_known, crit, RUBRIC["tiers"])
    assert r["group"] == "Review first" and r["coverage"] < 1


def test_affiliation_must_match_whole_words():
    assert sources.affiliation_matches("MIT", "MIT CSAIL")
    assert not sources.affiliation_matches("MIT", "Smith College")
    assert not sources.affiliation_matches("MIT", "transmitted signals")


def test_social_media_check_uses_the_hostname():
    assert sources.hostname_is("https://x.com/someone", gather_sources.BLOCKED_DOMAINS)
    assert not sources.hostname_is("https://www.dropbox.com/s/cv.pdf", gather_sources.BLOCKED_DOMAINS)


def test_brief_filter_catches_more_and_flags_less():
    srcs = {"sources": [{"url": "https://papers.example.org/p", "confidence": "verified"}]}

    def errs(now_text):
        b = (f"## X\n\n**Now:** {now_text} [p](https://papers.example.org/p).\n\n**Best known for:** A repo "
             "[p](https://papers.example.org/p).\n\n**Why it connects:** Video.\n\n**Suggested opener:** \"Hi.\"\n\n"
             "**Confidence:** verified")
        return check_brief.check(b, srcs)[0]

    assert any("compensation" in e for e in errs("She earns $200k at a lab"))
    assert any("family" in e for e in errs("A mother of two working on video"))
    assert any("age" in e for e in errs("Graduated in 2019 and works on video"))
    assert errs("Works on equity in ML and a Reddit-sourced dataset with Kenneth Church") == []


def test_rubric_named_schools_and_native_level_are_caught():
    bad = {"criteria": [
        {"id": "a", "weight": 1, "strong": "PhD from Stanford, MIT or CMU in machine learning."},
        {"id": "b", "weight": 1, "strong": "Native-level English and strong written updates."},
        {"id": "c", "weight": 1, "strong": "Writes a clear white paper and debugs a black box model."},
    ]}
    text = " ".join(lint_rubric.lint(bad)[0])
    assert "'a' uses named elite schools" in text and "'b' uses native speaker" in text and "'c'" not in text
