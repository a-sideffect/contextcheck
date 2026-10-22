"""Schemas the LLM fills in. Plain code (rules.py) turns them into the shapes index_3.html renders.

Extraction schemas hold what the paper says, with verbatim quotes.
Judge schemas hold the comparison against the user's project.
"""
from typing import List, Optional

from pydantic import BaseModel, Field
from typing_extensions import Literal

State = Literal["match", "partial", "differs", "unknown"]
Axis = Literal["instrument", "algorithm", "definition", "population", "site",
               "calibration", "method", "validation"]


# ---- step: extract (one call per paper, text in, quotes out) ----
class DimExtract(BaseModel):
    dimension: str = Field(description="Exactly one of the dimension names provided")
    value: str = Field(description="What the paper reports, in a few words. Empty if not stated")
    quote: str = Field(description="Verbatim sentence from the paper that supports value. Empty string if the paper does not say")


class QtyExtract(BaseModel):
    name: str = Field(description="The quantity with its reported value, e.g. 'PI 1.8'")
    quote: str = Field(description="Verbatim sentence from the paper. Empty string if absent")


class PaperExtract(BaseModel):
    summary: str = Field(description="Two sentences: who or what was studied, with which instrument, and the main result")
    hardware_name: str = Field(description="Instrument, sensor or method used")
    dims: List[DimExtract]
    quantities: List[QtyExtract]


# ---- step: compare (project profile + extraction in, judgement out) ----
class DimJudge(BaseModel):
    dimension: str
    state: State = Field(description="unknown only when the paper does not say")
    note: str = Field(description="One short sentence comparing the paper to the project")


class QtyJudge(BaseModel):
    name: str
    broken_on: List[Axis] = Field(description="Axes on which the paper's setting differs from the project in a way that changes this quantity's meaning")
    unknown_axes: List[Axis] = Field(description="Axes that matter for this quantity but the paper does not report")
    producible: bool = Field(description="Can the project's hardware produce this quantity at all")
    has_conversion: bool = Field(description="A documented conversion to the project's setting exists")
    validated: bool = Field(description="The paper validated this quantity on data separate from where it was derived")
    note: str


class FeatureJudge(BaseModel):
    name: str
    hw_feasible: Literal["yes", "needs change", "no"]
    hw_note: str
    evidence_note: str
    benefit: int = Field(description="1 low, 2 medium, 3 high")
    feasibility: float = Field(description="0 to 1")
    evidence_strength: float = Field(description="0.3 anecdotal to 0.6 strong, 0.35 for a single unvalidated cohort")
    effort: Literal["Low", "Medium", "High"]
    base_verdict: Literal["adopt", "test", "no"]
    quantity: Optional[str] = Field(description="Name of the quantity this feature relies on, exactly as in the quantity list, or null")


class PaperJudge(BaseModel):
    dims: List[DimJudge]
    quantities: List[QtyJudge]
    features: List[FeatureJudge]


# ---- step: plan (question and hardware in, checklist out) ----
class ChecklistDim(BaseModel):
    name: str = Field(description="Short dimension name, e.g. 'Sensor and wavelengths'")
    weight: int = Field(description="Importance for whether a finding transfers, 1 to 5")
    project_value: str = Field(description="What the user's project has for this dimension, or 'To define' if the user did not say")


class ChecklistQuestion(BaseModel):
    id: str = Field(description="Short lowercase id, no spaces")
    q: str
    why: str = Field(description="Why the answer changes the comparison")
    ph: str = Field(description="Example answer, starting 'e.g.'")


class ChecklistExtra(BaseModel):
    name: str
    why: str
    checked: bool = Field(description="True if the project very likely needs it")


class Checklist(BaseModel):
    task_name: str = Field(description="A short noun phrase naming what is being checked")
    claim: str = Field(description="The user's question restated as one testable claim")
    goal: str = Field(description="The user's improvement goal in one short sentence")
    dimensions: List[ChecklistDim] = Field(description="5 to 8 conditions that decide whether a published finding transfers")
    search_queries: List[str] = Field(description="3 literature search queries using the terms papers would use. Exactly one names the user's device, and at least two name no device or brand, only the quantity, method and setting, because the most informative papers often used different hardware")
    questions: List[ChecklistQuestion] = Field(description="At most 4 clarifying questions, only for things the question and hardware list do not already answer")
    extra_hardware: List[ChecklistExtra] = Field(description="Hardware or data the project may need to add, can be empty")


class Selection(BaseModel):
    keep: List[int] = Field(description="Numbers of the papers that directly study the claim, most relevant first")


class HwAssess(BaseModel):
    v: Literal["yes", "partial", "no", "unknown"] = Field(description="Can the user's hardware stand in for the paper's")
    mine: str = Field(description="The closest item from the user's list, or empty if none")
    why: str = Field(description="One or two sentences")
    ask_q: str = Field(description="A question only if one missing detail would change the verdict, else empty")
    ask_ph: str = Field(description="Example answer, starting 'e.g.', or empty")
