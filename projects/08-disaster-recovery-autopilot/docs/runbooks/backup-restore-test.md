# Runbook: BackupRestoreTestFailing and BackupRestoreTestStale

The restore test proves the **newest snapshot restores and passes the data checks**, in a scratch database, without
touching live data. It is the only thing that tells you a backup is bad before you need it.

```bash
python3 scripts/recover.py restore-test --metrics-file /var/lib/node_exporter/textfile/drpilot.prom --max-age-seconds 7200
```

It writes Prometheus textfile-collector metrics (`drpilot_restore_test_success`, `..._last_success_timestamp_seconds`,
`..._duration_seconds`, `..._snapshot_age_seconds`). `--max-age-seconds` makes "backups have stopped" a failure too.
`..._duration_seconds` is the honest restore time for your data: use it, not a guess, as the RTO you promise.

## Schedule it
Every hour is a reasonable start, offset from the snapshot job:

```cron
17 * * * *  DATABASE_URL=... BACKUP_STORE=s3://... /usr/bin/python3 /opt/drpilot/scripts/recover.py restore-test --metrics-file /var/lib/node_exporter/textfile/drpilot.prom --max-age-seconds 7200
```

On Kubernetes use a CronJob with the same command and a volume shared with node_exporter's textfile directory. Run the
snapshot job on its own schedule (`recover.py snapshot`); it validates the live data first and refuses to back up
data that is already wrong.

## `BackupRestoreTestFailing` (autoremediate)
drpilot runs [`backup-refresh`](../../playbooks/backup-refresh.yaml): take a fresh validated snapshot, then prove it
restores. If the **live** data fails validation the snapshot is refused and the playbook fails: that means your
backups are not the only problem. Treat it as a data-integrity incident and see the orders runbook.

## `BackupRestoreTestStale` (ticket, no automation)
No restore test has passed for 36 hours: the job is not running, or has been failing and nobody acted. Check the job's
logs first, then the alert history for `BackupRestoreTestFailing`.
