"""Deterministic sampling engine tests."""
from app.engines.reconcile import compare_sides
from app.engines.sampling import key_hash, sample_size_for, select_sample

ALIGN = ["k"]
FIELDS = ["v"]
LEFT = [{"k": i, "v": i} for i in range(10)]
RIGHT = [{"k": i, "v": i} for i in range(10)]


def test_sample_size_formula_is_explainable():
    size, formula = sample_size_for(population=10, rate=0.25, cap=3)
    assert size == 3  # ceil(2.5)=3, below cap
    assert "population=10" in formula and "rate=0.25" in formula and "cap=3" in formula


def test_sample_size_at_least_one_and_never_above_population():
    assert sample_size_for(10, 0.01, 25)[0] == 1
    assert sample_size_for(10, 1.0, 25)[0] == 10
    assert sample_size_for(0, 0.5, 5)[0] == 0


def test_same_seed_selects_identical_keys():
    a = select_sample(LEFT, RIGHT, align_keys=ALIGN, compare_fields=FIELDS,
                      rate=0.4, cap=25, seed="fixed-seed")
    b = select_sample(LEFT, RIGHT, align_keys=ALIGN, compare_fields=FIELDS,
                      rate=0.4, cap=25, seed="fixed-seed")
    assert a["sampled_keys"] == b["sampled_keys"]
    assert a["counts"] == b["counts"]


def test_different_seed_may_differ_but_is_also_stable():
    a = select_sample(LEFT, RIGHT, align_keys=ALIGN, compare_fields=FIELDS,
                      rate=0.3, cap=25, seed="seed-a")
    b = select_sample(LEFT, RIGHT, align_keys=ALIGN, compare_fields=FIELDS,
                      rate=0.3, cap=25, seed="seed-b")
    # both deterministic
    assert a["sampled_keys"] == select_sample(
        LEFT, RIGHT, align_keys=ALIGN, compare_fields=FIELDS,
        rate=0.3, cap=25, seed="seed-a")["sampled_keys"]
    assert {k["key_hash"] for k in a["sampled_keys"]} != {k["key_hash"] for k in b["sampled_keys"]}


def test_key_hash_is_seed_sensitive_and_stable():
    assert key_hash("s1", (1,)) == key_hash("s1", (1,))
    assert key_hash("s1", (1,)) != key_hash("s2", (1,))
    assert len(key_hash("s1", (1,))) == 16


def test_sample_only_covers_selected_keys():
    sample = select_sample(LEFT, RIGHT, align_keys=ALIGN, compare_fields=FIELDS,
                           rate=0.3, cap=2, seed="z")
    assert sample["sample_size"] == 2
    covered = {d["align_key"]["k"] for d in sample["diffs"]} | \
              {k["align_key"]["k"] for k in sample["sampled_keys"] if k["verdict"] == "matched"}
    assert covered == {k["align_key"]["k"] for k in sample["sampled_keys"]}
    full = compare_sides(LEFT, RIGHT, align_keys=ALIGN, compare_fields=FIELDS)
    assert full["counts"]["left_rows"] == 10
