"""In-memory background jobs. The UI polls GET /api/jobs/{id} so progress ticks on real stages
and a slow free-tier call never runs into a request timeout.
"""
import threading
import traceback
import uuid
from typing import Any, Callable, Dict, List

from . import llm

_jobs: Dict[str, dict] = {}


class Progress:
    def __init__(self, job: dict):
        self._job = job

    def stage(self, index: int, label: str = "") -> None:
        self._job["stage"] = index
        if label:
            self._job["stages"][index] = label


def start(stages: List[str], fn: Callable[[Progress], Any]) -> str:
    jid = uuid.uuid4().hex[:12]
    job = {"id": jid, "stages": list(stages), "stage": 0, "done": False, "error": "", "result": None}
    _jobs[jid] = job

    def run():
        try:
            job["result"] = fn(Progress(job))
        except llm.LLMError as e:  # messages from the wrapper are written for the user
            job["error"] = str(e)
        except Exception:
            traceback.print_exc()
            job["error"] = "Something went wrong on the server. Check its log."
        job["done"] = True

    threading.Thread(target=run, daemon=True).start()
    return jid


def get(jid: str) -> dict:
    return _jobs.get(jid)
