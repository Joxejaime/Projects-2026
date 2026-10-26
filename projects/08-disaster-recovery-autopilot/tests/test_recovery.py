"""Snapshot, restore, validation and restore-test against a real PostgreSQL server."""

import json
import os
import time

import psycopg
import pytest

from recovery import cli, snapshots
from recovery.pg import RecoveryError
from recovery.store import S3Store, open_store, snapshot_names
from recovery.validate import validate

from .helpers import post_order

pytestmark = pytest.mark.postgres


def sql(url, statement):
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(statement)


def totals(url):
    with psycopg.connect(url) as conn:
        return [r[0] for r in conn.execute("SELECT total_cents FROM orders ORDER BY id")]


@pytest.fixture
def populated(orders_service, db_url):
    for qty in (1, 2, 3):
        post_order(orders_service, qty)
    return db_url


def test_snapshot_writes_dump_then_manifest_with_counts_and_checksum(populated, store):
    manifest = snapshots.take(populated, store, log=lambda _m: None)
    assert manifest["tables"] == {"orders": 3, "order_items": 3}
    assert len(manifest["dump_sha256"]) == 64 and manifest["validated"] is True
    assert snapshot_names(store) == [manifest["name"]]
    assert sorted(store.keys()) == [f"{manifest['name']}.dump", f"{manifest['name']}.manifest.json"]


def test_snapshot_without_a_manifest_does_not_exist(populated, store):
    manifest = snapshots.take(populated, store, log=lambda _m: None)
    (store.dir / f"{manifest['name']}.manifest.json").unlink()
    assert snapshot_names(store) == []
    with pytest.raises(RecoveryError, match="no snapshots"):
        snapshots.restore(populated, store, log=lambda _m: None)


def test_snapshot_refuses_data_that_already_fails_validation(populated, store):
    sql(populated, "UPDATE orders SET total_cents = total_cents + 1 WHERE id = 1")
    with pytest.raises(RecoveryError, match="refusing to snapshot.*totals"):
        snapshots.take(populated, store, log=lambda _m: None)
    assert store.keys() == []


def test_snapshot_never_overwrites_an_existing_one(populated, store, clock):
    snapshots.take(populated, store, clock=clock, log=lambda _m: None)
    with pytest.raises(RecoveryError, match="already exists"):
        snapshots.take(populated, store, clock=clock, log=lambda _m: None)  # same second


def test_restore_recovers_dropped_tables_and_reports_facts(populated, store):
    snapshots.take(populated, store, log=lambda _m: None)
    before = totals(populated)
    sql(populated, "DROP TABLE order_items, orders")
    facts = snapshots.restore(populated, store, log=lambda _m: None)
    assert totals(populated) == before
    assert facts["rows_orders"] == 3 and facts["snapshots_skipped"] == 0
    assert facts["snapshot_age_seconds"] >= 0 and facts["snapshot_created_at"].endswith("Z")


def test_restore_skips_a_snapshot_whose_dump_was_tampered_with(populated, store):
    first = snapshots.take(populated, store, log=lambda _m: None)
    time.sleep(1.1)
    second = snapshots.take(populated, store, log=lambda _m: None)
    (store.dir / f"{second['name']}.dump").write_bytes(b"bit rot")
    sql(populated, "DROP TABLE order_items, orders")
    facts = snapshots.restore(populated, store, log=lambda _m: None)
    assert facts["snapshot"] == first["name"] and facts["snapshots_skipped"] == 1
    assert "checksum mismatch" in facts["skipped_reasons"]


def test_restore_skips_a_snapshot_that_restores_but_holds_wrong_data(populated, store):
    good = snapshots.take(populated, store, log=lambda _m: None)
    good_totals = totals(populated)
    time.sleep(1.1)
    sql(populated, "UPDATE orders SET total_cents = total_cents + 500 WHERE id <= 2")
    poisoned = snapshots.take(populated, store, verify=False, log=lambda _m: None)  # a backup job without validation
    assert poisoned["validated"] is False
    sql(populated, "DROP TABLE order_items, orders")
    facts = snapshots.restore(populated, store, log=lambda _m: None)
    assert facts["snapshot"] == good["name"] and totals(populated) == good_totals
    assert "totals" in facts["skipped_reasons"]


def test_restore_refuses_when_no_snapshot_proves_itself(populated, store):
    manifest = snapshots.take(populated, store, log=lambda _m: None)
    (store.dir / f"{manifest['name']}.dump").write_bytes(b"bit rot")
    sql(populated, "DROP TABLE order_items, orders")
    with pytest.raises(RecoveryError, match="no snapshot verified"):
        snapshots.restore(populated, store, log=lambda _m: None)
    with psycopg.connect(populated) as conn:  # nothing was restored over the live database
        assert conn.execute("SELECT to_regclass('public.orders')").fetchone()[0] is None


def test_restore_detects_a_manifest_that_disagrees_with_the_dump_contents(populated, store):
    manifest = snapshots.take(populated, store, log=lambda _m: None)
    path = store.dir / f"{manifest['name']}.manifest.json"
    tampered = json.loads(path.read_text())
    tampered["tables"]["orders"] = 99
    path.write_text(json.dumps(tampered))
    with pytest.raises(RecoveryError, match="manifest says 99"):
        snapshots.restore(populated, store, log=lambda _m: None)


def test_validation_catches_each_kind_of_damage(populated):
    assert all(c.ok for c in validate(populated)[0])
    sql(populated, "UPDATE orders SET total_cents = 1 WHERE id = 1")
    assert [c.name for c in validate(populated)[0] if not c.ok] == ["totals"]
    sql(
        populated,
        "UPDATE orders SET total_cents = 500 WHERE id = 1; ALTER TABLE order_items DROP CONSTRAINT order_items_order_id_fkey; DELETE FROM orders WHERE id = 2",
    )
    failed = {c.name for c in validate(populated)[0] if not c.ok}
    assert failed == {"orphans"}  # order 1's total is right again; order 2's items now point at nothing
    sql(populated, "DROP TABLE order_items")
    checks, _ = validate(populated)
    assert [(c.name, c.ok) for c in checks][-1] == ("schema", False)


def test_write_path_check_goes_through_the_service_and_cleans_up(populated, orders_service):
    checks, facts = validate(populated, smoke_url=orders_service)
    assert checks[-1].name == "write path" and checks[-1].ok, checks[-1].detail
    assert facts["rows_orders"] == 3  # the smoke order is gone again
    checks, _ = validate(populated, smoke_url="http://127.0.0.1:9")
    assert not checks[-1].ok
    assert not validate(populated, smoke_url="file:///etc/passwd")[0][-1].ok


def test_restore_test_proves_the_newest_snapshot_and_writes_metrics(populated, store, tmp_path, capsys):
    snapshots.take(populated, store, log=lambda _m: None)
    metrics = tmp_path / "textfile" / "drpilot.prom"
    assert cli.main(["--store", str(store), "restore-test", "--metrics-file", str(metrics), "--max-age-seconds", "3600"]) == 0
    text = metrics.read_text()
    assert "drpilot_restore_test_success 1" in text and "drpilot_restore_test_last_success_timestamp_seconds" in text
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["facts"]["rows_orders"] == 3


def test_failing_restore_test_flips_the_metric_but_keeps_the_last_success_time(populated, store, tmp_path, capsys):
    manifest = snapshots.take(populated, store, log=lambda _m: None)
    metrics = tmp_path / "drpilot.prom"
    assert cli.main(["--store", str(store), "restore-test", "--metrics-file", str(metrics)]) == 0
    last_success = next(ln for ln in metrics.read_text().splitlines() if ln.startswith("drpilot_restore_test_last_success"))
    (store.dir / f"{manifest['name']}.dump").write_bytes(b"bit rot")
    assert cli.main(["--store", str(store), "restore-test", "--metrics-file", str(metrics)]) == 1
    text = metrics.read_text()
    assert "drpilot_restore_test_success 0" in text and last_success in text
    assert "not restorable" in capsys.readouterr().err


def test_restore_test_fails_when_backups_have_stopped(populated, store):
    snapshots.take(populated, store, log=lambda _m: None)
    with pytest.raises(RecoveryError, match="backups have stopped"):
        snapshots.restore_test(populated, store, max_age_seconds=0.0001, log=lambda _m: None)


def test_cli_snapshot_restore_round_trip_prints_facts_for_the_postmortem(populated, store, capsys):
    assert cli.main(["--store", str(store), "snapshot"]) == 0
    sql(populated, "DROP TABLE order_items, orders")
    assert cli.main(["--store", str(store), "restore"]) == 0
    facts = json.loads(capsys.readouterr().out.strip().splitlines()[-1])["facts"]
    assert facts["rows_orders"] == 3 and "snapshot_created_at" in facts


def test_cli_without_a_store_or_database_url_explains_itself(monkeypatch, capsys):
    monkeypatch.delenv("BACKUP_STORE", raising=False)
    assert cli.main(["restore"]) == 1
    assert "no backup store" in capsys.readouterr().err
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert cli.main(["validate"]) == 1
    assert "DATABASE_URL is not set" in capsys.readouterr().err


# --- S3 store: the contract with the `aws` CLI, tested against a stand-in that maps s3:// to a directory -------------

FAKE_AWS = """#!/usr/bin/env python3
import json, os, shutil, sys
root = os.environ["FAKE_S3_ROOT"]
args = sys.argv[1:]
def local(uri):
    assert uri.startswith("s3://"), uri
    return os.path.join(root, uri[5:])
if args[:2] == ["s3", "cp"]:
    src, dst = args[2], args[3]
    src, dst = (local(src) if src.startswith("s3://") else src), (local(dst) if dst.startswith("s3://") else dst)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)
elif args[:2] == ["s3api", "list-objects-v2"]:
    bucket, prefix = args[args.index("--bucket") + 1], args[args.index("--prefix") + 1]
    base = os.path.join(root, bucket)
    keys = []
    for dirpath, _, files in os.walk(base):
        for f in files:
            key = os.path.relpath(os.path.join(dirpath, f), base)
            if key.startswith(prefix):
                keys.append(key)
    print(json.dumps(keys or None))
else:
    sys.exit("unsupported: " + " ".join(args))
"""


@pytest.fixture
def fake_aws(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    aws = bin_dir / "aws"
    aws.write_text(FAKE_AWS)
    aws.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_S3_ROOT", str(tmp_path / "s3"))
    return tmp_path / "s3"


def test_s3_store_round_trips_a_snapshot_through_the_aws_cli(populated, fake_aws):
    store = open_store("s3://my-backups/orders/prod")
    assert isinstance(store, S3Store) and str(store) == "s3://my-backups/orders/prod"
    manifest = snapshots.take(populated, store, log=lambda _m: None)
    assert (fake_aws / "my-backups" / "orders" / "prod" / f"{manifest['name']}.dump").exists()
    assert snapshot_names(store) == [manifest["name"]]
    sql(populated, "DROP TABLE order_items, orders")
    assert snapshots.restore(populated, store, log=lambda _m: None)["rows_orders"] == 3


def test_s3_store_rejects_bad_uris_and_reports_cli_failures(tmp_path, monkeypatch):
    with pytest.raises(RecoveryError):
        S3Store("https://example.com/bucket")
    monkeypatch.setenv("PATH", str(tmp_path))  # no aws binary at all
    with pytest.raises(RecoveryError, match="aws CLI failed"):
        S3Store("s3://my-backups/x").keys()
