# jev-skill-laya

A fork of [wuyoscar/jev-skill](https://github.com/wuyoscar/jev-skill) **v0.2.0**
(commit `82c0105`) reworked so every skill calls **only the local Laya decision
API** (route L) — keyless, free, and staying inside the campus network.
OpenRouter/TypeSafe and simulation modes are removed; there is no provider
choice and no API key.

## Why

The upstream skills are gated on `OPENROUTER_API_KEY` / `TYPESAFE_API_KEY` and
per-call charges. This fork points them at a self-hosted **Laya** decision
service (a FastAPI + `laya-rl-agent` deployment on an RTX 5090) that answers
the same typed questions (choice / score / noul) with probabilities, at
millisecond latency and no cost — and removes every other route, so a call
can never leave the campus network or cost money.

## What changed from upstream v0.2.0

| Area | Change |
|---|---|
| `skills/jev/scripts/jev.py` | **L-only**: the campus Laya endpoint is the only destination (no `--provider`, no keys, no simulation). Unwraps the `{"ok": true, "result": ...}` envelope; a list `result` becomes a per-record `items` report. **Model auto-routes** per the benchmarked decision table below; `--model` forces one variant. Endpoint overridable via the `LAYA_URL` env var. |
| Honest labeling | Laya reports say `mode: laya_api`, `laya_called: true`, `backend: laya-rl-agent` — never presented as TypeSafe Jev calibration. |
| All 11 `SKILL.md` | Route section rewritten to **L-only**; A (OpenRouter/TypeSafe) and B (simulation) removed together with their consent flows and key checks; commands run the script directly (`python3 <jev-skill-dir>/scripts/jev.py`). `jev-setup` is now a connectivity/route checker; `references/simulation.md` deleted. |
| `skills/jev/references/laya.md` | New adapter reference: endpoint, request/response mapping, variant guidance, measured latency, calibration caveats. |

Everything else (validation, review thresholds, exit codes, safety wording,
assets, evals, tests) is upstream v0.2.0 unchanged.

## Quick start

```bash
# No API key needed. Validate a request offline first (auto-routing shows
# which variant(s) each request would go to):
python3 skills/jev/scripts/jev.py decide skills/jev/assets/checkpoint.json --dry-run

# Real call via the local Laya service (default provider):
python3 skills/jev/scripts/jev.py decide skills/jev/assets/checkpoint.json

# Text classification:
python3 skills/jev/scripts/jev.py classify --text "billing charge looks wrong" \
    --criteria skills/jev/assets/support-labels.json

# Batch: make "state" a JSON array (one entry per record, <=200), the report
# comes back as an "items" list.

```

Exit codes: `0` selected/scored · `2` at least one question needs review ·
`1` error.

### Installing the skills for your agent

Copy the eleven folders from `skills/` into your agent's project-level skill
directory, e.g. `.zcode/skills/`, `.claude/skills/`, or `.agents/skills/`.
See `docs/upstream-README.md` (the original README) for the full skill
catalog, or `docs/install.md` for the upstream installation guide.

## Variant selection (auto by default)

Requests don't need a `model`: the CLI routes per this benchmarked decision
table (2026-09-21):

| | `english` | `multilingual` | `typed-decisions` |
|---|---|---|---|
| Strength | English general purpose, calibrated confidence | Chinese / multilingual classification | Numeric score calibration |
| English classification | 5/6 ✓ | 5/6 ✓ | 5/6 ✓ |
| Chinese classification | not recommended (English-only official) | 5/6 ✓ | 4/6 (slightly worse) |
| `urgency` score shape | squeezed mid-range (0.5–1.9) | all high (1.4–1.9) ⚠ | clean 3-band separation (≈0.6 / 1.2 / 1.8) ✓ |
| `choice` confidence | 0.46–0.86, safe for absolute thresholds | 0.69–1.00, high but usable | 0.04–0.34, relative only |
| Latency | 8 ms | 6.3 ms | 8 ms |

Routing rules:

- `choice` / `noul` questions only → `english` when the `state` text is
  predominantly English, otherwise `multilingual`.
- Any `score` question → `typed-decisions` (fixed thresholds work there:
  score > 1.4 → critical, 0.9–1.4 → soon, < 0.9 → not urgent).
- Mixed requests are split into two Laya calls, one per model, and merged
  into one report; the report's `routing` object records strategy, detected
  language, and the models used. `--model english\|multilingual\|typed-decisions`
  forces a single variant.

Measured on 2026-09-21: single ≈ 13–31 ms, batch ≈ 2–7.5 ms per record,
10 concurrent singles ≈ 0.22 s server-side.

## Notes and limits

- The default endpoint (`http://172.27.116.56:8000`) is a **private campus
  address** reachable only inside that LAN. Point `LAYA_URL` at your own Laya
  deployment to use this fork elsewhere.
- Laya probabilities come from `laya-rl-agent`, not TypeSafe Jev; they are not
  calibrated to Jev's published bands. Keep the `needs_review` guardrails and
  treat provider `confidence` as a signal, not a guarantee.
- Decisions are advisory: selection is never permission to act.

## License

MIT, © the upstream author(s) of [jev-skill](https://github.com/wuyoscar/jev-skill).
This fork's changes are published under the same license; see [LICENSE](LICENSE).
Upstream READMEs are preserved at `docs/upstream-README.md` /
`docs/upstream-README.zh.md`.
