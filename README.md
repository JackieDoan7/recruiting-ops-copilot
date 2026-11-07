# Recruiting Ops Copilot

Two tools I'd put to work in my first month in a Recruiting Coordinator & Office Manager role: one for recruiting ops, one for keeping the office running. The onsite project's bonus question asked what I'd build in Claude to speed up both, and said there was no need to actually build it. I wanted to, so here it is: working code, tested, with sample output for everything.

**Try them:** [Candidate Desk](https://claude.ai/artifact/7eqaZjqTktKfX7KsqeYgPK) · [Supply Autopilot](https://claude.ai/artifact/VS48KRR92gnbPaUpdc4qsm) (interactive demos on made-up data)

**Jackie Doan** · November 2026

## The idea

The belief I led with in my onsite project: **top candidates should feel individually known.** When a handful of companies are competing for the same researchers, a note that names someone's actual work, an onsite day where they only have to think about the interviews, and a fast, clear answer are what set a team apart.

The catch is time. Personal at scale only works if everything behind the scenes runs itself, so each tool here takes a piece of that hidden work off the coordinator's plate. They all follow the same rules:

- **AI prepares; a person decides, sends, or buys.** Nothing here rejects a candidate, sends an email, changes Ashby, or checks out a cart on its own.
- **Read-only by default.** Writing a note to Ashby or sending an invite is always someone's click.
- **Professional work only.** Candidate research covers papers, code and talks. Never personal social media, family, health, age, religion or politics, and a checker enforces it.
- **Compensation stays private.** It never appears in a digest.

## What's here

| Tool | What it does | Where it comes from in my onsite project | Skills inside |
| --- | --- | --- | --- |
| **Candidate Desk** | A coordinator's morning in three steps: see what's slipping in Ashby, write to candidates like someone who knows their work, and build their onsite with a backup for every round | Appendices A and B, my onsite prep and same-day reschedule notes, and "have AI research top candidates' recent work" | [Pipeline Pulse](skills/pipeline-pulse), [Talent Research](skills/talent-research), [Onsite Scheduler](skills/onsite-scheduler) |
| **Supply Autopilot** | A Google Sheet that scales stock with headcount and events, builds the Amazon cart in one click, and tracks office fixes | Section 5: my Google Form + Sheets supply tracker, one step further | [Supply Autopilot](skills/supply-autopilot) |

Each step is a [Claude skill](https://support.claude.com/en/articles/12512176-what-are-skills): instructions Claude follows, plus small, tested scripts for the parts that have to be exact (dates, time zones, math, links). Candidate Desk is three skills, so each step also works on its own, like running just the morning pipeline check.

### How this fits with Ashby

Ashby already does a lot of this, and I'd start there: auto-scheduling for complex panels, interviewer pools and limits, its AI assistant for pipeline questions, candidate summaries from what's already in Ashby, and personalized sourcing outreach. These tools cover the gaps I saw:

- **Our own timelines.** A morning check against the promises we make candidates: an update within 72 hours, scorecards within 24, a debrief within 48.
- **Backup plans.** A named backup for every round, and a quick re-plan when an interviewer drops out on the day.
- **Research outside Ashby.** A candidate's actual papers and code, checked to be the same person, so outreach to researchers is specific.

They read from Ashby through its official MCP connector (or a read-only export), and nothing changes in Ashby without a person.

---

## 1. Candidate Desk

The three steps of a coordinator's morning, in the order the demo walks through them.

### Step 1: What's slipping ([Pipeline Pulse](skills/pipeline-pulse))

A read-only morning pass over the pipeline that applies the team's promises: no candidate goes 72 hours without an update, scorecards within 24 hours, availability booked within two days. It catches strong candidates who've gone quiet, finished onsites with no scorecards, availability sitting unbooked, duplicate profiles that disagree, and "not a fit" candidates still marked active.

<details open>
<summary>Sample output (made-up pipeline)</summary>

> **11 active applications checked. 8 items across 7 candidates: 4 need a decision and 4 are quick fixes.**
>
> | # | Candidate | Stage | What's wrong | Next step |
> | --- | --- | --- | --- | --- |
> | 1 | Maya Okonkwo (ML Engineer) | Technical Interview | Strong signal in the notes, but no activity for 24 days. | Ask the owner what's holding it up today. Strong candidates usually have other offers. |
> | 2 | Sam Rivera (Data Engineer) | On Site | No scorecards 17 days after the interview. | Find out what's blocking feedback, then book the debrief. The candidate is waiting on us. |
> | 3 | Nora Lind (Reliability Engineer) | Final Interview | Feedback says pass, but the application is still active. | Confirm with the owner, archive, and send a warm, personal close-out. |
> | 4 | Ana Lima (FDE) | Technical Interview | Two records with the same email disagree on the stage. | Confirm which is current, merge, keep all feedback. |

Full output: [`examples/digest.md`](skills/pipeline-pulse/examples/digest.md)
</details>

In Ashby itself, this check could likely be built as one of its Custom Agents; this is the spec I'd hand it. Pulse keeps the rules in one config file, so the team can see exactly what "stale" means and change it.

### Step 2: Write to them ([Talent Research](skills/talent-research))

- **Candidate briefs.** Four sentences: what someone is working on now, what they're best known for, why it connects to the team's work, and a suggested first line for the email. Sources come from arXiv, Semantic Scholar and GitHub, each labeled *verified* (linked from their application), *likely* (name and school or employer match) or *unconfirmed* (name only). A checker blocks any brief that cites a link it didn't actually find or leans on an unconfirmed source. Common names are a real risk with researchers, so "I couldn't confirm this is the same person" is an allowed answer.
- **Reading order for applicants.** My original idea was "which applicants' work matches the company best?" I built it as a reading order, not a filter: the hiring manager writes a short rubric, every rating needs evidence, and applicants land in "Review first," "Review" or "Human check." Missing information never lowers anyone's group. Before anyone relies on a rubric, a checker screens it for biased criteria and a backtest compares it with decisions the team already made. ([sample](skills/talent-research/examples/reading-order.md), [backtest](skills/talent-research/examples/backtest.md))
- **Research radar.** Since this role grows into sourcing: people with recent arXiv work in the team's area (video datasets, data curation, multimodal pretraining data) who aren't already in Ashby, with the paper to open a personal note with.

<details open>
<summary>Sample brief (made-up candidate)</summary>

> **Now:** Finishing a PhD at Example University; their latest paper scores 40M web video clips for motion quality before captioning and shows the filtered set trains a better retrieval model ([paper](https://papers.example.org/motion-aware-filtering)).
>
> **Best known for:** fastclip, a GPU video-decoding library with about 1,800 GitHub stars, and an audit of synthetic video captions that's been cited 41 times.
>
> **Why it connects:** Deciding which video is worth training on is the core of our data work, and they've measured it end to end.
>
> **Suggested opener:** "Your motion-quality filter paper is very close to problems our team works on every day, and I'd love to show you what we're building."
</details>

In California, tools that help make hiring decisions count as "automated-decision systems" under rules in effect since October 1, 2025. So the reading-order tool keeps its rubric, ratings and backtest as records, and I'd get a sign-off from whoever handles legal before using it on live applicants. The optional selection-rate check in the backtest uses voluntary self-ID data, so People Ops or legal would run that step on data they already hold and share only the totals.

### Step 3: Build the onsite ([Onsite Scheduler](skills/onsite-scheduler))

Give it interviewer calendars, candidate availability and the rounds each candidate needs. It:

- **books the hardest schedules first** and has each one avoid slots the others still need. In the sample, it puts a London screen on Thursday so a Wednesday onsite keeps its interviewer.
- **keeps onsites to one day,** back to back.
- **keeps the hard rounds when not everything fits.** A three-person panel stays onsite; a 1:1 becomes a video call at a specific time that person is free.
- **decides the backup plan up front** for every interviewer in every round.
- **keeps everything in office time (PT)** and drafts the itinerary email and calendar invites. Invites carry the time zone, so each candidate's calendar shows their own local time without anyone converting by hand.

**On time zones:** Scheduling across time zones came up a few times in my interviews. The easiest approach I've found is to use one time zone for everything on our side, here Pacific, the office's time. The schedule, the interviewers' calendars and the debrief all use the same times, and nobody has to do time zone math in their head, which is where mistakes happen. Then I let the software do the converting: the calendar invite carries the time zone, so Google Calendar and Ashby show each candidate the time in their own zone. The scheduler still uses the candidate's time zone to read their availability, so a London screen lands during London's workday, but it never shows up on our side.

<details open>
<summary>Sample output (made-up people and calendars)</summary>

> **Clara Novak (Data Engineer), Friday, November 20**
>
> | Round | PST | With |
> | --- | --- | --- |
> | Coffee chat | 9:30 AM–10 AM | Kai, Luis |
> | Presentation | 10 AM–11 AM | Gwen, Hana, Nadia |
> | Tech deep dive | 11 AM–12 PM | Gwen |
>
> **Flag before sending:** GM interview couldn't be placed. Hana's only open time goes to the Presentation, which is harder to move to another day. Next move: offer a video call on Mon Nov 23, 10 AM–10:45 AM PST, when Hana is free.
>
> **Backup plan:** Coffee chat: if Kai drops, Luis can do it alone. Presentation: no backup named for Gwen, Hana, Nadia. Pick one before sending.

Full output: [`schedule.md`](skills/onsite-scheduler/examples/output/schedule.md) · [itinerary email](skills/onsite-scheduler/examples/output/victor-hale-itinerary.md) · [calendar file](skills/onsite-scheduler/examples/output/victor-hale.ics)
</details>

My templates for onsite prep, same-day reschedules and warm rejections are in [`references/templates.md`](skills/onsite-scheduler/references/templates.md).

## 2. Supply Autopilot

My clinic system was a Google Form feeding a Google Sheet, so I could see what was low without opening every drawer. This adds the step I always wanted: **the sheet builds the cart, and I just review and buy.**

- Targets scale the way each item is actually used: snacks with everyone each week, teammates' own items one per person (so a new hire gets theirs automatically), guest items with that week's onsite candidates and visitors.
- Orders round up to full packs and only trigger at a reorder point. Anything already ordered but not yet delivered counts, so nothing gets bought twice.
- One link adds every Amazon item to the cart, using Amazon's documented [Add to Cart form](https://webservices.amazon.com/paapi5/documentation/add-to-cart-form.html).
- Other vendors get a ready-to-paste list for Claude in Chrome, which fills the cart and stops. (Claude in Chrome [doesn't make purchases](https://support.claude.com/en/articles/12902446-claude-for-chrome-permissions-guide), which is exactly the line I want.)
- A Vendors tab keeps a backup for each category, so a catering no-show is one phone call.
- An **Office fixes** tab for the things that aren't a reorder: what's wrong, the fix, who owns it, and the routine that keeps it fixed. The worked example is a shoes-off entryway: wall racks instead of floor piles, a washable pair of their own for every teammate (after a two-week trial of a few kinds, so we buy the one people actually like), sized guest pairs with a hamper, and a two-minute end-of-day sweep ([playbook](skills/supply-autopilot/references/entryway.md)). Candidates hear about it in their itinerary email and get asked their shoe size, so a fresh pair is waiting.
- A Monday email with the list, the cart link and an estimated total.

Setup is pasting one file into Apps Script: [`apps-script/README.md`](skills/supply-autopilot/apps-script/README.md). [Sample order](skills/supply-autopilot/examples/order.md)

---

## Try it

Needs Python 3.11 or newer. The scripts use only the standard library; the tests need `pytest`, and Node 18+ for the Apps Script tests.

```bash
git clone https://github.com/JackieDoan7/recruiting-ops-copilot.git
cd recruiting-ops-copilot
make demo      # regenerates every sample output from the sample data, no keys needed
pip install pytest && make test
make package   # dist/<skill>.zip for each skill
```

**To use the skills in Claude:** upload the zips under Customize > Skills (Team and Enterprise owners can share them with the whole org). They work best with Ashby's official MCP connector turned on (an Ashby admin enables it under Opt-In Features), Google Calendar and Gmail connected, and Claude in Chrome for vendor carts.

## What I'd build next

- **Interviewer packet:** when someone reaches Onsite, assemble the brief, each interviewer's focus area and the backup plan into one page in Ashby.
- **First-day kit:** offer accepted → accounts, laptop, welcome email and a first-week calendar, from one checklist.
- **Office help desk in Slack:** Wi-Fi, guests, expenses, "who do I ask," with repeat questions turned into better docs.
- **Candidate experience pulse:** a two-question survey after every onsite, summarized monthly.

## How it was built

I built this with Claude as my pair programmer, which felt like the most honest answer to a question about AI as an accelerant. Standard-library Python plus one Google Apps Script file, tested on Python 3.11 to 3.13, with a CI check that the committed sample outputs match the code.

*All people, candidates, calendars and papers in this repo are made up.*
