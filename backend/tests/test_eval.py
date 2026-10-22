"""Offline checks for the evaluation metrics. Run from the repo root:
    .venv/Scripts/python backend/tests/test_eval.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "eval"))
import metrics  # noqa: E402


def row(gold, pred, paper="A"):
    return {"paper": paper, "dimension": "d", "gold": gold, "pred": pred}


rows = [row("differs", "differs"), row("differs", "partial"), row("differs", "match"),
        row("match", "match"), row("match", "differs"), row("unknown", "unknown"),
        row("unknown", "match", "B"), row("partial", "partial", "B")]
m = metrics.aggregate(rows)
assert m["dimensions_labelled"] == 8
assert m["state_accuracy"] == 0.5                     # 4 of 8 equal
assert m["mismatch_recall"] == 0.333                   # 1 of 3 real mismatches flagged Differs
assert m["mismatch_recall_lenient"] == 0.667           # Partial counted as flagged
assert m["mismatch_precision"] == 0.5                  # 2 predicted Differs, 1 real
assert m["false_match_rate"] == 0.333                  # 1 of 3 real mismatches shown as Match
assert m["unknown_agreement"] == 0.5
assert m["confusion"]["differs>match"] == 1
assert metrics.by_paper(rows) == {"A": 0.5, "B": 0.5}
assert metrics.quote_validity([True, True, False, True]) == {"quotes": 4, "verbatim_rate": 0.75}
assert metrics.aggregate([])["state_accuracy"] is None   # no labels: n/a, not a crash
print("eval metric checks passed")
