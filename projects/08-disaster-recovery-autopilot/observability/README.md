# Observability: reuse project 04, do not rebuild it

Detection, alert routing and paging already live in [project 04](../../04-observability-slo). Project 08 adds only what
it needs on top:

| File | Merge into | Purpose |
|---|---|---|
| `alert-rules.yml` | 04's Prometheus rule files | `OrdersDataUnhealthy`, `BackupRestoreTestFailing`, `BackupRestoreTestStale` |
| `alertmanager-snippet.yml` | 04's `alertmanager.yml` | route alerts labelled `autoremediate="true"` to drpilot, with `continue: true` so humans are still paged |
| `prometheus-snippet.yml` | 04's `prometheus.yml` | scrape the orders service |

04's own alerts that drpilot has playbooks for (`TargetDown`, `CrashLooping` on `release-tracker`) are matched by the
playbooks in `../playbooks/` and need no new rules; `tests/test_config.py` checks that those alert names and labels still
exist in 04's rule files. Add `autoremediate: "true"` to them, or route them to drpilot by `alertname`, when you
decide to let automation act on them.
