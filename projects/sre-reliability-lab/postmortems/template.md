# Postmortem: <short title>

**Date:** YYYY-MM-DD  **Authors:** <names>  **Status:** draft | reviewed
**Severity:** SEV-n  **Duration:** <start> to <end> (<total>)
**Error budget consumed:** <x>% of the 30-day budget  (from `slo:error_budget_remaining:ratio`)

## Summary
Two or three sentences a non-engineer could follow: what broke, who was affected, how it ended.

## Impact
Numbers from metrics, not impressions: affected requests, error ratio, duration, users or revenue if known.

## Timeline (UTC)
| Time | Event |
|---|---|
| hh:mm | First symptom / change deployed |
| hh:mm | Alert fired (name) |
| hh:mm | Acknowledged |
| hh:mm | Mitigation applied |
| hh:mm | Resolved |

## Root cause and contributing factors
Describe systems and decisions, not people. Keep asking "why" until you reach something that can be fixed.

## Detection
Time between the start of impact and the first page. Would a different burn-rate window have been faster
(`python -m slogen simulate`)? Were any alerts noisy or missing?

## What went well / what went poorly / where we got lucky

## Action items
| Action | Type (prevent / detect / mitigate) | Owner | Due |
|---|---|---|---|
