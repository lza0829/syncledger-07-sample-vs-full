"""Deterministic, reproducible sampling for reconciliation scouting batches.

A sample batch is a *scout* (摸底), never a clearance. Selection is driven by
a SHA-256 score over (seed, composite alignment key) so that the same seed on
the same fixture snapshot selects exactly the same keys — reruns are stable.
"""

from __future__ import annotations

import hashlib
import math
import uuid
from typing import Any

from app.engines.reconcile import (
    DIFF_MATCHED,
    aligned_universe,
    compare_sides,
)

MODE_FULL = "full"
MODE_SAMPLE = "sample"

# A sample batch may never be promoted to a clearance state.
SAMPLE_BATCH_STATUS = "sampled"
FULL_BATCH_STATUS = "completed"
# A later full review contradicted this sample batch; its scout verdict is void.
CONFLICTED_BATCH_STATUS = "conflicted"

VALID_MODES = (MODE_FULL, MODE_SAMPLE)


def _key_tokens(key: tuple) -> str:
    return "|".join("" if part is None else str(part) for part in key)


def key_hash(seed: str, key: tuple) -> str:
    digest = hashlib.sha256(f"{seed}‖{_key_tokens(key)}".encode("utf-8")).hexdigest()
    return digest[:16]


def sample_size_for(population: int, rate: float, cap: int) -> tuple[int, str]:
    """Explainable sample size: rate-proportional, capped, at least one key."""
    rate_based = math.ceil(population * rate)
    size = max(1, min(cap, rate_based, population)) if population else 0
    formula = (
        f"min(cap={cap}, ceil(population={population} × rate={rate:g})"
        f" = {rate_based}, population) = {size}"
    )
    return size, formula


def select_sample(
    left_rows: list[dict[str, Any]],
    right_rows: list[dict[str, Any]],
    *,
    align_keys: list[str],
    compare_fields: list[str],
    rate: float,
    cap: int,
    seed: str | None,
) -> dict[str, Any]:
    """Pick a deterministic key sample and run the alignment only over it.

    Returns sampled keys with hashes plus summary counts over the sample and
    the diff rows themselves.
    """
    if seed is None or not str(seed).strip():
        seed = uuid.uuid4().hex
    seed = str(seed)

    universe = aligned_universe(left_rows, right_rows, align_keys=align_keys)
    population = len(universe)
    size, formula = sample_size_for(population, rate, cap)

    scored = sorted(
        ((key_hash(seed, key), idx, key) for idx, key in enumerate(universe)),
        key=lambda item: (item[0], item[1]),
    )
    chosen = [(h, key) for h, _idx, key in scored[:size]]

    key_filter = [key for _h, key in chosen]
    result = compare_sides(
        left_rows,
        right_rows,
        align_keys=align_keys,
        compare_fields=compare_fields,
        key_filter=key_filter,
    )

    # Per-key classification inside the sample, including matched keys.
    diff_by_key = {
        tuple(d["align_key"][k] for k in align_keys): d["kind"]
        for d in result["diffs"]
    }
    sampled_keys = [
        {
            "align_key": {k: key[i] for i, k in enumerate(align_keys)},
            "key_hash": h,
            "verdict": diff_by_key.get(key, DIFF_MATCHED),
        }
        for h, key in chosen
    ]

    counts = dict(result["counts"])
    counts["sample_population"] = population
    counts["sample_size"] = size
    return {
        "seed": seed,
        "rate": rate,
        "cap": cap,
        "population": population,
        "sample_size": size,
        "size_formula": formula,
        "sampled_keys": sampled_keys,
        "key_filter": key_filter,
        "counts": counts,
        "diffs": result["diffs"],
    }
