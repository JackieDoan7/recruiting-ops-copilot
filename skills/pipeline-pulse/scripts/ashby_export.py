#!/usr/bin/env python3
"""Export active Ashby applications to the CSV format pipeline_pulse.py reads.

Read-only: it calls list endpoints only and never writes to Ashby.

    export ASHBY_API_KEY=...        # an API key with Candidates "read" permission
    python ashby_export.py -o pipeline.csv
    python pipeline_pulse.py pipeline.csv

Inside Claude, prefer Ashby's official MCP connector (each person signs in with
their own permissions). This script is the fallback for scheduled jobs.

Notes on the mapping:
  * last_activity uses the application's `updatedAt`, which moves whenever the
    application changes. It is a good proxy for "someone touched this".
  * feedback_count comes from applicationFeedback.list and counts feedback from
    every round, not just the latest one.
  * owner is the hiring-team member with the Recruiter role, if any.

Limits of this export (so the digest is read correctly):
  * It doesn't include upcoming interview times, so a candidate who is booked
    but untouched for 72 hours shows as "stale". Add a next_interview column
    (or use the Ashby connector, which can read schedules) to quiet those.
  * Because feedback_count is all-time, "no scorecards after the onsite" only
    fires reliably when interview_completed_at and per-round feedback come
    from the connector or a CSV export of the onsite stage.

Standard library only.
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import sys
import urllib.request
from pathlib import Path

API = "https://api.ashbyhq.com"
FIELDS = ["application_id", "candidate", "email", "role", "stage", "last_activity",
          "feedback_count", "owner", "status"]


class Ashby:
    def __init__(self, api_key: str, opener=urllib.request.urlopen):
        token = base64.b64encode(f"{api_key}:".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
            "Accept": "application/json; version=1",
        }
        self.opener = opener

    def call(self, endpoint: str, body: dict) -> dict:
        req = urllib.request.Request(f"{API}/{endpoint}", data=json.dumps(body).encode(),
                                     headers=self.headers, method="POST")
        with self.opener(req, timeout=30) as resp:
            data = json.loads(resp.read())
        if not data.get("success", False):
            raise RuntimeError(f"Ashby {endpoint} failed: {data.get('errors') or data}")
        return data

    def list_all(self, endpoint: str, body: dict) -> list[dict]:
        results, cursor = [], None
        while True:
            page = self.call(endpoint, {**body, **({"cursor": cursor} if cursor else {}), "limit": 100})
            results.extend(page.get("results", []))
            cursor = page.get("nextCursor")
            if not page.get("moreDataAvailable") or not cursor:
                return results


def recruiter_of(app: dict) -> str:
    for member in app.get("hiringTeam") or []:
        if "recruiter" in (member.get("role") or "").lower():
            return f"{member.get('firstName', '')} {member.get('lastName', '')}".strip()
    return ""


def to_row(app: dict, feedback_count: int) -> dict:
    cand = app.get("candidate") or {}
    email = cand.get("primaryEmailAddress") or {}
    return {
        "application_id": app.get("id", ""),
        "candidate": cand.get("name", ""),
        "email": email.get("value", "") if isinstance(email, dict) else str(email),
        "role": (app.get("job") or {}).get("title", ""),
        "stage": (app.get("currentInterviewStage") or {}).get("title", ""),
        "last_activity": app.get("updatedAt", ""),
        "feedback_count": feedback_count,
        "owner": recruiter_of(app),
        "status": app.get("status", ""),
    }


def export(client: Ashby, job_id: str | None = None) -> list[dict]:
    body = {"status": "Active"}
    if job_id:
        body["jobId"] = job_id
    rows = []
    for app in client.list_all("application.list", body):
        feedback = client.list_all("applicationFeedback.list", {"applicationId": app["id"]})
        rows.append(to_row(app, len(feedback)))
    return rows


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Export active Ashby applications for Pipeline Pulse.")
    p.add_argument("-o", "--output", type=Path, default=Path("pipeline.csv"))
    p.add_argument("--job-id", help="Only this job (Ashby job UUID)")
    args = p.parse_args(argv)
    key = os.environ.get("ASHBY_API_KEY")
    if not key:
        print("Set ASHBY_API_KEY first (Ashby Admin > API Keys, Candidates read permission).", file=sys.stderr)
        return 2
    rows = export(Ashby(key), args.job_id)
    with args.output.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} applications to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
