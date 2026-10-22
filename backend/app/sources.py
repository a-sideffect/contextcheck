"""Literature search (Europe PMC and OpenAlex) and paper text fetching.

Both APIs work without a key. OPENALEX_API_KEY, if set, is sent to raise OpenAlex's daily budget.
Fetched text is cached on disk by paper id, so a paper is downloaded once.
"""
import hashlib
import html
import json
import os
import re
from itertools import zip_longest
from pathlib import Path
from typing import Dict, List, Optional

import httpx

EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
OPENALEX = "https://api.openalex.org/works"
MAX_TEXT = 80000  # characters passed to the LLM per paper


def _cache() -> Path:
    d = Path(os.getenv("CACHE_DIR", Path.cwd() / "cache")) / "papers"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _plain(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _paper(title, surname, year, journal, doi, pmcid, abstract, oa) -> dict:
    doi = (doi or "").replace("https://doi.org/", "").lower()
    pid = "p" + hashlib.sha1((doi or title).encode()).hexdigest()[:8]
    short = ("%s %s" % (surname, year)).strip() if surname else (_plain(title)[:24] or pid)
    return {"id": pid, "short": short, "title": _plain(title), "year": str(year or ""),
            "journal": _plain(journal), "doi": doi, "pmcid": pmcid or "",
            "abstract": _plain(abstract), "oa": bool(oa)}


def _epmc(query: str, n: int) -> List[dict]:
    r = httpx.get(EPMC + "/search", timeout=30, params={
        "query": query, "format": "json", "resultType": "core", "pageSize": n})
    r.raise_for_status()
    out = []
    for x in r.json().get("resultList", {}).get("result", []):
        # authorString is "Li J, Xu Q, ...": the surname is the first word
        surname = x["authorString"].split()[0] if x.get("authorString") else ""
        out.append(_paper(x.get("title", ""), surname, x.get("pubYear"), x.get("journalTitle") or ((x.get("journalInfo") or {}).get("journal") or {}).get("title", ""),
                          x.get("doi"), x.get("pmcid") if x.get("isOpenAccess") == "Y" else "",
                          x.get("abstractText", ""), x.get("isOpenAccess") == "Y"))
    return out


def _openalex_abstract(inv: Optional[dict]) -> str:
    if not inv:
        return ""
    words = {}
    for w, pos in inv.items():
        for p in pos:
            words[p] = w
    return " ".join(words[i] for i in sorted(words))


def _openalex(query: str, n: int) -> List[dict]:
    params = {"search": query, "per-page": n,
              "select": "id,doi,title,publication_year,primary_location,authorships,open_access,abstract_inverted_index"}
    if os.getenv("OPENALEX_API_KEY"):
        params["api_key"] = os.getenv("OPENALEX_API_KEY")
    r = httpx.get(OPENALEX, params=params, timeout=30)
    r.raise_for_status()
    out = []
    for w in r.json().get("results", []):
        auth = [a["author"]["display_name"] for a in w.get("authorships", []) if a.get("author")]
        surname = auth[0].split()[-1] if auth else ""  # "S. Muthukrishnan" -> "Muthukrishnan"
        src = ((w.get("primary_location") or {}).get("source") or {}).get("display_name", "")
        out.append(_paper(w.get("title") or "", surname, w.get("publication_year"), src, w.get("doi"),
                          "", _openalex_abstract(w.get("abstract_inverted_index")),
                          (w.get("open_access") or {}).get("is_oa")))
    return out


def search(queries: List[str], limit: int = 12, per_query: int = 8) -> List[dict]:
    """Search both indexes for every query, merge by DOI, interleave so each query is represented.

    A source that errors is skipped; if every call fails the last error is raised.
    """
    lists, err = [], None
    for q in queries:
        for fn in (_epmc, _openalex):
            try:
                lists.append(fn(q, per_query))
            except (httpx.HTTPError, ValueError) as e:
                err = e
    if not lists and err:
        raise err
    seen, merged = set(), []
    for batch in zip_longest(*lists):
        for p in batch:
            if p is None:
                continue
            key = p["doi"] or p["title"].lower()
            if key in seen or len(p["abstract"]) < 200:  # no abstract means nothing to read
                continue
            seen.add(key)
            merged.append(p)
    return merged[:limit]


def _xml_to_text(xml: str) -> str:
    xml = re.sub(r"<ref-list>.*?</ref-list>", " ", xml, flags=re.S)       # references are noise
    xml = re.sub(r"<(?:back|front)>.*?</(?:back|front)>", " ", xml, flags=re.S)
    xml = re.sub(r"</(?:p|title|caption|td|th|tr|sec)>", "\n", xml)
    text = html.unescape(re.sub(r"<[^>]+>", " ", xml))
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", text)).strip()


def get_text(paper: dict) -> Dict[str, str]:
    """Full text when Europe PMC has it open access, otherwise title plus abstract."""
    f = _cache() / (paper["id"] + ".json")
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    text, how = "", "abstract"
    if paper.get("pmcid"):
        try:
            r = httpx.get("%s/%s/fullTextXML" % (EPMC, paper["pmcid"]), timeout=60)
            if r.status_code == 200 and len(r.text) > 5000:
                text, how = _xml_to_text(r.text), "full text"
        except httpx.HTTPError:
            pass
    if not text:
        text = paper["title"] + "\n" + paper["abstract"]
    out = {"text": text[:MAX_TEXT], "text_source": how}
    f.write_text(json.dumps(out), encoding="utf-8")
    return out


def cached_text(paper_id: str) -> Optional[Dict[str, str]]:
    """Text saved by the plan step, or None if that paper was never fetched."""
    f = _cache() / (paper_id + ".json")
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
