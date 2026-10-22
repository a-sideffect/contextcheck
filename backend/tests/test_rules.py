"""Offline checks, no API calls. Run from the repo root:
    .venv/Scripts/python backend/tests/test_rules.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.rules import cap, classify_qty, rank, score, to_ui_paper, verify_quote  # noqa: E402
from app.schemas import PaperExtract, PaperJudge  # noqa: E402

TEXT = ("We enrolled 36 critically ill adults with acute kidney injury during their first intermittent "
        "hemodialysis ses-\nsion. Perfusion index was measured with the Masimo Radical-7 monitor.")

# quote check: exact, line-break hyphenation, and a made-up quote
assert verify_quote("36 critically ill adults with acute kidney injury", TEXT)
assert verify_quote("first intermittent hemodialysis session", TEXT)
assert not verify_quote("52 outpatients on maintenance dialysis at home", TEXT)

# scoring matches the UI: unknown is left out of the score and lowers confidence
assert score(["match", "differs", "unknown", "partial"], [3, 2, 3, 1]) == {"s": 58, "c": 67, "unk": 1}

# comparability and cap rules
assert classify_qty([], [], True, False) == "direct"
assert classify_qty(["instrument"], [], True, False) == "local"
assert classify_qty(["instrument"], [], True, True) == "conv"
assert classify_qty([], ["site"], True, False) == "local"
assert classify_qty([], [], False, False) == "not"
assert cap("adopt", "not") == "no"
assert cap("adopt", "local") == "test"
assert cap("adopt", "direct", validated=False) == "test"   # unvalidated can never be Adopt
assert cap("adopt", None) == "adopt"                        # a method with no quantity behind it
assert abs(rank(3, 0.5, 0.35) - 0.525) < 1e-9

# adapter: shapes the UI reads
ex = PaperExtract.model_validate({
    "summary": "36 ICU adults on first HD session; Masimo Radical-7.", "hardware_name": "Masimo Radical-7",
    "dims": [{"dimension": "Population", "value": "ICU adults with AKI",
              "quote": "36 critically ill adults with acute kidney injury"},
             {"dimension": "Outcome definition", "value": "norepinephrine", "quote": "this sentence is invented"}],
    "quantities": [{"name": "PI 1.8", "quote": ""}]})
jd = PaperJudge.model_validate({
    "dims": [{"dimension": "Population", "state": "differs", "note": "ICU, not maintenance HD"},
             {"dimension": "Outcome definition", "state": "differs", "note": "Different IDH definition"}],
    "quantities": [{"name": "PI 1.8", "broken_on": ["instrument"], "unknown_axes": [], "producible": True,
                    "has_conversion": False, "validated": False, "note": "Relative ratio"}],
    "features": [{"name": "PI as predictor", "hw_feasible": "needs change", "hw_note": "Different scale",
                  "evidence_note": "n=36", "benefit": 3, "feasibility": 0.5, "evidence_strength": 0.35,
                  "effort": "Medium", "base_verdict": "test", "quantity": "PI 1.8"}]})
p = to_ui_paper("Mostafa 2019", "BMC Anesthesiology", ex, jd,
                ["Population", "Sensor", "Outcome definition"], TEXT)
assert p["dims"][0][0] == "differs"                      # verified quote keeps its state
assert p["dims"][1][0] == "unknown"                      # dimension the paper never covered
assert p["dims"][2][0] == "unknown" and "not found" in p["dims"][2][1]   # invented quote is dropped
assert p["qty"][0][1] == "local"
f = p["feat"][0]
assert len(f) == 11 and f[9] == "PI 1.8" and f[10] is False
print("all checks passed")
