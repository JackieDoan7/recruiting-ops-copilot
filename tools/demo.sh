#!/usr/bin/env bash
# Regenerate every example output from the sample data. No network, no API keys.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== Pipeline Pulse"
python3 skills/pipeline-pulse/scripts/pipeline_pulse.py skills/pipeline-pulse/examples/pipeline.csv \
  --config skills/pipeline-pulse/config.toml --now 2026-11-09T09:00-08:00 \
  -o skills/pipeline-pulse/examples/digest.md

echo "== Onsite Scheduler"
python3 skills/onsite-scheduler/scripts/schedule.py skills/onsite-scheduler/examples/request.json \
  --out skills/onsite-scheduler/examples/output --stamp 2026-11-09T17:00:00Z > /dev/null

echo "== Talent Research"
TR=skills/talent-research
python3 $TR/scripts/lint_rubric.py $TR/rubrics/ml-data-engineer.toml
python3 $TR/scripts/score.py $TR/examples/ratings.json --rubric $TR/rubrics/ml-data-engineer.toml \
  -o $TR/examples/reading-order.md
python3 $TR/scripts/score.py $TR/examples/past_ratings.json --rubric $TR/rubrics/ml-data-engineer.toml \
  --format json -o $TR/examples/past_scored.json
python3 $TR/scripts/backtest.py $TR/examples/past_scored.json $TR/examples/past_outcomes.csv \
  > $TR/examples/backtest.md
python3 $TR/scripts/check_brief.py $TR/examples/brief.md --sources $TR/examples/sources.json

echo "== Supply Autopilot"
python3 skills/supply-autopilot/scripts/supply_order.py skills/supply-autopilot/examples/inventory.csv \
  --headcount 45 --guests 12 -o skills/supply-autopilot/examples/order.md

echo "Done. Outputs are in each skill's examples/ folder."
