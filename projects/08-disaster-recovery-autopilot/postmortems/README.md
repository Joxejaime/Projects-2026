# Postmortems

drpilot writes a postmortem **draft** here (or wherever `--postmortems` points) when an incident closes. A draft
contains only what was observed: the alert, every timeline event, each recovery step with its output, the verification
result, the facts restore scripts reported, and whether the declared RTO/RPO were met. Root cause, plain-language
impact and action-item owners are left as `TODO (human)`, because an automation that guesses a root cause produces
confident fiction.

## `drills/`

Drafts produced by `make drill`, which corrupts the demo service's data file on purpose and lets drpilot recover it.
They are committed **unedited**, as evidence of exactly what the tool generates; the TODO sections are left open on
purpose. They are drills, not incidents: nothing in this folder describes a real outage.

| Drill draft | Scenario | Automated recovery | RTO (target 2 min) | RPO (target 15 min) |
|---|---|---|---|---|
| [`20261026-060057-notesunhealthy-d6e0`](drills/20261026-060057-notesunhealthy-d6e0.md) | data file corrupted | succeeded on attempt 1, verified | 1.5 s, met | 1.1 s, met (2 notes written after the snapshot lost) |
| [`20261026-060100-notesunhealthy-1a0a`](drills/20261026-060100-notesunhealthy-1a0a.md) | data file **and** every snapshot corrupted | refused to restore garbage, gave up after 2 attempts, escalated | 0.6 s, met (the "human" fix is instant in a drill) | **missed**: no verified restore, all 7 notes lost |

The second drill is the more useful one. The snapshot was verified when it was taken and rotted afterwards, so a
"backup succeeded" log line would have been green the whole time. Its draft correctly suggests testing restores on a
schedule rather than snapshotting more often.
