# Runbook: NotesUnhealthy

**Alert:** `NotesUnhealthy` (severity `page`, service `notes`). `/healthz` has failed: the data file is missing,
unreadable, fails its checksum, or no longer matches what the service holds in memory.

**Automation:** drpilot runs the playbook [`notes-restore-from-snapshot`](../../playbooks/notes-restore.yaml) as soon
as the alert fires. You are still paged. Check the incident's timeline before acting, because the automation may already
have recovered the service:

```bash
curl -s -H "Authorization: Bearer $DRPILOT_TOKEN" http://drpilot:9095/incidents
```

## If automation recovered it (status `mitigated` or `closed`)
1. Confirm `/healthz` returns 200 and the note count is plausible.
2. Writes made after the restored snapshot are gone. The postmortem draft records the snapshot age (the recovery point
   actually achieved). Decide whether anyone needs to be told.
3. Finish the postmortem draft: root cause, impact in plain words, owners for action items.

## If automation gave up (status `escalated`)
1. Read the failed step in the timeline. The most common causes, in order:
   - **No snapshot verified:** every snapshot is corrupt or the directory is empty. Look for an off-host copy.
     Do not restore an unverified file: the service will refuse to reload it anyway.
   - **Reload returned 401:** the responder's `NOTES_ADMIN_TOKEN` differs from the service's.
   - **Verification failed:** the restore worked but `/healthz` is still failing. Check the `reason` in the response.
2. Manual restore, the same steps the playbook runs:
   ```bash
   python3 demo/backup.py restore --data "$NOTES_DATA" --dir "$NOTES_BACKUPS"
   curl -X POST -H "Authorization: Bearer $NOTES_ADMIN_TOKEN" "$NOTES_URL/admin/reload"
   ```
3. Once healthy, the alert resolves and drpilot writes the postmortem draft with the full timeline, including the
   failed automation. Add what you did by hand to it.

## Afterwards
If the automation failed, fix the playbook and re-run `make drill` before closing the action item: a recovery
path that has not been drilled since it changed is a guess.
