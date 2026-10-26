# Runbook: OrdersDataUnhealthy

**Alert:** `OrdersDataUnhealthy` (severity `page`, service `orders`, `autoremediate="true"`). The orders service reports
a missing table or an unavailable database for a minute. Its `/healthz` says which: `table orders is missing` or
`database unavailable`.

**Automation:** drpilot runs [`orders-restore-from-snapshot`](../../playbooks/orders-restore.yaml) as soon as the alert
fires. You are paged as well. Look at the incident before acting, because automation may already have recovered it:

```bash
curl -s -H "Authorization: Bearer $DRPILOT_TOKEN" http://drpilot:9095/incidents
```

## What "recovered" means here
Three consecutive healthy `/healthz` probes **and** passing data checks (schema, orphans, order totals against items,
and a test order written through the service). A restore that exits 0 is not a recovery.

## If automation recovered it (status `mitigated` or `closed`)
1. Read the draft postmortem: the **data loss window** is the writes between the restored snapshot and the failure. Decide
   whether anyone must be told, and whether the lost writes can be replayed from another source.
2. If `snapshots_skipped` is above zero, newer snapshots failed verification and were **not** restored. Find out why
   (the reason is in the draft). A snapshot that fails its totals check was taken from already-wrong data.
3. Finish the draft: root cause, plain-language impact, owners.

## If automation gave up (status `escalated`)
1. Read the failed step in the timeline. Common causes, in order:
   - **`no snapshot verified`:** every snapshot failed its checksum, restore or validation. Look for an off-host copy
     (S3 versions: `aws s3api list-object-versions`). Do **not** force a restore of an unverified dump.
   - **`cannot connect to the database` / `permission denied to create database`:** `DATABASE_URL` is wrong, or its user
     lacks `CREATEDB` (restores are proven in a scratch database before they touch live data).
   - **Verification failed after a good restore:** read the failing check; the data is restored but wrong or the service
     cannot write to it.
2. Manual restore, the same steps the playbook runs:
   ```bash
   export DATABASE_URL=... BACKUP_STORE=...
   python3 scripts/recover.py list
   python3 scripts/recover.py restore
   python3 scripts/recover.py validate --smoke-url "$ORDERS_URL"
   ```
3. Once healthy the alert resolves and drpilot writes the postmortem draft, including the failed automation.

## Afterwards
If automation failed, fix the playbook or the backups and re-run `make drill-fail`. A recovery path that has not been
drilled since it changed is a guess.
