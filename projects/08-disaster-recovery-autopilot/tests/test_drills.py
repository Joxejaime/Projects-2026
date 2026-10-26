"""End-to-end drills: a real PostgreSQL server, the real recovery tools, the real responder."""

import pytest

from drpilot.drill import SCENARIOS, run_drill

pytestmark = [pytest.mark.postgres, pytest.mark.drill]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_drill_passes(tmp_path, scenario):
    result = run_drill(tmp_path, scenario=scenario, timeout=60, interval=0.1)
    assert result.passed, "\n".join(result.summary)


def draft(tmp_path, scenario):
    result = run_drill(tmp_path, scenario=scenario, timeout=60, interval=0.1)
    assert result.passed, "\n".join(result.summary)
    return result.postmortem.read_text()


def test_dropped_table_draft_shows_verified_recovery_and_the_data_loss_window(tmp_path):
    text = draft(tmp_path, "dropped-table")
    assert "Health probes | ok" in text and "Validate recovered data and write path | ok" in text
    assert "write path: order" in text and "RPO (last good snapshot to impact start)" in text
    assert "`snapshot_created_at`" in text and "**TODO (human):**" in text


def test_poisoned_backup_draft_names_the_skipped_snapshot(tmp_path):
    text = draft(tmp_path, "poisoned-backup")
    assert "`snapshots_skipped` | 1" in text
    assert "totals: 2 order(s) whose total differs from their items" in text
    assert "newer snapshot(s) failed verification during recovery" in text


def test_corrupt_backups_draft_records_the_failed_automation_and_the_follow_up(tmp_path):
    text = draft(tmp_path, "corrupt-backups")
    assert "could not recover the service, so a human was paged" in text
    assert "checksum mismatch" in text and "Automation gave up after 2 attempt(s)" in text
    assert "run `recover.py restore-test` on a schedule" in text
