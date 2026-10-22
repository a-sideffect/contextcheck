"""Check step: extractions in, per-dimension judgement, rules applied in code, report out.

Output feeds renderResults() in index_3.html. The LLM judges and explains; quote
verification, quantity class, scoring and the Adopt cap are applied by rules.py.
"""
from typing import List, Optional

from pydantic import BaseModel

from . import llm, rules, sources
from .jobs import Progress
from .plan import SYSTEM, extract_paper
from .schemas import PaperJudge, Report

STAGES = ["Extract with quotes", "Verify quotes", "Compare to project", "Rank features"]


class PaperIn(BaseModel):
    id: str
    short: str
    title: str
    src: str = ""
    hw_name: str = ""
    hw_v: str = "unknown"          # the user's final hardware verdict: yes | partial | no | unknown
    hw_why: str = ""
    ans: Optional[List[str]] = None  # [question, answer] if the user answered the paper's follow-up


class CheckReq(BaseModel):
    claim: str
    goal: str = ""
    hardware: List[str] = []
    dims: List[list]               # [[name, weight], ...] exactly as the plan returned them
    ref: List[str] = []            # the project's value for each dimension
    papers: List[PaperIn]
    extra: List[List[str]] = []    # hardware the user plans to add: [name, why]
    qa: List[List[str]] = []       # clarifying questions and answers


def _profile(req: CheckReq, names: List[str]) -> str:
    L = ["CLAIM: " + req.claim, "GOAL: " + (req.goal or "not stated"), "", "HARDWARE THE USER HAS:"]
    L += ["- " + h for h in req.hardware] or ["- (none listed)"]
    L += ["", "THE PROJECT'S VALUE FOR EACH DIMENSION:"]
    L += ["- %s: %s" % (n, (req.ref[i] if i < len(req.ref) and req.ref[i] else "To define")) for i, n in enumerate(names)]
    answered = [x for x in req.qa if len(x) > 1 and x[1].strip()]
    if answered:
        L += ["", "THE USER'S ANSWERS:"] + ["- %s -> %s" % (x[0], x[1]) for x in answered]
    if req.extra:
        L += ["", "HARDWARE THE USER PLANS TO ADD:"] + ["- " + x[0] for x in req.extra]
    return "\n".join(L)


def _judge(req: CheckReq, p: PaperIn, ex, names: List[str]) -> PaperJudge:
    dimtxt = "\n".join("- %s | paper says: %s | quote: %s" % (d.dimension, d.value or "not stated", d.quote or "(none)")
                       for d in ex.dims)
    qtytxt = "\n".join("- %s | quote: %s" % (q.name, q.quote or "(none)") for q in ex.quantities) or "- (none)"
    ans = ("\nUser's answer about this paper's hardware: %s -> %s" % (p.ans[0], p.ans[1])) if p.ans else ""
    prompt = (
        _profile(req, names)
        + "\n\nPAPER: %s\nINSTRUMENT: %s\nSUMMARY: %s\nHARDWARE VERDICT (user's final call): %s. %s%s\n\n"
          "WHAT THE PAPER SAYS, BY DIMENSION:\n%s\n\nQUANTITIES THE PAPER REPORTS:\n%s\n\n"
          "Judge how well this paper transfers to the project.\n"
          "- dims: one entry per dimension, exact names, in order. state is match, partial or differs by comparing "
          "the paper to the project's value. Use unknown whenever the paper's quote is (none).\n"
          "- quantities: one entry per quantity above, same names. broken_on lists axes where the paper's setting "
          "changes the quantity's meaning for this project; unknown_axes lists axes that matter but the paper "
          "does not report; producible is whether the user's hardware can produce this quantity at all.\n"
          "- features: 2 to 4 things the project could copy or adopt from this paper, each tied to a quantity "
          "when it relies on one (use null for a method or practice with no quantity behind it). Be honest: "
          "base_verdict adopt only when it clearly works with the user's hardware."
        % (p.short, p.hw_name, ex.summary, p.hw_v, p.hw_why, ans, dimtxt, qtytxt))
    return llm.ask("judge", prompt, PaperJudge, system=SYSTEM)


def build_check(req: CheckReq, progress: Progress) -> dict:
    names = [str(d[0]) for d in req.dims]
    weights = [int(d[1]) for d in req.dims]

    # 1. extract: free, the plan step already cached these
    progress.stage(0)
    texts, extracts = {}, {}
    for p in req.papers:
        got = sources.cached_text(p.id)
        if not got:
            raise llm.LLMError("The text for %s is no longer saved. Run the search again." % p.short)
        texts[p.id] = got["text"]
        extracts[p.id] = extract_paper({"title": p.title}, got["text"], names)

    # 2. verify quotes against the source text
    progress.stage(1)
    total = ok = 0
    for p in req.papers:
        for d in extracts[p.id].dims:
            if d.quote:
                total += 1
                ok += rules.verify_quote(d.quote, texts[p.id])
    progress.stage(1, "Verify quotes, %d of %d found in the papers" % (ok, total))

    # 3. compare each paper to the project
    ui = {}
    for n, p in enumerate(req.papers, 1):
        progress.stage(2, "Compare to project (%d of %d)" % (n, len(req.papers)))
        judge = _judge(req, p, extracts[p.id], names)
        ui[p.id] = rules.to_ui_paper(p.short, p.src, extracts[p.id], judge, names, texts[p.id])

    # 4. rank in code, then write the report from the capped results
    progress.stage(3)
    lines, closes, confs, abstract_only = [], [], [], 0
    for p in req.papers:
        u = ui[p.id]
        sc = rules.score([d[0] for d in u["dims"]], weights)
        cls = {q[0]: q[1] for q in u["qty"]}
        closes.append(sc["s"])
        confs.append(sc["c"])
        abstract_only += sources.cached_text(p.id)["text_source"] == "abstract"
        lines.append("%s: closeness %d at %d%% confidence, %d dimensions unknown" % (p.short, sc["s"], sc["c"], sc["unk"]))
        lines += ["  quantity %s: %s" % (q[0], q[1]) for q in u["qty"]]
        for f in u["feat"]:
            lines.append("  feature %s: %s" % (f[0], rules.cap(f[8], cls.get(f[9]), f[10])))
    n = len(req.papers)
    lines.insert(0, "OVERALL: mean confidence %d%%, %d of %d papers read from the abstract only. If mean confidence "
                    "is below 50%%, or most papers are abstract-only, start the lead with 'Not enough evidence.' "
                    "instead of Yes or No." % (round(sum(confs) / n), abstract_only, n))
    rep = llm.ask("report", _profile(req, names) + "\n\nRESULTS AFTER THE RULES WERE APPLIED:\n" + "\n".join(lines)
                  + "\n\nWrite the report. Do not contradict a feature verdict or a quantity class. "
                    "A quantity that is 'not' cannot be reproduced with the user's hardware; 'local' needs "
                    "recalibration on the user's own data.", Report, system=SYSTEM)
    return {"papers": ui, "task": {"lead": rep.lead, "actions": rep.actions[:3], "gaps": rep.gaps[:4]}}
