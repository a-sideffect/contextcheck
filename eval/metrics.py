"""Evaluation metrics. Pure functions, no LLM calls, so they can be tested offline.

A row is one dimension of one paper: {paper, dimension, gold, pred}, where gold is the
human label and pred is what the tool shows the user (after quote verification).
"""
from collections import Counter
from typing import Dict, List, Optional

STATES = ("match", "partial", "differs", "unknown")


def _ratio(num: int, den: int) -> Optional[float]:
    return round(num / den, 3) if den else None


def aggregate(rows: List[dict]) -> Dict[str, object]:
    n = len(rows)
    gold_d = [r for r in rows if r["gold"] == "differs"]
    pred_d = [r for r in rows if r["pred"] == "differs"]
    gold_u = [r for r in rows if r["gold"] == "unknown"]
    conf = Counter((r["gold"], r["pred"]) for r in rows)
    return {
        "dimensions_labelled": n,
        # share of dimensions where the tool's state equals the human label
        "state_accuracy": _ratio(sum(r["gold"] == r["pred"] for r in rows), n),
        # of the real mismatches, how many did the tool call Differs? (lenient also counts Partial)
        "mismatch_recall": _ratio(sum(r["pred"] == "differs" for r in gold_d), len(gold_d)),
        "mismatch_recall_lenient": _ratio(sum(r["pred"] in ("differs", "partial") for r in gold_d), len(gold_d)),
        # of the mismatches the tool raised, how many were real?
        "mismatch_precision": _ratio(sum(r["gold"] == "differs" for r in pred_d), len(pred_d)),
        # the dangerous error: a real mismatch shown as a Match
        "false_match_rate": _ratio(sum(r["pred"] == "match" for r in gold_d), len(gold_d)),
        # where the paper really does not say, did the tool leave it Unknown?
        "unknown_agreement": _ratio(sum(r["pred"] == "unknown" for r in gold_u), len(gold_u)),
        "confusion": {"%s>%s" % (g, p): c for (g, p), c in sorted(conf.items())},
        "counts": {"gold_differs": len(gold_d), "pred_differs": len(pred_d), "gold_unknown": len(gold_u)},
    }


def by_paper(rows: List[dict]) -> Dict[str, Optional[float]]:
    out: Dict[str, List[dict]] = {}
    for r in rows:
        out.setdefault(r["paper"], []).append(r)
    return {k: _ratio(sum(r["gold"] == r["pred"] for r in v), len(v)) for k, v in out.items()}


def quote_validity(checks: List[bool]) -> Dict[str, Optional[float]]:
    """checks: one bool per extracted quote, True if it was found verbatim in the paper text.
    A value below 1.0 means the model produced a quote that is not in the source."""
    return {"quotes": len(checks), "verbatim_rate": _ratio(sum(checks), len(checks))}
