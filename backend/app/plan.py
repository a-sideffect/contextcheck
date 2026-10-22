"""Plan step: question and hardware in; checklist, papers and hardware comparison out.

Output matches what index_3.html needs for renderClarify(): see docs/api-contract.md.
"""
import os
from typing import List

from . import llm, sources
from .jobs import Progress
from .schemas import Checklist, HwAssess, PaperExtract, Selection

SYSTEM = ("You help an engineer or researcher check whether published findings transfer to their own project. "
          "Be literal and conservative. Never invent details. If something is not stated, say it is not stated.")

STAGES = ["Parse your project", "Search the literature", "Read hardware from each paper"]


def _hw_text(hardware: List[str]) -> str:
    return "\n".join("- " + h for h in hardware) if hardware else "(none listed)"


def extract_paper(paper: dict, text: str, dim_names: List[str]) -> PaperExtract:
    """One cached call per paper. Shared with the check step, which hits the same cache."""
    prompt = (
        "Read this paper and extract what it says. Do not compare it to anything.\n\n"
        "Return one entry in dims for each of these dimensions, using the exact names:\n"
        + "\n".join("- " + d for d in dim_names)
        + "\n\nFor every dim and quantity, quote must be copied character for character from the paper text "
          "below. If the paper does not say, use an empty string for value and quote. Never paraphrase a quote.\n"
          "quantities: every numeric threshold, cut-off or accuracy figure the paper reports.\n\n"
        "TITLE: %s\n\nPAPER TEXT:\n%s" % (paper["title"], text))
    return llm.ask("extract", prompt, PaperExtract, system=SYSTEM, tier="lite")


def build_plan(question: str, hardware: List[str], progress: Progress) -> dict:
    # 1. checklist
    progress.stage(0)
    cl = llm.ask("checklist", "USER QUESTION:\n%s\n\nUSER HARDWARE:\n%s\n\n"
                 "Build the checklist for checking whether published findings transfer to this project. "
                 "Ask clarifying questions only about things the question and hardware list leave out."
                 % (question, _hw_text(hardware)), Checklist, system=SYSTEM)
    dims = [[d.name, max(0, min(5, d.weight))] for d in cl.dimensions[:8]]
    dim_names = [d[0] for d in dims]

    # 2. search and choose
    progress.stage(1)
    try:
        found = sources.search(cl.search_queries[:3], limit=12)
    except Exception:
        raise llm.LLMError("Could not reach Europe PMC or OpenAlex. Check your connection and try again.")
    progress.stage(1, "Search the literature, %d found" % len(found))
    if not found:
        raise llm.LLMError("No papers with abstracts were found for this question.")
    listing = "\n".join("%d. [%s] %s (%s). %s" % (i + 1, "full text" if p["pmcid"] else "abstract only",
                                                  p["title"], p["year"], p["abstract"][:350])
                        for i, p in enumerate(found))
    sel = llm.ask("select", "CLAIM: %s\n\nCandidate papers:\n%s\n\nScore every paper for how useful it is for "
                  "judging this claim. Hardware does not need to match: a paper that measured the same quantity "
                  "with different hardware is just as useful. Judge by what the paper measured, not by which "
                  "device names appear in its title." % (cl.claim, listing), Selection, system=SYSTEM)
    rel = {s.n - 1: s.relevance for s in sel.scores if 1 <= s.n <= len(found)}
    # code decides: best relevance first, full text before abstract-only, search order as the tiebreak
    order = sorted(rel, key=lambda i: (-rel[i], 0 if found[i]["pmcid"] else 1, i))
    limit = int(os.getenv("MAX_PAPERS", "5"))
    chosen = [found[i] for i in order if rel[i] >= 2][:limit]
    if len(chosen) < 3:  # too few direct hits: pad with same-topic papers, but never with unrelated ones
        chosen += [found[i] for i in order if rel[i] == 1][: 3 - len(chosen)]
    if not chosen:
        raise llm.LLMError("None of the papers found were relevant enough to compare.")
    progress.stage(1, "Search the literature, %d relevant of %d" % (len(chosen), len(found)))

    # 3. read each paper and compare hardware
    papers = {}
    for n, p in enumerate(chosen, 1):
        progress.stage(2, "Read hardware from each paper (%d of %d)" % (n, len(chosen)))
        got = sources.get_text(p)
        ex = extract_paper(p, got["text"], dim_names)
        if hardware:
            a = llm.ask("hardware", "PAPER INSTRUMENT: %s\nPAPER SUMMARY: %s\n\nUSER HARDWARE:\n%s\n\n"
                        "Can the user's hardware stand in for what the paper used, to reproduce what the paper "
                        "measured? Use \"yes\" only if the same quantity can be measured."
                        % (ex.hardware_name, ex.summary, _hw_text(hardware)), HwAssess, system=SYSTEM, tier="lite")
            assess = {"v": a.v, "mine": a.mine, "why": a.why,
                      "ask": [a.ask_q, None, a.ask_ph or "e.g. a short answer"] if a.ask_q else None}
        else:
            assess = {"v": "unknown", "mine": "", "why": "Attach your hardware to assess this.", "ask": None}
        if p["journal"]:
            src = "%s, DOI %s" % (p["journal"], p["doi"]) if p["doi"] else p["journal"]
        else:
            src = "DOI %s" % p["doi"] if p["doi"] else p["title"]
        papers[p["id"]] = {"short": p["short"], "src": src, "summary": ex.summary,
                           "hw": {"name": ex.hardware_name, "assess": assess},
                           "title": p["title"], "doi": p["doi"], "text_source": got["text_source"]}

    progress.stage(2, "Read hardware from each paper")
    return {
        "task": {"name": cl.task_name, "domain": "live", "claim": cl.claim, "goal": cl.goal,
                 "ref": [d.project_value for d in cl.dimensions[:8]],
                 "extra": [[e.name, e.why, e.checked] for e in cl.extra_hardware],
                 "papers": [p["id"] for p in chosen], "lead": "", "actions": [], "gaps": []},
        "dims": dims,
        "questions": [{"id": q.id, "q": q.q, "why": q.why, "ph": q.ph} for q in cl.questions[:4]],
        "papers": papers,
    }
