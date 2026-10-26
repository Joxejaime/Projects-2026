# Postmortems

drpilot writes a postmortem **draft** here (or wherever `--postmortems` points) when an incident closes. A draft
contains only what was observed: the alert, every timeline event, each recovery step and the data checks with their
output, the facts the restore reported, and whether the declared RTO and RPO were met. Root cause, plain-language
impact and action-item owners are left as `TODO (human)`, because an automation that guesses a root cause produces
confident fiction.

## `drills/`

Drafts produced by `make drills`, which destroys a real (throwaway) PostgreSQL database three different ways and
lets drpilot recover it. They are committed **unedited**, as evidence of exactly what the tool generates; the TODO
sections are left open on purpose. They are drills, not incidents: nothing in this folder describes a real outage.

| Drill draft | Disaster | What drpilot did | RTO (target 5 min) | RPO (target 15 min) |
|---|---|---|---|---|
| [`…38be`](drills/20261026-123941-ordersdataunhealthy-38be.md) | the orders tables dropped | restored the newest snapshot, 3 healthy probes, data checks and a test write passed | 1.9 s, met | 1.5 s, met (2 later orders lost) |
| [`…4e5d`](drills/20261026-123947-ordersdataunhealthy-4e5d.md) | same, but the newest snapshot was taken from already-wrong data | restored it into a scratch database first, saw the order totals did not match their items, **skipped it**, restored the older one | 2.0 s, met | 3.0 s, met |
| [`…6859`](drills/20261026-123951-ordersdataunhealthy-6859.md) | same, and the only snapshot had rotted | checksum mismatch, refused to restore, gave up after 2 attempts, escalated; the drill then plays the human who rebuilds | 0.8 s, met (the "human" is instant) | **missed**: nothing verified, all 7 orders lost |

The second and third are the useful ones. A restore that "succeeds" with the wrong data, or a snapshot that rotted after
it was verified, is how real recoveries fail. The timings are from a tiny database on one machine: they show that the
mechanism works, not how long your restore will take. `recover.py restore-test` measures that on your data.
