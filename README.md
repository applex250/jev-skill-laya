# jev-skill-laya

A fork of [wuyoscar/jev-skill](https://github.com/wuyoscar/jev-skill) **v0.2.0**
(commit `82c0105`) adapted so every skill calls a **local Laya decision API by
default** — keyless, free, and staying inside the campus network — instead of
requiring an OpenRouter or TypeSafe key. The original Jev routes remain fully
available via `--provider openrouter|typesafe`.

## Why

The upstream skills are gated on `OPENROUTER_API_KEY` / `TYPESAFE_API_KEY` and
per-call charges. This fork points them at a self-hosted **Laya** decision
service (a FastAPI + `laya-rl-agent` deployment on an RTX 5090) that answers
the same typed questions (choice / score / noul) with probabilities, at
millisecond latency and no cost.

## What changed from upstream v0.2.0

| Area | Change |
|---|---|
| `skills/jev/scripts/jev.py` | New `laya` provider and **new default**. No auth header. Unwraps the `{"ok": true, "result": ...}` envelope; a list `result` becomes a per-record `items` report. Model defaults to `multilingual`; non-Laya model IDs in bundled assets map to it automatically. Endpoint overridable via the `LAYA_URL` env var. |
| Honest labeling | Laya reports say `mode: laya_api`, `jev_called: false`, `laya_called: true`, `backend: laya-rl-agent` — never presented as TypeSafe Jev calibration. |
| All 11 `SKILL.md` | Route menu now leads with **L — Local Laya (default, already configured)** before A (OpenRouter/TypeSafe) and B (simulation); commands run the script directly (`python3 <jev-skill-dir>/scripts/jev.py`) instead of assuming a `jev-decide` CLI install. |
| `skills/jev/references/laya.md` | New adapter reference: endpoint, request/response mapping, variant guidance, measured latency, calibration caveats. |

Everything else (validation, review thresholds, exit codes, safety wording,
assets, evals, tests) is upstream v0.2.0 unchanged.

## Quick start

```bash
# No API key needed. Validate a request offline first:
python3 skills/jev/scripts/jev.py decide skills/jev/assets/checkpoint.json --dry-run

# Real call via the local Laya service (default provider):
python3 skills/jev/scripts/jev.py decide skills/jev/assets/checkpoint.json

# Text classification:
python3 skills/jev/scripts/jev.py classify --text "billing charge looks wrong" \
    --criteria skills/jev/assets/support-labels.json

# Batch: make "state" a JSON array (one entry per record, <=200), the report
# comes back as an "items" list.

# OpenRouter / TypeSafe (upstream behavior, keys required):
python3 skills/jev/scripts/jev.py decide request.json --provider typesafe
```

Exit codes: `0` selected/scored · `2` at least one question needs review ·
`1` error.

### Installing the skills for your agent

Copy the eleven folders from `skills/` into your agent's project-level skill
directory, e.g. `.zcode/skills/`, `.claude/skills/`, or `.agents/skills/`.
See `docs/upstream-README.md` (the original README) for the full skill
catalog, or `docs/install.md` for the upstream installation guide.

## Laya variants

| Variant | Use for |
|---|---|
| `multilingual` (default) | Chinese / mixed-language input, department classification |
| `typed-decisions` | Best-calibrated `score` answers (urgency, rubrics); score > 1.4 ≈ critical, < 0.9 ≈ not urgent |
| `english` | English general purpose |

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
