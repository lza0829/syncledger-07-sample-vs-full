from __future__ import annotations

import json
from typing import Any

import sqlite3


def _batch(r: sqlite3.Row | None) -> dict[str, Any] | None:
    if r is None:
        return None
    d = dict(r)
    d["conflicted"] = bool(d.get("conflicted"))
    d["sample_meta"] = json.loads(d.pop("sample_meta_json")) if d.get("sample_meta_json") else None
    d["conflict_detail"] = (
        json.loads(d.pop("conflict_detail_json")) if d.get("conflict_detail_json") else None
    )
    d.pop("sample_meta_json", None)
    d.pop("conflict_detail_json", None)
    return d


def _diff(r: sqlite3.Row | None) -> dict[str, Any] | None:
    if r is None:
        return None
    d = dict(r)
    d["align_key"] = json.loads(d.pop("align_key_json"))
    d["left"] = json.loads(d.pop("left_json")) if d.get("left_json") else None
    d["right"] = json.loads(d.pop("right_json")) if d.get("right_json") else None
    d["mismatched_fields"] = json.loads(d.pop("mismatched_fields_json"))
    return d


def list_batches(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM reconcile_batches ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [_batch(r) for r in rows]  # type: ignore[misc]


def get_batch(conn: sqlite3.Connection, batch_id: int) -> dict[str, Any] | None:
    return _batch(conn.execute("SELECT * FROM reconcile_batches WHERE id=?", (batch_id,)).fetchone())


def list_diffs(
    conn: sqlite3.Connection, *, batch_id: int | None = None, pair_id: int | None = None, limit: int = 200
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM reconcile_diffs WHERE 1=1"
    args: list[Any] = []
    if batch_id is not None:
        sql += " AND batch_id=?"
        args.append(batch_id)
    if pair_id is not None:
        sql += " AND pair_id=?"
        args.append(pair_id)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    return [_diff(r) for r in conn.execute(sql, args).fetchall()]  # type: ignore[misc]


def insert_batch(
    conn: sqlite3.Connection,
    *,
    batch_no: str,
    pair_id: int,
    mode: str,
    status: str,
    counts: dict[str, int],
    note: str | None,
    created_at: str,
    sample_meta: dict[str, Any] | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO reconcile_batches(
            batch_no, pair_id, mode, status, left_rows, right_rows, matched,
            left_only, right_only, field_mismatch, diff_total,
            sample_size, sample_seed, sample_rate, sample_population,
            sample_size_formula, sample_meta_json, note, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            batch_no,
            pair_id,
            mode,
            status,
            counts["left_rows"],
            counts["right_rows"],
            counts["matched"],
            counts["left_only"],
            counts["right_only"],
            counts["field_mismatch"],
            counts["diff_total"],
            (sample_meta or {}).get("sample_size"),
            (sample_meta or {}).get("seed"),
            (sample_meta or {}).get("rate"),
            (sample_meta or {}).get("population"),
            (sample_meta or {}).get("size_formula"),
            json.dumps(sample_meta, ensure_ascii=False) if sample_meta else None,
            note,
            created_at,
        ),
    )
    return int(cur.lastrowid)


def mark_conflicted(
    conn: sqlite3.Connection,
    *,
    batch_id: int,
    full_batch_id: int,
    detail: dict[str, Any],
) -> None:
    """Void/downgrade a scout batch after a contradicting full review."""
    conn.execute(
        """
        UPDATE reconcile_batches
        SET conflicted=1,
            status='conflicted',
            conflict_of_batch_id=?,
            conflict_detail_json=?
        WHERE id=?
        """,
        (full_batch_id, json.dumps(detail, ensure_ascii=False), batch_id),
    )


def insert_diff(
    conn: sqlite3.Connection,
    *,
    batch_id: int,
    pair_id: int,
    diff: dict[str, Any],
    created_at: str,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO reconcile_diffs(
            batch_id, pair_id, kind, align_key_json, left_json, right_json,
            mismatched_fields_json, severity, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (
            batch_id,
            pair_id,
            diff["kind"],
            json.dumps(diff["align_key"], ensure_ascii=False),
            json.dumps(diff["left"], ensure_ascii=False) if diff.get("left") is not None else None,
            json.dumps(diff["right"], ensure_ascii=False) if diff.get("right") is not None else None,
            json.dumps(diff.get("mismatched_fields") or [], ensure_ascii=False),
            "medium",
            created_at,
        ),
    )
    return int(cur.lastrowid)
