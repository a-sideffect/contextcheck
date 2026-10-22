"""Evaluate ContextCheck against hand-checked papers.

    python eval/eval.py template --case hr    # fetch the papers and write a blank labels.json
    python eval/eval.py run --case hr         # score the tool against your filled-in labels

Run from the repo root with the project's Python. Each paper costs about two Gemini calls
(cached after the first run), which count against the daily cap in .env.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import metrics  # noqa: E402
from app import check, llm, rules, sources  # noqa: E402
from app.plan import extract_paper  # noqa: E402


def case_dir(name: str) -> Path:
    d = Path(__file__).resolve().parent / "cases" / name
    if not d.exists():
        sys.exit("No such case: %s. Cases are the folders in eval/cases/." % name)
    return d


def cmd_template(a) -> None:
    d = case_dir(a.case)
    proj = json.loads((d / "project.json").read_text(encoding="utf-8"))
    lab_path = d / "labels.json"
    labels = json.loads(lab_path.read_text(encoding="utf-8")) if lab_path.exists() else {"papers": []}
    have = {p["doi"] for p in labels["papers"]}
    dois = [x.strip() for x in (d / "papers.txt").read_text(encoding="utf-8").splitlines()
            if x.strip() and not x.startswith("#")]
    for doi in dois:
        if doi.lower() in have:
            continue  # never overwrite labels you already filled in
        paper = sources.by_doi(doi)
        if not paper:
            print("  not found, skipped:", doi)
            continue
        got = sources.get_text(paper)
        labels["papers"].append({
            "doi": paper["doi"], "id": paper["id"], "short": paper["short"], "title": paper["title"],
            "text_source": got["text_source"],
            "dims": [{"dimension": x["name"], "gold_state": "", "gold_quote": ""} for x in proj["dimensions"]]})
        print("  added %s (%s)" % (paper["short"], got["text_source"]))
    lab_path.write_text(json.dumps(labels, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nWrote %s\nFill in gold_state for each dimension: match, partial, differs or unknown, judged\n"
          "against the project in project.json. Label from the paper itself, not from the tool's output.\n"
          "Optionally paste the sentence that supports it into gold_quote." % lab_path)


def cmd_run(a) -> None:
    d = case_dir(a.case)
    proj = json.loads((d / "project.json").read_text(encoding="utf-8"))
    labels = json.loads((d / "labels.json").read_text(encoding="utf-8"))
    names = [x["name"] for x in proj["dimensions"]]
    req = check.CheckReq(claim=proj["claim"], goal=proj.get("goal", ""), hardware=proj["hardware"],
                         dims=[[x["name"], x["weight"]] for x in proj["dimensions"]],
                         ref=[x["project_value"] for x in proj["dimensions"]], papers=[])
    rows, quote_checks, errors, skipped = [], [], [], []
    for p in labels["papers"]:
        gold = {x["dimension"]: x["gold_state"].strip().lower() for x in p["dims"] if x["gold_state"].strip()}
        bad = [v for v in gold.values() if v not in metrics.STATES]
        if bad:
            sys.exit("%s has an invalid gold_state %r. Use one of %s." % (p["short"], bad[0], metrics.STATES))
        if not gold:
            skipped.append(p["short"])
            continue
        got = sources.cached_text(p["id"])
        if not got:
            print("  text missing for %s, run the template step again" % p["short"])
            continue
        print("  scoring %s ..." % p["short"])
        try:
            ex = extract_paper({"title": p["title"]}, got["text"], names)
            judge = check._judge(req, check.PaperIn(id=p["id"], short=p["short"], title=p["title"]), ex, names)
        except llm.LLMError as e:
            print("    stopped: %s" % e)
            break
        ui = rules.to_ui_paper(p["short"], "", ex, judge, names, got["text"])  # the production code path
        quote_checks += [rules.verify_quote(q.quote, got["text"]) for q in ex.dims if q.quote]
        for i, n in enumerate(names):
            if n in gold:
                row = {"paper": p["short"], "dimension": n, "gold": gold[n], "pred": ui["dims"][i][0],
                       "text_source": p["text_source"], "note": ui["dims"][i][1]}
                rows.append(row)
                if row["gold"] != row["pred"]:
                    errors.append(row)
    if not rows:
        sys.exit("No labelled dimensions found. Fill in gold_state in %s first." % (d / "labels.json"))

    full = [r for r in rows if r["text_source"] == "full text"]
    res = {"case": a.case, "papers": len({r["paper"] for r in rows}), "overall": metrics.aggregate(rows),
           "full_text_only": metrics.aggregate(full) if full else None,
           "per_paper_accuracy": metrics.by_paper(rows), "quotes": metrics.quote_validity(quote_checks)}
    (d / "results.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    (d / "results.md").write_text(render(res, errors, skipped), encoding="utf-8")
    print("\n" + render(res, errors, skipped))


def pct(x) -> str:
    return "n/a" if x is None else "%d%%" % round(x * 100)


def render(res, errors, skipped) -> str:
    o = res["overall"]
    L = ["# Evaluation: %s" % res["case"], "",
         "%d papers, %d dimensions labelled by hand. Small samples are noisy, so read these as indicative." %
         (res["papers"], o["dimensions_labelled"]), "",
         "| Metric | Result |", "| --- | --- |",
         "| State accuracy (tool equals your label) | %s |" % pct(o["state_accuracy"]),
         "| Mismatch recall (real Differs the tool flagged Differs) | %s of %d |" % (pct(o["mismatch_recall"]), o["counts"]["gold_differs"]),
         "| Mismatch recall, counting Partial as flagged | %s |" % pct(o["mismatch_recall_lenient"]),
         "| Mismatch precision (flagged Differs that were real) | %s of %d |" % (pct(o["mismatch_precision"]), o["counts"]["pred_differs"]),
         "| False match rate (real Differs shown as Match) | %s |" % pct(o["false_match_rate"]),
         "| Unknown agreement (paper silent, tool left Unknown) | %s of %d |" % (pct(o["unknown_agreement"]), o["counts"]["gold_unknown"]),
         "| Quotes found verbatim in the paper | %s of %d |" % (pct(res["quotes"]["verbatim_rate"]), res["quotes"]["quotes"]), ""]
    if res["full_text_only"]:
        f = res["full_text_only"]
        L += ["Full-text papers only: accuracy %s, mismatch recall %s (%d dimensions)." %
              (pct(f["state_accuracy"]), pct(f["mismatch_recall"]), f["dimensions_labelled"]), ""]
    L += ["## Per paper (state accuracy)", ""] + ["- %s: %s" % (k, pct(v)) for k, v in res["per_paper_accuracy"].items()]
    L += ["", "## Confusion (your label > tool)", ""] + ["- %s: %d" % (k, v) for k, v in o["confusion"].items()]
    if errors:
        L += ["", "## Where the tool disagreed with you", ""]
        L += ["- %s, %s: you said %s, tool said %s. Tool note: %s" %
              (e["paper"], e["dimension"], e["gold"], e["pred"], e["note"]) for e in errors]
    if skipped:
        L += ["", "Not scored, no labels yet: " + ", ".join(skipped)]
    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["template", "run"])
    ap.add_argument("--case", required=True)
    a = ap.parse_args()
    {"template": cmd_template, "run": cmd_run}[a.command](a)
