# Disaster Recovery Autopilot

**When something breaks, try the recovery automatically, prove it worked, and write the postmortem draft.**
`drpilot` receives alerts (from Alertmanager, or from its own health-probe watcher), opens an incident, runs the
matching recovery playbook, and only calls the service recovered after consecutive healthy probes. When the incident
closes it writes a postmortem draft with the full timeline, every recovery step and its output, and whether the
declared RTO and RPO were met. It can also open the draft as a GitHub issue for review.

It does not pretend to know why things broke. Root cause, plain-language impact and action-item owners are left as
explicit `TODO (human)` sections, because an automated postmortem that guesses a root cause is confident fiction.

![System architecture](docs/schematics/01-architecture.svg)

<sub>Source: [`01-architecture.mmd`](docs/schematics/01-architecture.mmd) · [all schematics](docs/schematics/README.md) (architecture, incident lifecycle)</sub>

## What it demonstrates

| Area | Where |
|---|---|
| Alertmanager webhook receiver with bearer-token auth, body limits and idempotent handling of repeat notifications | `drpilot/server.py`, `drpilot/alertmanager.py` |
| Incident lifecycle: one incident per alert group, closed only when every alert resolved **and** no recovery is still running | `drpilot/engine.py` |
| Recovery playbooks as YAML: most-specific match wins, retries, commands without a shell, secrets only from the environment | `playbooks/`, `drpilot/playbooks.py` |
| Recovery is verified, not assumed: N consecutive healthy probes before a deadline | `drpilot/playbooks.py` (`verify`) |
| Disaster recovery for real data: checksummed data file, verified snapshots, restore that skips corrupt snapshots and reports the recovery point achieved | `demo/notes.py`, `demo/backup.py` |
| RTO / RPO declared per playbook and checked in every postmortem | `playbooks/notes-restore.yaml`, `drpilot/render.py` |
| Postmortem drafts: timeline, key times, step output, objective checks, suggested follow-ups derived from what happened | `drpilot/render.py`, `postmortems/` |
| Escalation is part of the design: no playbook or failed automation pages a human and is recorded, never silent | `drpilot/engine.py`, `observability/alertmanager.yml` |
| Works without Prometheus: a probe watcher turns `/healthz` into the same alert payloads | `drpilot/watch.py` |
| Drills that break the service on purpose, including the case where automation must refuse to recover | `drpilot/drill.py`, `make drill`, `make drill-fail` |
| Runbook tied to the alert | `docs/runbooks/notes-unhealthy.md` |

## Quick start

Python 3.11+ and PyYAML. Nothing else: no Docker, no cloud account.

```bash
pip install -r requirements.txt
make test         # 35 tests, about 7 s, including both drills end to end
make check        # validate every playbook
make drill        # corrupt the demo service's data, watch drpilot restore it, read postmortems/drills/<id>.md
make drill-fail   # corrupt the data AND every snapshot: drpilot must refuse, escalate, and say so in the draft
make replay       # replay a sample Alertmanager incident with no playbook (the escalation path)
```

### What a drill prints

```
$ make drill
scenario corrupt-data: incident 20261026-060057-notesunhealthy-d6e0, recovery succeeded, postmortem postmortems/drills/20261026-060057-notesunhealthy-d6e0.md
data: 5 notes restored, 2 written after the snapshot were lost (expected: RPO > 0)
RTO (impact start to service restored): target 2m 00s, observed 1.5s -> met
RPO (age of the data restored): target 15m 00s, observed 1.1s -> met
DRILL PASSED

$ make drill-fail
scenario corrupt-backups: incident 20261026-060100-notesunhealthy-1a0a, recovery failed, postmortem postmortems/drills/20261026-060100-notesunhealthy-1a0a.md
data: automation refused to restore a corrupt snapshot and escalated; 7 notes lost, rebuilt by hand
RTO (impact start to service restored): target 2m 00s, observed 0.6s -> met
RPO (age of the data restored): target 15m 00s, observed unknown (no restore reported it) -> MISSED
DRILL PASSED
```

The second drill "passes" because the tool did the right thing: it would not restore a snapshot that failed its
checksum, it escalated after two attempts, and the draft names the failing step and its error. Both drafts are
committed unedited in [`postmortems/drills/`](postmortems/README.md).

## Running it for real

```bash
export DRPILOT_TOKEN=$(openssl rand -hex 16)          # Alertmanager sends this as a bearer token
python -m drpilot serve --host 0.0.0.0 --port 9095 --state /var/lib/drpilot --postmortems /var/lib/drpilot/postmortems
```

Point Alertmanager at it with [`observability/alertmanager.yml`](observability/alertmanager.yml): pages go to drpilot
**and** to people (`continue: true`), and `send_resolved: true` is required because resolution is what closes the
incident. Alert rules with the labels the playbooks match on are in
[`observability/alert-rules.yml`](observability/alert-rules.yml). Without Prometheus, run the watcher instead:

```bash
python -m drpilot watch http://notes:8090/healthz --alertname NotesUnhealthy --label service=notes \
  --label severity=page --responder http://drpilot:9095/alerts
```

To have drafts opened as GitHub issues labelled `postmortem` and `draft`, set `DRPILOT_GITHUB_REPO=owner/name` and
`DRPILOT_GITHUB_TOKEN` (a fine-grained token with Issues: write on that repository only). Publishing is best effort:
if it fails, the timeline says so and the file on disk is still written.

### Writing a playbook

```yaml
name: notes-restore-from-snapshot
match: {alertname: NotesUnhealthy, service: notes}   # all must equal the alert's labels; most keys wins
max_attempts: 2
objectives: {rto_seconds: 120, rpo_seconds: 900}
steps:
  - name: Restore newest verified snapshot
    run: ["{python}", "{playbook_dir}/../demo/backup.py", "restore", "--data", "{env.NOTES_DATA}", "--dir", "{env.NOTES_BACKUPS}"]
  - name: Reload service from disk
    http: {method: POST, url: "{env.NOTES_URL}/admin/reload", bearer_token_env: NOTES_ADMIN_TOKEN}
verify: {url: "{env.NOTES_URL}/healthz", successes: 3, interval_seconds: 0.5, timeout_seconds: 20}
```

A step that prints `{"facts": {...}}` as its last line has those facts recorded in the postmortem; `snapshot_age_seconds`
is what the RPO check reads. A second example, [`k8s-rollback-unavailable.yaml`](playbooks/k8s-rollback-unavailable.yaml),
rolls back a Deployment whose replicas stay unavailable.

## Design decisions

- **Humans are paged anyway.** Automation runs in parallel with the page, not instead of it. The worst failure mode of
  auto-remediation is a quiet one.
- **Verified, or it did not happen.** A restore that exits 0 is not a recovery; three consecutive healthy probes are.
- **Never restore what does not verify.** Snapshots are checksummed when taken and again before restore. The
  corrupt-backups drill exists to prove this.
- **No shell, no label injection.** Commands are argv lists. Alert labels come from whoever can reach the webhook, so
  `{label.x}` is substituted only when the value is a plain name (`[A-Za-z0-9._:/-]`); otherwise the step fails.
- **The postmortem waits for the automation.** If the alert resolves while a restore is still running, the draft is
  written when the restore finishes, so it never misses the end of its own story.
- **Repeat notifications are idempotent.** Alertmanager re-sends firing alerts every `repeat_interval`; that must not
  run a second restore.

## What has and has not been verified

| Verified (run in the build environment) | Not verified (needs a run) |
|---|---|
| All 35 tests pass, including both drills end to end against the real demo service | drpilot receiving webhooks from a real Alertmanager (only Alertmanager-shaped payloads were used) |
| `make drill` and `make drill-fail` produced the two drafts in `postmortems/drills/` | The alert rules evaluated by Prometheus (CI runs `promtool check rules` for syntax only) |
| Three separate processes (notes service, `drpilot serve`, `drpilot watch`) recovered a corrupted data file over HTTP, with token auth enforced | The Kubernetes rollback playbook against a cluster (it is loaded and validated, never run) |
| GitHub issue publishing against a local fake of the API, including the failure path | Publishing to the real GitHub API |
| `make replay` on the sample payloads in `examples/` | Any real incident: there has been none, so no postmortem here describes one |

## Limitations and next steps

Single process with a JSON-file store, so one responder per service set; a real deployment needs one leader or a
shared store. Recovery steps run serially, and there is no rate limit across incidents (a flapping alert could trigger
many restores). Next: a cooldown per playbook, a Prometheus query step to record error-budget impact in the draft,
a scheduled restore test that fires an alert when a snapshot does not verify (the follow-up the corrupt-backups drill
proposed), and posting the draft as a pull request into `postmortems/` instead of an issue.

## Repository layout
```
drpilot/          responder, playbooks, renderer, server, watcher, drill, CLI
playbooks/        recovery playbooks (YAML)                demo/          notes service + snapshot/restore
observability/    Alertmanager route + alert rules          examples/      sample Alertmanager payloads
postmortems/      drafts; drills/ holds the committed drill output
docs/             runbook, schematics                       tests/         unit, integration and drill tests
```

## License
MIT
