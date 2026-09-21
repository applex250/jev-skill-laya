# Laya adapter notes

This installation of `jev-skill` is **adapted**: the default provider is the
local Laya decision service instead of OpenRouter/TypeSafe Jev.

- **Provenance:** adapted from `wuyoscar/jev-skill` **v0.2.0** (commit
  `82c0105`, tag verified) on 2026-09-21. Only `jev/scripts/jev.py` and the
  SKILL.md files differ from upstream; `--provider openrouter|typesafe`
  behavior is unchanged for those routes.
- **Service:** `http://172.27.116.56:8000` — campus LAN only, HTTP, no API key
  (the server's optional key is not enabled). Swagger docs: `/docs`, health:
  `/health`. Override the endpoint with the `LAYA_URL` environment variable.

## What the CLI changes

| Aspect | Upstream (Jev) | This install (Laya) |
|---|---|---|
| Default `--provider` | `openrouter` | `laya` |
| Endpoint | `openrouter.ai/api/alpha/decisions` / `api.typesafe.ai/v1/systemone` | `http://172.27.116.56:8000/v1/predict` |
| Auth | `OPENROUTER_API_KEY` / `TYPESAFE_API_KEY` | none |
| Default model | `typesafe/jev-1.13` | `multilingual` |
| Response shape | `answers` at top level | wrapped in `result` (unwrapped by the script) |
| Batch | one request per invocation | `state` may be a list (≤200 records); report gains `items` |
| Report labels | `mode: jev_api`, `jev_called: true` | `mode: laya_api`, `jev_called: false`, `laya_called: true`, `backend: laya-rl-agent` |

Request JSON is the native `state`/`questions` format unchanged: every question
still needs `instructions`; `choice` criteria stay a label→description object,
`score` criteria stay an ordered list. Bundled example assets keep their
OpenRouter model IDs — the script maps any non-Laya model to `multilingual`
automatically (`--model english|multilingual|typed-decisions` to override).

## Choosing a Laya variant

From the service README, confirmed by spot checks on 2026-09-21:

- **`multilingual`** (default) — Chinese and mixed-language input, department
  classification (README: 5/6 accuracy, 6.3 ms).
- **`typed-decisions`** — best-calibrated `score` answers; README thresholds:
  score > 1.4 ≈ critical, < 0.9 ≈ not urgent. Use for urgency/rubric scoring.
- **`english`** — English general purpose.

Observed latency: single ≈ 13–31 ms, batch ≈ 2–7.5 ms per record, 10
concurrent singles ≈ 0.22 s server-side.

## Calibration caveats

- Probabilities come from `laya-rl-agent`, **not** TypeSafe Jev; they have not
  been calibrated to Jev's published bands. Keep the review thresholds
  (`--min-probability 0.8 --min-margin 0.15`) as guardrails and treat
  `needs_review` as an abstention.
- Spot check: `multilingual` judged a benign classroom-inquiry message as
  technical 0.68 / urgency 1.72, but with confidence 0.10 — low provider
  `confidence` correlates with wrong calls. Surface uncertain cases instead of
  auto-acting on them.
- A `noul` question type is advertised by the service; if its answer shape ever
  fails `build_report`, inspect the raw `response` field in the report before
  filing it as an error.

## Honesty rules carried over

Laya output must not be presented as "Jev" or as carrying Jev's calibration.
The report says `laya_api` / `laya_called: true` / `backend` for exactly this
reason. Selection is never permission to act; host permissions and
deterministic checks still apply.
