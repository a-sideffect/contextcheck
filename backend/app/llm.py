"""Gemini wrapper. Every LLM step in the pipeline goes through ask().

Order of work per call: cache -> daily budget -> throttle -> Gemini -> validate -> cache.
Free tier only: the daily cap stops us before Google does, and no billing is ever enabled.
"""
import hashlib
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Type, TypeVar
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _cache_dir() -> Path:
    d = Path(os.getenv("CACHE_DIR", Path.cwd() / "cache"))
    (d / "llm").mkdir(parents=True, exist_ok=True)
    return d


def _model(tier: str) -> str:
    main = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    return os.getenv("GEMINI_MODEL_LITE", "gemini-3.5-flash-lite") if tier == "lite" else main


class LLMError(Exception):
    """Base class. The message is safe to show in the UI."""


class BudgetExceeded(LLMError):
    pass


class QuotaExhausted(LLMError):
    pass


class Unavailable(LLMError):
    """Gemini is overloaded or rate-limiting. ask() falls back to the lite model once."""


_lock = threading.Lock()
_last_call = 0.0


def _today() -> str:
    # Gemini daily quotas reset at midnight Pacific.
    return datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")


def usage() -> dict:
    cap = int(os.getenv("GEMINI_DAILY_CAP", "100"))
    p = _cache_dir() / "usage.json"
    calls = 0
    try:
        d = json.loads(p.read_text())
        if d.get("date") == _today():
            calls = d.get("calls", 0)
    except (OSError, ValueError):
        pass
    return {"date": _today(), "calls": calls, "cap": cap, "left": max(cap - calls, 0)}


def _count_call() -> None:
    u = usage()
    (_cache_dir() / "usage.json").write_text(json.dumps({"date": u["date"], "calls": u["calls"] + 1}))


def _log(row: dict) -> None:
    with open(_cache_dir() / "calls.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def _key(model: str, system: str, prompt: str, schema: dict) -> str:
    raw = json.dumps([model, system, prompt, schema], sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:40]


def _post(model: str, body: dict) -> dict:
    """One network call with budget, throttle and retry on 429/5xx."""
    global _last_call
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise LLMError("GEMINI_API_KEY is not set in .env")
    gap = float(os.getenv("GEMINI_MIN_INTERVAL", "2"))
    delays = [5, 15]
    for attempt in range(len(delays) + 1):
        if usage()["left"] <= 0:
            raise BudgetExceeded("Daily call budget reached. It resets at midnight Pacific time.")
        with _lock:  # serialise calls so the throttle holds across threads
            wait = gap - (time.time() - _last_call)
            if wait > 0:
                time.sleep(wait)
            _last_call = time.time()
            _count_call()
        try:
            r = httpx.post(API.format(model=model), json=body, timeout=60,
                           headers={"x-goog-api-key": api_key})
        except httpx.HTTPError as e:
            raise LLMError("Could not reach Gemini: %s" % type(e).__name__)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429 and "PerDay" in r.text:
            raise QuotaExhausted("Gemini's free daily quota is used up. Try again after midnight Pacific.")
        if r.status_code in (429, 500, 503) and attempt < len(delays):
            time.sleep(delays[attempt])
            continue
        msg = r.text[:200].replace(api_key, "***")
        if r.status_code in (429, 500, 503):
            raise Unavailable("Gemini is busy right now (%s). Try again in a minute." % r.status_code)
        raise LLMError("Gemini returned %s: %s" % (r.status_code, msg))
    raise Unavailable("Gemini kept rate-limiting. Try again in a minute.")


def _text(resp: dict) -> str:
    parts = (resp.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


def ask(task: str, prompt: str, schema: Type[T], system: str = "", tier: str = "main") -> T:
    """Run one structured LLM step. Returns a validated pydantic object.

    task:  short label for the log, e.g. "extract" or "checklist".
    tier:  "main" for reading papers, "lite" for short steps. Both default to the same model.
    """
    model = _model(tier)
    js = schema.model_json_schema()
    ck = _key(model, system, prompt, js)
    cpath = _cache_dir() / "llm" / (ck + ".json")
    if cpath.exists():
        try:
            out = schema.model_validate_json(cpath.read_text(encoding="utf-8"))
            _log({"t": time.time(), "task": task, "model": model, "cache": True})
            return out
        except ValidationError:
            pass  # stale cache entry from an older schema; fall through and refresh it

    def make_body(m: str) -> dict:
        cfg = {"temperature": 0, "responseMimeType": "application/json", "responseJsonSchema": js}
        if m != _model("lite"):  # thinking is what made the main model take 20 to 35 s per paper
            cfg["thinkingConfig"] = {"thinkingBudget": int(os.getenv("GEMINI_THINKING_BUDGET", "0"))}
        b = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": cfg}
        if system:
            b["systemInstruction"] = {"parts": [{"text": system}]}
        return b

    body = make_body(model)
    last_err = ""
    t0 = time.time()
    tries = 0
    while tries < 2:  # a second pass only if the first reply failed validation
        try:
            resp = _post(model, body)
        except Unavailable:
            if model == _model("lite"):
                raise
            model = _model("lite")  # overloaded: fall back to the lite model once
            body = make_body(model)
            continue
        tries += 1
        meta = resp.get("usageMetadata", {})
        try:
            out = schema.model_validate_json(_text(resp))
        except ValidationError as e:
            last_err = str(e)[:300]
            body["contents"].append({"role": "model", "parts": [{"text": _text(resp)[:2000]}]})
            body["contents"].append({"role": "user", "parts": [{"text": "That did not match the schema: %s. Return corrected JSON only." % last_err}]})
            continue
        cpath.write_text(out.model_dump_json(), encoding="utf-8")
        _log({"t": time.time(), "task": task, "model": model, "cache": False, "sec": round(time.time() - t0, 1),
              "in": meta.get("promptTokenCount"), "out": meta.get("candidatesTokenCount")})
        return out
    raise LLMError("The model's answer did not match the expected format: " + last_err)
