from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.config import FIXTURES_DIR
from app.db import connect
from app.engines.reconcile import DIFF_MATCHED, compare_sides
from app.engines.sampling import (
    CONFLICTED_BATCH_STATUS,
    FULL_BATCH_STATUS,
    MODE_FULL,
    MODE_SAMPLE,
    SAMPLE_BATCH_STATUS,
    VALID_MODES,
    select_sample,
)
from app.repositories import batches as batch_repo
from app.repositories import contracts as contract_repo
from app.repositories import pairs as pair_repo
from app.repositories import tickets as ticket_repo

DEFAULT_SAMPLE_RATE = 0.4
DEFAULT_SAMPLE_CAP = 25


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_fixture(name: str) -> list[dict[str, Any]]:
    path = FIXTURES_DIR / name
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"fixture {name} must be a JSON array")
    return data


def dashboard_stats() -> dict[str, Any]:
    conn = connect()
    try:
        return {
            "pair_count": conn.execute("SELECT COUNT(*) c FROM reconcile_pairs").fetchone()["c"],
            "enabled_pairs": conn.execute(
                "SELECT COUNT(*) c FROM reconcile_pairs WHERE enabled=1"
            ).fetchone()["c"],
            "batch_count": conn.execute("SELECT COUNT(*) c FROM reconcile_batches").fetchone()["c"],
            "full_batch_count": conn.execute(
                "SELECT COUNT(*) c FROM reconcile_batches WHERE mode='full'"
            ).fetchone()["c"],
            "sample_batch_count": conn.execute(
                "SELECT COUNT(*) c FROM reconcile_batches WHERE mode='sample'"
            ).fetchone()["c"],
            "conflicted_batch_count": conn.execute(
                "SELECT COUNT(*) c FROM reconcile_batches WHERE conflicted=1"
            ).fetchone()["c"],
            "diff_count": conn.execute("SELECT COUNT(*) c FROM reconcile_diffs").fetchone()["c"],
            "open_dispositions": conn.execute(
                "SELECT COUNT(*) c FROM diff_tickets WHERE status='open'"
            ).fetchone()["c"],
            "policy": conn.execute(
                "SELECT value FROM settings WHERE key='default_policy'"
            ).fetchone()["value"],
            "default_mode": conn.execute(
                "SELECT value FROM settings WHERE key='default_reconcile_mode'"
            ).fetchone()["value"],
        }
    finally:
        conn.close()


def list_pairs() -> list[dict[str, Any]]:
    conn = connect()
    try:
        return pair_repo.list_pairs(conn)
    finally:
        conn.close()


def list_batches(limit: int = 50) -> list[dict[str, Any]]:
    conn = connect()
    try:
        rows = batch_repo.list_batches(conn, limit=limit)
        pairs = {p["id"]: p for p in pair_repo.list_pairs(conn)}
        for r in rows:
            p = pairs.get(r["pair_id"])
            r["pair_code"] = p["code"] if p else None
            r["pair_title"] = p["title"] if p else None
        return rows
    finally:
        conn.close()


def list_diffs(batch_id: int | None = None, pair_id: int | None = None) -> list[dict[str, Any]]:
    conn = connect()
    try:
        return batch_repo.list_diffs(conn, batch_id=batch_id, pair_id=pair_id)
    finally:
        conn.close()


def list_dispositions() -> list[dict[str, Any]]:
    """Difference disposition records (not a customer-service ticket desk)."""
    conn = connect()
    try:
        return ticket_repo.list_tickets(conn)
    finally:
        conn.close()


def list_contracts() -> list[dict[str, Any]]:
    conn = connect()
    try:
        return contract_repo.list_contracts(conn)
    finally:
        conn.close()


def list_settings() -> dict[str, str]:
    conn = connect()
    try:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}
    finally:
        conn.close()


def update_settings(updates: dict[str, str]) -> dict[str, str]:
    conn = connect()
    try:
        allowed = {
            "default_reconcile_mode",
            "default_sample_rate",
            "sample_size_cap",
            "default_policy",
            "auto_overwrite",
        }
        for key, value in updates.items():
            if key not in allowed:
                raise ValueError(f"unknown setting: {key}")
            if key == "default_reconcile_mode" and value not in VALID_MODES:
                raise ValueError("default_reconcile_mode must be 'full' or 'sample'")
            if key in {"default_sample_rate", "sample_size_cap"}:
                if key == "default_sample_rate":
                    _parse_sample_params(value, 1)
                else:
                    _parse_sample_params(0.5, value)
            conn.execute(
                """
                INSERT INTO settings(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, str(value)),
            )
        conn.commit()
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}
    finally:
        conn.close()


def _parse_sample_params(raw_rate: Any, raw_cap: Any) -> tuple[float, int]:
    try:
        rate = float(raw_rate)
    except (TypeError, ValueError) as exc:
        raise ValueError("sample rate must be a number between 0 and 1") from exc
    if not 0 < rate <= 1:
        raise ValueError("sample rate must satisfy 0 < rate <= 1")
    try:
        cap = int(raw_cap)
    except (TypeError, ValueError) as exc:
        raise ValueError("sample size cap must be a positive integer") from exc
    if cap < 1:
        raise ValueError("sample size cap must be a positive integer")
    return rate, cap


def _sample_settings(conn: sqlite3.Connection) -> tuple[float, int]:  # type: ignore[name-defined]
    rows = {
        r["key"]: r["value"]
        for r in conn.execute("SELECT key, value FROM settings").fetchall()
    }
    return _parse_sample_params(
        rows.get("default_sample_rate", str(DEFAULT_SAMPLE_RATE)),
        rows.get("sample_size_cap", str(DEFAULT_SAMPLE_CAP)),
    )


def run_reconcile(
    pair_id: int,
    note: str | None = None,
    *,
    mode: str | None = None,
    sample_seed: str | None = None,
    sample_rate: float | None = None,
    sample_cap: int | None = None,
) -> dict[str, Any]:
    """Extract both fixtures, align, persist batch + diffs. No overwrite.

    One batch carries exactly one primary strategy: full line-by-line review
    or a reproducible sample scout. Sample batches are never clearance states.
    """
    conn = connect()
    try:
        pair = pair_repo.get_pair(conn, pair_id)
        if not pair:
            raise ValueError("pair not found")
        if not pair["enabled"]:
            raise ValueError("pair disabled")

        if mode is None:
            mode = conn.execute(
                "SELECT value FROM settings WHERE key='default_reconcile_mode'"
            ).fetchone()["value"]
        if mode not in VALID_MODES:
            raise ValueError("mode must be 'full' or 'sample'")
        if mode == MODE_FULL and (sample_seed or sample_rate is not None or sample_cap is not None):
            raise ValueError("sample parameters are only allowed in sample mode (one strategy per batch)")

        left_rows = _load_fixture(pair["left_fixture"])
        right_rows = _load_fixture(pair["right_fixture"])
        now = _now()
        seq = conn.execute("SELECT COUNT(*) c FROM reconcile_batches").fetchone()["c"] + 1
        batch_no = f"RB-{now[:10].replace('-', '')}-{seq:04d}"

        sample_meta: dict[str, Any] | None = None
        if mode == MODE_SAMPLE:
            cfg_rate, cfg_cap = _sample_settings(conn)
            rate = sample_rate if sample_rate is not None else cfg_rate
            cap = sample_cap if sample_cap is not None else cfg_cap
            rate, cap = _parse_sample_params(rate, cap)
            sample = select_sample(
                left_rows,
                right_rows,
                align_keys=pair["align_keys"],
                compare_fields=pair["compare_fields"],
                rate=rate,
                cap=cap,
                seed=sample_seed,
            )
            counts = sample["counts"]
            diffs = sample["diffs"]
            status = SAMPLE_BATCH_STATUS
            sample_meta = {
                "seed": sample["seed"],
                "rate": sample["rate"],
                "cap": sample["cap"],
                "population": sample["population"],
                "sample_size": sample["sample_size"],
                "size_formula": sample["size_formula"],
                "sampled_keys": sample["sampled_keys"],
                "clearance_allowed": False,
                "scout_only": True,
            }
        else:
            result = compare_sides(
                left_rows,
                right_rows,
                align_keys=pair["align_keys"],
                compare_fields=pair["compare_fields"],
            )
            counts = result["counts"]
            diffs = result["diffs"]
            status = FULL_BATCH_STATUS

        batch_id = batch_repo.insert_batch(
            conn,
            batch_no=batch_no,
            pair_id=pair_id,
            mode=mode,
            status=status,
            counts=counts,
            note=note,
            created_at=now,
            sample_meta=sample_meta,
        )
        for diff in diffs:
            if diff["kind"] == DIFF_MATCHED:
                continue
            batch_repo.insert_diff(
                conn, batch_id=batch_id, pair_id=pair_id, diff=diff, created_at=now
            )

        conflict = None
        if mode == MODE_FULL:
            conflict = _apply_full_review_conflicts(conn, pair, batch_id)

        conn.commit()
        batch = batch_repo.get_batch(conn, batch_id)
        assert batch is not None
        batch["pair_code"] = pair["code"]
        batch["pair_title"] = pair["title"]
        batch["policy"] = "record_only"
        batch["counts"] = counts
        batch["diff_preview"] = batch_repo.list_diffs(conn, batch_id=batch_id, limit=20)
        if conflict is not None:
            batch["sample_conflicts"] = conflict
        return batch
    finally:
        conn.close()


def _verdict_map(diffs: list[dict[str, Any]], align_keys: list[str]) -> dict[tuple, str]:
    out: dict[tuple, str] = {}
    for d in diffs:
        key = tuple(d["align_key"][k] for k in align_keys)
        out[key] = d["kind"]
    return out


def _apply_full_review_conflicts(
    conn: sqlite3.Connection,
    pair: dict[str, Any],
    full_batch_id: int,
) -> dict[str, Any]:
    """Compare the full review against prior sample scouts of the same pair.

    Two conflict shapes void/downgrade a scout batch:

    * ``verdict_contradiction`` — a sampled key's verdict in the scout differs
      from the full review verdict (typically snapshot drift between runs).
    * ``coverage_gap_clean_sample`` — the scout summary showed zero diffs and
      read as clean, but the full review finds diffs on keys the sample never
      covered. The clean scout impression is misleading and must not stand.

    A sample must never stand in for a full clearance either way.
    """
    full_batch = batch_repo.get_batch(conn, full_batch_id)
    assert full_batch is not None
    full_diffs = batch_repo.list_diffs(conn, batch_id=full_batch_id, limit=100000)
    full_verdict = _verdict_map(full_diffs, pair["align_keys"])
    full_diff_keys = set(full_verdict)

    prior_scouts = conn.execute(
        """
        SELECT * FROM reconcile_batches
        WHERE pair_id=? AND mode='sample' AND conflicted=0
        ORDER BY id ASC
        """,
        (pair["id"],),
    ).fetchall()

    affected_batches: list[dict[str, Any]] = []
    total_conflicts = 0
    for row in prior_scouts:
        scout = dict(row)
        meta = json.loads(scout["sample_meta_json"]) if scout["sample_meta_json"] else None
        if not meta:
            continue
        key_conflicts: list[dict[str, Any]] = []
        sampled_keys = set()
        for entry in meta.get("sampled_keys", []):
            key = tuple(entry["align_key"][k] for k in pair["align_keys"])
            sampled_keys.add(key)
            scout_verdict = entry["verdict"]
            full_verdict_kind = full_verdict.get(key, DIFF_MATCHED)
            if scout_verdict != full_verdict_kind:
                key_conflicts.append(
                    {
                        "reason": "verdict_contradiction",
                        "align_key": entry["align_key"],
                        "key_hash": entry["key_hash"],
                        "scout_verdict": scout_verdict,
                        "full_verdict": full_verdict_kind,
                    }
                )

        # Coverage gap: an all-clean sample while the full review finds
        # diffs outside the sampled population.
        uncovered_diff_keys = full_diff_keys - sampled_keys
        if scout["diff_total"] == 0 and uncovered_diff_keys:
            for key in sorted(uncovered_diff_keys, key=lambda t: tuple(str(x) for x in t)):
                key_conflicts.append(
                    {
                        "reason": "coverage_gap_clean_sample",
                        "align_key": {k: key[i] for i, k in enumerate(pair["align_keys"])},
                        "key_hash": None,
                        "scout_verdict": None,
                        "full_verdict": full_verdict[key],
                    }
                )

        if key_conflicts:
            total_conflicts += len(key_conflicts)
            detail = {
                "full_batch_id": full_batch_id,
                "full_batch_no": full_batch["batch_no"],
                "conflict_count": len(key_conflicts),
                "conflicting_keys": key_conflicts,
                "reasons": sorted({c["reason"] for c in key_conflicts}),
                "resolution": "sample_scout_voided",
                "message": "全量复核与抽样摸底结论冲突，该抽样批次结论已作废降级，不得作为放行依据。",
            }
            batch_repo.mark_conflicted(
                conn,
                batch_id=scout["id"],
                full_batch_id=full_batch_id,
                detail=detail,
            )
            affected_batches.append(
                {
                    "batch_id": scout["id"],
                    "batch_no": scout["batch_no"],
                    "conflict_count": len(key_conflicts),
                    "reasons": detail["reasons"],
                }
            )

    return {
        "checked_scout_batches": len(prior_scouts),
        "conflicted_batches": affected_batches,
        "conflict_count": total_conflicts,
    }


def audit_summary(batch_id: int) -> dict[str, Any]:
    """Lightweight audit view for a batch (export hooks left for later cuts)."""
    conn = connect()
    try:
        batch = batch_repo.get_batch(conn, batch_id)
        if not batch:
            raise ValueError("batch not found")
        pair = pair_repo.get_pair(conn, batch["pair_id"])
        diffs = batch_repo.list_diffs(conn, batch_id=batch_id)
        summary = {
            "batch": batch,
            "pair": pair,
            "mode": batch["mode"],
            "status": batch["status"],
            "clearance_allowed": batch["mode"] == MODE_FULL
            and batch["status"] == FULL_BATCH_STATUS,
            "diff_count": len(diffs),
            "kinds": {
                "left_only": sum(1 for d in diffs if d["kind"] == "left_only"),
                "right_only": sum(1 for d in diffs if d["kind"] == "right_only"),
                "field_mismatch": sum(1 for d in diffs if d["kind"] == "field_mismatch"),
            },
            "export_ready": False,
            "note": "底座仅提供摘要；审计包导出留给后题切口",
        }
        if batch["mode"] == MODE_SAMPLE:
            summary["note"] = (
                "抽样批次仅为摸底，不可标记为对账已清/放行；清账须另跑同对全量复核。"
            )
        if batch.get("conflict_detail"):
            summary["note"] = batch["conflict_detail"].get("message", summary["note"])
        return summary
    finally:
        conn.close()
