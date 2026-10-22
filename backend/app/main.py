import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import List

from . import jobs, llm, plan

# Local runs read .env from the repo root; in Docker, compose injects it.
ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

app = FastAPI(title="ContextCheck backend")

# Docker copies the UI to static/index.html; locally it is index_3.html at the repo root.
UI_CANDIDATES = [Path("static/index.html"), ROOT / "index_3.html"]


@app.get("/api/health")
def health():
    """Reports which keys are configured, never their values."""
    return {
        "ok": True,
        "gemini_key": bool(os.getenv("GEMINI_API_KEY")),
        "groq_key": bool(os.getenv("GROQ_API_KEY")),
        "openalex_key": bool(os.getenv("OPENALEX_API_KEY")),
    }


class Ping(BaseModel):
    ok: bool
    echo: str


@app.get("/api/llm-usage")
def llm_usage():
    return llm.usage()


@app.get("/api/llm-test")
def llm_test():
    """One tiny structured call. Call twice: the second must come from cache and spend no quota."""
    try:
        out = llm.ask("test", "Return ok=true and echo the single word ready.", Ping, tier="lite")
    except llm.LLMError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {"result": out.model_dump(), "usage": llm.usage()}


class PlanReq(BaseModel):
    question: str
    hardware: List[str] = []


@app.post("/api/plan")
def api_plan(req: PlanReq):
    q = req.question.strip()
    if not q:
        raise HTTPException(status_code=400, detail="Question is empty")
    if not os.getenv("GEMINI_API_KEY"):
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY is not set in .env")
    hw = [h.strip() for h in req.hardware if h.strip()][:60]
    jid = jobs.start(plan.STAGES, lambda pr: plan.build_plan(q, hw, pr))
    return {"job": jid}


@app.get("/api/jobs/{jid}")
def api_job(jid: str):
    j = jobs.get(jid)
    if not j:
        raise HTTPException(status_code=404, detail="Unknown job")
    return j


# Serving the UI from the same origin means no CORS setup is needed.
@app.get("/")
def index():
    for p in UI_CANDIDATES:
        if p.exists():
            return FileResponse(p)
    return JSONResponse({"error": "UI file not found"}, status_code=404)
