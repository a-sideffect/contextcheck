# ContextCheck

**OSI Hackathon 2026**

> Does a published finding transfer to your project, and which of its features can improve it?

Papers report results from specific populations, devices and protocols. A threshold that works in one setting can fail in another, and it is easy to adopt it without noticing. ContextCheck takes a claim and a project profile, then shows how well the evidence transfers and what is safe to adopt.

## What it does

Given a claim and a project profile, ContextCheck reports:

1. **Closeness** of each paper to your project, per dimension. The score is computed by code from adjustable weights.
2. **Comparability** of each quantity across methods, labelled one of:
   - Direct
   - Convertible
   - Needs local calibration
   - Not comparable
3. **Ranked feature transfer.** An unvalidated or non-comparable quantity can never be ranked **Adopt**.

## Case study

Our dialysis early-warning monitor for intradialytic hypotension (IDH). Its PI, HRV, dPVi and RBV thresholds come from different populations and devices, which makes it a good test of whether a threshold really carries over.

## Run it

No build step and no dependencies. Open `index.html` in a browser:

```bash
start index.html      # Windows
open index.html       # macOS
xdg-open index.html   # Linux
```

Fonts load from Google Fonts, so the page looks best with an internet connection. It falls back to system fonts offline.

## Repository layout

| File | Purpose |
| --- | --- |
| `index.html` | The demo UI. A single self-contained file. |
| `README.md` | This file. |

## Status and limitations

- The UI runs on **preset demo data**.
- Evidence lines are **paraphrased from project notes**, not verified quotes.
- The live pipeline (OpenAlex search and quote-verified extraction) is built separately and **has not yet been run against the real API**.
- The closeness score is a **heuristic**, not a validated measure.
- The TiO2 entries are **placeholders**.

## Team

OSI Hackathon 2026. Add team member names here.

## License

No license has been chosen yet. Add a `LICENSE` file (for example MIT) before sharing the code for reuse.

## Run with Docker

```bash
cp .env.example .env     # then add your keys
docker compose up --build
```

Open http://localhost:8000. Check http://localhost:8000/api/health to see which keys are set.

## Run without Docker

```bash
python -m venv .venv
.venv/Scripts/pip install -r backend/requirements.txt
.venv/Scripts/python -m uvicorn app.main:app --app-dir backend --reload --port 8000
```
