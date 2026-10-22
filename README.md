# ContextCheck

**OSI Hackathon 2026**

> Does a published finding transfer to your project, and which of its features can improve it?

Papers report results from specific populations, devices and protocols. A threshold that works in one setting can fail in another, and it is easy to adopt it without noticing. ContextCheck takes a claim and your project setup, then shows how well each paper's evidence transfers and what is safe to adopt.

## What it does

Given a claim and a project profile, ContextCheck:

1. **Finds papers.** It searches Europe PMC and OpenAlex, scores each result for relevance, and prefers papers with open full text.
2. **Extracts conditions with quotes.** An LLM reads each paper and returns every condition (population, instrument, outcome definition and so on) with a verbatim quote.
3. **Verifies the quotes.** Plain code checks each quote against the paper text. A condition without a verified quote is shown as Unknown, which blocks made-up details.
4. **Compares to your project, per dimension.** Each cell is Match, Partial, Differs or Unknown. Closeness and confidence are computed by code from adjustable weights, and Unknown cells lower confidence instead of counting as a match.
5. **Classifies each quantity.** Direct, Convertible, Needs local calibration or Not comparable, set by rule rather than by the LLM.
6. **Ranks features to transfer.** An unvalidated or non-comparable quantity can never be ranked **Adopt**.
7. **Reports the gaps.** The lead says "Not enough evidence" when confidence is low, and lists what no paper in the set covers.

## Case study

Our dialysis early-warning monitor for intradialytic hypotension (IDH). Its PI, HRV, dPVi and RBV thresholds come from different populations and devices: one from 36 critically ill ICU patients, one from a single-region cohort, one from a machine-learning target never tested against blood pressure. ContextCheck checks whether each threshold really carries over to a low-cost finger PPG sensor.

## Run it

You need Python 3.9 or newer and a free [Gemini API key](https://aistudio.google.com).

```bash
python -m venv .venv
.venv/Scripts/pip install -r backend/requirements.txt
cp .env.example .env        # then put your GEMINI_API_KEY in .env
.venv/Scripts/python -m uvicorn app.main:app --app-dir backend --reload --port 8000
```

Open http://localhost:8000. On macOS or Linux use `.venv/bin/` instead of `.venv/Scripts/`.

Check http://localhost:8000/api/health to see which keys are loaded. Never commit `.env`; it is already in `.gitignore`.

### Docker (optional)

```bash
cp .env.example .env
docker compose up --build
```

The Docker setup has not been run yet.

### Demo mode and live mode

- The two questions from our presentation (resting heart rate on a MAX30102, and the RBV 6.5 percent per hour threshold) replay canned results instantly.
- Any other question runs the **live pipeline**: it searches, reads and compares real papers. This takes about 30 to 60 seconds.
- Add `?live` to the address to run live for every question, or `?demo` for canned data only.
- If a live run fails, the page falls back to the canned data and says so.
- Opening `index_3.html` directly as a file also works, in demo mode only.

### Free tier limits

Gemini's free tier limits requests per model per day, and sometimes returns "high demand" errors. The backend caches every answer on disk, caps daily calls (`GEMINI_DAILY_CAP`), and falls back to the lite model on overload or quota errors. Questions you have already run are served from the cache and cost nothing.

## Evaluation

`eval/` scores the tool against papers you check by hand, with the two metrics from our target: extraction accuracy and mismatch recall.

```bash
.venv/Scripts/python eval/eval.py template --case hr   # fetch papers, write a blank labels.json
# open eval/cases/hr/labels.json and fill in gold_state for each dimension, from the paper itself
.venv/Scripts/python eval/eval.py run --case hr        # writes eval/cases/hr/results.md
```

Labels are blind: the template does not show the tool's guesses, so they don't anchor your judgement. Add more DOIs to `eval/cases/<case>/papers.txt`, or copy a case folder to start a new one. Aim for 10 to 20 papers across the cases.

Offline tests for the rules and metrics (no API calls):

```bash
.venv/Scripts/python backend/tests/test_rules.py
.venv/Scripts/python backend/tests/test_eval.py
```

## Repository layout

| Path | Purpose |
| --- | --- |
| `index_3.html` | The UI. Single file, no build step. |
| `index.html` | The earlier demo-only UI. |
| `backend/app/llm.py` | Gemini wrapper: cache, daily cap, throttle, retry, model fallback. |
| `backend/app/plan.py`, `check.py` | The pipeline: plan (search and read), then check (compare and report). |
| `backend/app/rules.py` | Rules kept in code: quote verification, scoring, quantity class, Adopt cap. |
| `backend/app/sources.py` | Europe PMC and OpenAlex search, full-text fetch. |
| `eval/` | Hand-checked evaluation: cases, labels, metrics, runner. |
| `docs/api-contract.md` | The data shapes shared by the UI and the backend. |

## Status and limitations

- Live results are only as good as the papers found. Many papers are available as abstract only, which leaves dimensions Unknown and lowers confidence.
- Demo-mode evidence lines are **paraphrased from project notes**, not verified quotes. Live mode shows verified quotes.
- The closeness score is a **heuristic**, not a validated measure.
- The TiO2 entries in demo mode are **placeholders**.
- The evaluation machinery is built, but the hand-checked results are not in yet.

## Team

Justus Tan, Darrell Ang, Isaac Hau and Rathod Siddharth.

## License

[MIT](LICENSE)
