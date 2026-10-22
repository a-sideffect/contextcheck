"""Rules that must live in code, never in the LLM, plus the adapter to the UI's data shapes.

The functions score(), cap() and rank() mirror the ones in index_3.html so both sides agree.
"""
import re
import unicodedata
from typing import Dict, List, Optional

VAL = {"match": 1, "partial": 0.5, "differs": 0}
CLASSES = ("direct", "conv", "local", "not")


# ---- quote verification: the guard against made-up details ----
def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    s = re.sub(r"[‐-―−]", "-", s)          # unicode dashes and minus
    s = re.sub(r"[‘’“”]", "'", s)      # curly quotes
    s = re.sub(r"-\s*\n\s*", "", s)                        # words hyphenated across lines
    return re.sub(r"\s+", " ", s).strip()


def verify_quote(quote: str, source: str) -> bool:
    """True only if the quote appears in the source text, ignoring spacing and punctuation style."""
    q = _norm(quote)
    if len(q) < 12:  # too short to be evidence
        return False
    s = _norm(source)
    if q in s:
        return True
    strip = lambda t: re.sub(r"[^a-z0-9]", "", t)          # tolerate odd spacing from PDF text
    return strip(q) in strip(s)


def settle_state(state: str, quote: str, source: str) -> (str, str):
    """A claim without a verified quote becomes unknown. Returns (state, note_suffix)."""
    if state == "unknown":
        return "unknown", ""
    if not quote:
        return "unknown", " No supporting quote, so left Unknown."
    if not verify_quote(quote, source):
        return "unknown", " Quote not found in the paper text, so left Unknown."
    return state, ""


# ---- scoring, same maths as the UI ----
def score(states: List[str], weights: List[int]) -> Dict[str, int]:
    num = den = allw = 0
    for st, w in zip(states, weights):
        allw += w
        if st != "unknown":
            den += w
            num += w * VAL[st]
    return {"s": round(num / den * 100) if den else 0,
            "c": round(den / allw * 100) if allw else 0,
            "unk": sum(1 for st in states if st == "unknown")}


def classify_qty(broken_on: List[str], unknown_axes: List[str], producible: bool,
                 has_conversion: bool) -> str:
    """Comparability class by rule. A differing axis drops it below Direct; unknown axes cap it."""
    if not producible:
        return "not"
    if broken_on:
        return "conv" if has_conversion else "local"
    if unknown_axes:
        return "local"
    return "direct"


def cap(base: str, cls: Optional[str], validated: bool = True) -> str:
    """A feature can never be Adopt if its quantity is Not comparable, needs local calibration, or is unvalidated."""
    if cls == "not":
        return "no"
    if base == "adopt" and (cls == "local" or (cls is not None and not validated)):
        return "test"
    return base


def rank(benefit: float, feasibility: float, evidence: float) -> float:
    return benefit * feasibility * evidence


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


# ---- adapter: LLM output -> the exact tuples index_3.html reads ----
def to_ui_paper(short: str, src: str, extract, judge, dimensions: List[str], source_text: str) -> dict:
    """Build one PAPERS entry. dimensions is the ordered dimension list of the plan (DIMS[domain] names)."""
    quotes = {d.dimension: d.quote for d in extract.dims}
    judged = {d.dimension: d for d in judge.dims}
    dims = []
    for name in dimensions:
        j = judged.get(name)
        if j is None:
            dims.append(["unknown", "Not extracted from this paper.", ""])
            continue
        st, why = settle_state(j.state, quotes.get(name, ""), source_text)
        dims.append([st, j.note + why, quotes.get(name, "") if st != "unknown" else ""])

    qty_quotes = {q.name: q.quote for q in extract.quantities}
    qty, cls_of, validated_of = [], {}, {}
    for q in judge.quantities:
        cls = classify_qty(q.broken_on, q.unknown_axes, q.producible, q.has_conversion)
        cls_of[q.name], validated_of[q.name] = cls, q.validated
        broken = " and ".join(a.capitalize() for a in q.broken_on) or "None"
        qty.append([q.name, cls, broken, q.note, qty_quotes.get(q.name, "")])

    feat = []
    for f in judge.features:
        feat.append([f.name, f.hw_feasible, f.hw_note, f.evidence_note,
                     int(_clamp(f.benefit, 1, 3)), _clamp(f.feasibility, 0, 1),
                     _clamp(f.evidence_strength, 0.3, 0.6), f.effort, f.base_verdict,
                     f.quantity if f.quantity in cls_of else None,
                     validated_of.get(f.quantity, True)])
    return {"short": short, "src": src, "summary": extract.summary,
            "hw": {"name": extract.hardware_name},
            "dims": dims, "qty": qty, "feat": feat}
