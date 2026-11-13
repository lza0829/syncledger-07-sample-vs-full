"""Service-level tests: mode switch, scout gate, conflicts, counts."""
import pytest

from app.services import reconcile_service as svc


def test_default_mode_setting_is_full_and_persisted(pair_ids):
    assert svc.list_settings()["default_reconcile_mode"] == "full"
    svc.update_settings({"default_reconcile_mode": "sample"})
    assert svc.list_settings()["default_reconcile_mode"] == "sample"
    with pytest.raises(ValueError):
        svc.update_settings({"default_reconcile_mode": "bogus"})


def test_sample_batch_is_scout_never_clearance(pair_ids):
    inv = pair_ids["inventory_hq_vs_store"]
    batch = svc.run_reconcile(inv, mode="sample", sample_seed="abc", sample_rate=0.4, sample_cap=25)
    assert batch["mode"] == "sample"
    assert batch["status"] == "sampled"
    assert batch["sample_meta"]["scout_only"] is True
    assert batch["sample_meta"]["clearance_allowed"] is False
    audit = svc.audit_summary(batch["id"])
    assert audit["clearance_allowed"] is False
    assert "摸底" in audit["note"]
    # explainable, reproducible metadata is persisted
    assert batch["sample_seed"] == "abc"
    assert batch["sample_population"] == 5
    assert batch["sample_size_formula"].startswith("min(")
    assert all(len(k["key_hash"]) == 16 for k in batch["sample_meta"]["sampled_keys"])


def test_same_seed_rerun_is_stable(pair_ids):
    inv = pair_ids["inventory_hq_vs_store"]
    first = svc.run_reconcile(inv, mode="sample", sample_seed="stable-seed")
    second = svc.run_reconcile(inv, mode="sample", sample_seed="stable-seed")
    h1 = [k["key_hash"] for k in first["sample_meta"]["sampled_keys"]]
    h2 = [k["key_hash"] for k in second["sample_meta"]["sampled_keys"]]
    assert h1 == h2
    assert first["counts"] == second["counts"]


def test_random_seed_is_generated_and_persisted_when_omitted(pair_ids):
    inv = pair_ids["inventory_hq_vs_store"]
    batch = svc.run_reconcile(inv, mode="sample")
    assert batch["sample_meta"]["seed"]
    assert batch["sample_seed"] == batch["sample_meta"]["seed"]


def test_full_batch_is_completed_and_clearance_eligible(pair_ids):
    inv = pair_ids["inventory_hq_vs_store"]
    batch = svc.run_reconcile(inv, mode="full")
    assert batch["mode"] == "full"
    assert batch["status"] == "completed"
    assert svc.audit_summary(batch["id"])["clearance_allowed"] is True


def test_full_mode_rejects_sample_parameters(pair_ids):
    inv = pair_ids["inventory_hq_vs_store"]
    with pytest.raises(ValueError):
        svc.run_reconcile(inv, mode="full", sample_seed="x")
    with pytest.raises(ValueError):
        svc.run_reconcile(inv, mode="full", sample_rate=0.5)


def test_invalid_mode_and_sample_params_rejected(pair_ids):
    inv = pair_ids["inventory_hq_vs_store"]
    with pytest.raises(ValueError):
        svc.run_reconcile(inv, mode="sideways")
    with pytest.raises(ValueError):
        svc.run_reconcile(inv, mode="sample", sample_rate=1.5)
    with pytest.raises(ValueError):
        svc.run_reconcile(inv, mode="sample", sample_cap=0)


def test_verdict_contradiction_on_snapshot_drift_voids_scout(pair_ids, monkeypatch):
    inv_id = pair_ids["inventory_hq_vs_store"]
    pair = next(p for p in svc.list_pairs() if p["id"] == inv_id)
    real_loader = svc._load_fixture

    def drifted(name):
        rows = real_loader(name)
        if name == pair["left_fixture"]:
            rows = [dict(r) for r in rows]
            for r in rows:
                if r["sku_id"] == "SKU-100" and r["store_id"] == "S01":
                    r["qty"] = 118  # matches right side in the drifted snapshot
        return rows

    monkeypatch.setattr(svc, "_load_fixture", drifted)
    scout = svc.run_reconcile(inv_id, mode="sample", sample_seed="drift",
                              sample_rate=1.0, sample_cap=25)
    monkeypatch.setattr(svc, "_load_fixture", real_loader)
    full = svc.run_reconcile(inv_id, mode="full")

    conflict = full["sample_conflicts"]
    assert any(c["batch_id"] == scout["id"] for c in conflict["conflicted_batches"])
    audit = svc.audit_summary(scout["id"])
    assert audit["batch"]["status"] == "conflicted"
    assert audit["batch"]["conflict_of_batch_id"] == full["id"]
    detail = audit["batch"]["conflict_detail"]
    assert "verdict_contradiction" in detail["reasons"]
    hit = next(c for c in detail["conflicting_keys"] if c["reason"] == "verdict_contradiction")
    assert hit["scout_verdict"] == "matched"
    assert hit["full_verdict"] == "field_mismatch"
    assert audit["clearance_allowed"] is False


def test_clean_sample_coverage_gap_is_voided_by_full_review(pair_ids):
    inv_id = pair_ids["inventory_hq_vs_store"]
    # find a 1-key seed whose sampled key happens to be clean
    scout_id = None
    for i in range(200):
        attempt = svc.run_reconcile(inv_id, mode="sample", sample_seed=f"s{i}",
                                    sample_rate=0.2, sample_cap=1)
        if attempt["diff_total"] == 0:
            scout_id = attempt["id"]
            break
    assert scout_id is not None
    full = svc.run_reconcile(inv_id, mode="full")
    audit = svc.audit_summary(scout_id)
    detail = audit["batch"]["conflict_detail"]
    assert audit["batch"]["status"] == "conflicted"
    assert detail["reasons"] == ["coverage_gap_clean_sample"]
    assert detail["full_batch_id"] == full["id"]
    assert detail["resolution"] == "sample_scout_voided"


def test_agreeing_sample_is_not_conflicted(pair_ids):
    pay = pair_ids["payment_vs_ledger"]
    scout = svc.run_reconcile(pay, mode="sample", sample_seed="pay",
                              sample_rate=1.0, sample_cap=10)
    full = svc.run_reconcile(pay, mode="full")
    assert full["sample_conflicts"]["conflict_count"] == 0
    row = next(b for b in svc.list_batches(limit=100) if b["id"] == scout["id"])
    assert row["status"] == "sampled" and row["conflicted"] is False


def test_conflicted_scout_not_reprocessed_by_later_full_runs(pair_ids):
    pay = pair_ids["payment_vs_ledger"]
    svc.run_reconcile(pay, mode="sample", sample_seed="pay", sample_rate=1.0, sample_cap=10)
    first_full = svc.run_reconcile(pay, mode="full")
    pointer_after_first = {
        b["id"]: b["conflict_of_batch_id"] for b in svc.list_batches(limit=100) if b["conflicted"]
    }
    svc.run_reconcile(pay, mode="full")
    pointer_after_second = {
        b["id"]: b["conflict_of_batch_id"] for b in svc.list_batches(limit=100) if b["conflicted"]
    }
    assert pointer_after_first == pointer_after_second
    assert first_full["sample_conflicts"]["checked_scout_batches"] >= 1


def test_dashboard_counts_match_batch_list(pair_ids):
    inv = pair_ids["inventory_hq_vs_store"]
    svc.run_reconcile(inv, mode="sample", sample_seed="x", sample_rate=0.2, sample_cap=1)
    svc.run_reconcile(inv, mode="full")
    stats = svc.dashboard_stats()
    batches = svc.list_batches(limit=1000)
    assert stats["full_batch_count"] == sum(1 for b in batches if b["mode"] == "full")
    assert stats["sample_batch_count"] == sum(1 for b in batches if b["mode"] == "sample")
    assert stats["conflicted_batch_count"] == sum(1 for b in batches if b["conflicted"])
    assert stats["batch_count"] == stats["full_batch_count"] + stats["sample_batch_count"]


def test_sample_diff_rows_only_cover_sampled_keys(pair_ids):
    inv = pair_ids["inventory_hq_vs_store"]
    batch = svc.run_reconcile(inv, mode="sample", sample_seed="x", sample_rate=0.4, sample_cap=2)
    diffs = svc.list_diffs(batch_id=batch["id"])
    assert len(diffs) <= batch["sample_meta"]["sample_size"]
    assert all(d["batch_id"] == batch["id"] for d in diffs)
