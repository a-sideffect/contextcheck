# UI and backend contract

`index_3.html` renders three kinds of data. The backend must return exactly these shapes, so the UI's renderers (`renderClarify`, `renderResults`, `renderDetail`) work unchanged. All names below are the UI's own.

## Shapes the UI reads

| UI global | Shape | Produced by |
| --- | --- | --- |
| `DIMS[domain]` | `[[dimension name, weight 0-5], ...]` | plan step (LLM checklist, default weights) |
| `QS[domain]` | `[{id, q, why, ph}]`, only questions still unanswered | plan step |
| `PAPERS[id]` | `{short, src, summary, hw, dims, qty, feat}` | `rules.to_ui_paper()` |
| `TASKS[k]` | `{name, domain, papers[], ref[], claim, goal, extra[[name, why, checked]], lead, actions[], gaps[]}` | plan and report steps |

Inside a paper:

- `dims[i] = [state, note, quote]`. `state` is `match | partial | differs | unknown`, in the same order as `DIMS`. Index 2 (the verbatim quote) is new and optional for the UI.
- `qty[i] = [name, class, brokenOn, note, quote]`. `class` is `direct | conv | local | not`, set by `rules.classify_qty`, never by the LLM.
- `feat[i] = [name, hwFeasible, hwNote, evidenceNote, benefit, feasibility, evidence, effort, baseVerdict, quantityName|null, validated]`. Index 10 (`validated`) is new.

## Endpoints

Built: `POST /api/plan`, `GET /api/jobs/{id}`, `GET /api/llm-usage`, `GET /api/llm-test`. `POST /api/check` (built, returns `PAPERS` entries plus lead, actions and gaps).

| Step in the UI | Endpoint | Returns |
| --- | --- | --- |
| Send | `POST /api/plan` with `{question, hardware[]}` | `{job}` then the plan: `DIMS`, `QS`, `TASKS` entry, papers with `hw.assess` |
| Run check | `POST /api/check` with `{plan, inputs}` where `inputs` is what `collect()` already builds | `{job}` then `PAPERS` entries, `lead`, `actions`, `gaps` |
| Progress | `GET /api/jobs/{id}` | `{stage, stages[], done, result, error}` |
| Debug | `GET /api/llm-usage`, `GET /api/llm-test` | built, working |

Jobs run in the background and the UI polls, so the progress steps tick on real stages and a slow free-tier call never hits a request timeout.

## Changes needed in `index_3.html`

1. `detect(q)` and the "demo mode only" error go away in live mode. `send()` calls `/api/plan` instead.
2. `DIMS`, `QS`, `PAPERS`, `TASKS` are filled from the API response. Keep the preset data behind a `?demo` switch and as the fallback when the backend is unreachable.
3. `assess(id)` reads `PAPERS[id].hw.assess` (`{v, mine, why, ask}`) computed by the backend. The regex fields (`rx`, `ask[1]`) cannot be sent as JSON.
4. `animate()` takes its labels and ticks from `/api/jobs` stages instead of a 460 ms timer.
5. `cap(base, cls)` takes the `validated` flag (`feat[10]`), matching `rules.cap`.
6. `renderDetail()` shows the verbatim quote under each dimension and quantity.

## Rules that stay in code

- A dimension with no verified quote is forced to Unknown (`rules.settle_state`).
- Comparability class, scoring, ranking and the Adopt cap (`rules.classify_qty`, `score`, `cap`, `rank`).
- A feature can never be Adopt when its quantity is Not comparable, needs local calibration, or is unvalidated.

## Free-tier guards (`llm.py`)

Disk cache by hash of model, prompt and schema. Daily call cap (`GEMINI_DAILY_CAP`, resets midnight Pacific). Minimum gap between calls (`GEMINI_MIN_INTERVAL`). Retry on 429 and 5xx. No billing is ever enabled.
