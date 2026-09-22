# Competitive AI-Tool Radar — runnable demo

[![GitHub repo](https://img.shields.io/badge/GitHub-Laksh--star%2Fradar--demo-blue?logo=github)](https://github.com/Laksh-star/radar-demo)

This is the pipeline from the architecture diagram, actually running. Every
stage has a real implementation now; the ones needing a paid API key fall
back to a free mock when the key isn't set, so it always runs end to end.

## Run it

```
pip install -r requirements.txt
cp .env.example .env      # then fill in whichever keys you have — all optional
python3 pipeline.py
```

It resets `dashboard.sqlite`, seeds one entity as "already seen from
yesterday" (so you can watch dedup actually skip something), then runs all
8 stages and prints a trace — item counts at every stage, which items got
discarded and why, which ones got a generated brief, and the final rows
written to the local SQLite "dashboard."

### Configuration — `.env`

Every real integration (TypeSafe AI, Anthropic) reads its key from the
environment, loaded automatically from a local `.env` file via
`python-dotenv` (see `pipeline.py`/`dashboard.py`'s `load_dotenv()` call).
`.env.example` documents every variable; copy it to `.env` and fill in
whatever you have — anything you leave blank just falls back to that
stage's free mock. `.env` itself is gitignored, so cloning this repo never
exposes real keys, and anyone can run the full pipeline with zero setup
(all mocks) before adding any keys at all.

### Or watch it run in a browser

```
python3 dashboard.py
open http://localhost:5050
```

Same pipeline, same `run_pipeline()` in `pipeline.py` — just rendered live
instead of printed. Pick providers from the dropdowns (a key badge tells you
whether `TYPESAFE_API_KEY` / `ANTHROPIC_API_KEY` are set) and hit **Run
pipeline**. The 8 stages light up as they run, and the right-hand panel
streams Jev's Choice/Score/Noul judgment for every item the moment each
call returns, with its confidence and latency — that panel is the point of
the dashboard: it's the only stage in the pipeline making a real per-item
judgment call fast enough to watch happen live.

## What's real vs. mocked

| File | Status | Notes |
|---|---|---|
| `models.py` | real | the `RawSignal` / `TriageResult` / `Signal` Pydantic contracts |
| `extract.py` | real | pluggable `ExtractionProvider` interface — `BrowserUseExtract` runs a real browser-use `Agent` against Hacker News / GitHub Trending (Product Hunt excluded, see below), `MockExtract` returns the canned `sample_sources.py` batch (all 3 sources) |
| `triage.py` | real | pluggable `TriageProvider` interface — `TypeSafeTriage` makes the real `/v1/systemone` call, `MockTriage` is the original keyword heuristic kept as a no-key fallback |
| `gate.py` | real | the actual threshold logic (`relevance_score >= 1.0 and relevance_confidence >= 0.6`) |
| `store.py` | real | SQLite-backed dedup table + persistence — stands in for your `create_brief` / `get_trending_competitors` tools |
| `generate.py` | real | pluggable `GenerateProvider` interface — `ClaudeGenerate` calls the Anthropic API, `MockGenerate` is the original templated placeholder kept as a no-key fallback |
| `pipeline.py` | real | `run_pipeline()` orchestrates all 8 stages and emits an event per step; `pipeline.py`'s own `main()` prints a trace, `dashboard.py` renders those same events live |
| `dashboard.py` | real | Flask + Server-Sent Events; a local web view of a run, with a dedicated live panel for Jev's per-item judgments |

Every stage now has a real path. The only thing that still doesn't exist at
all — real or mocked — is stage 5's second browser-use "deep dive" pass on
survivors; `generate.py` writes straight from the stage-4 triage
description instead. Everything else either runs for real when its key is
set, or falls back to a free, keyless mock so the pipeline always completes.

### Extract provider selection

`extract.get_extract_provider()` reads `EXTRACT_PROVIDER` from the
environment. Unlike triage/generate below, this **defaults to `mock`** even
when `ANTHROPIC_API_KEY` is set — a live 3-site crawl takes ~30-90s and
spends several LLM calls, so it needs an explicit opt-in rather than
piggybacking on a key set for another stage:

- unset or `mock` → the canned `sample_sources.py` batch, no key/network/browser
- `browser-use` → a real browser-use `Agent` (needs `ANTHROPIC_API_KEY` — this
  drives the *browsing* agent, unrelated to Jev, which only judges afterward).
  It launches its own isolated headless Chromium (a temp profile via the
  `browser-use` package), not your regular browser.

**Product Hunt is excluded from the live crawl.** It sits behind a
Cloudflare "verify you're human" challenge that a headless agent gets stuck
on indefinitely trying (and failing) to click through — observed 12+ steps
with no resolution in testing. We don't attempt to solve bot-detection
challenges, so `BrowserUseExtract` only hits Hacker News and GitHub
Trending live; Product Hunt items only ever come from `MockExtract`'s
sample data. Each source is also capped at 15 agent steps
(`_MAX_STEPS_PER_SOURCE` in `extract.py`) so any *other* site that traps
the agent fails fast and cheap instead of grinding — `agent.run()` defaults
to 500 steps, which is a lot of real LLM calls to burn on a stuck page.

```
# in .env: ANTHROPIC_API_KEY=... and EXTRACT_PROVIDER=browser-use
python3 pipeline.py

# or without .env:
ANTHROPIC_API_KEY=your-key-here EXTRACT_PROVIDER=browser-use python3 pipeline.py
```

### Triage provider selection

`triage.get_triage_provider()` reads `TRIAGE_PROVIDER` from the environment:

- unset → `typesafe` if `TYPESAFE_API_KEY` is set, else `mock`
- `typesafe` → real call to TypeSafe AI's `/v1/systemone` (needs `TYPESAFE_API_KEY`)
- `mock` → the original keyword heuristic, no key or network needed

```
# in .env: TYPESAFE_API_KEY=...
python3 pipeline.py            # uses TypeSafeTriage

TRIAGE_PROVIDER=mock python3 pipeline.py   # forces the free heuristic
```

Both implement the `TriageProvider` interface (`triage(raw: RawSignal) ->
TriageResult`), so `gate.py`, `pipeline.py`, and everything downstream don't
care which one ran.

### Generate provider selection

`generate.get_generate_provider()` follows the same pattern, reading
`GENERATE_PROVIDER` from the environment:

- unset → `claude` if `ANTHROPIC_API_KEY` is set, else `mock`
- `claude` → real call to the Anthropic API (needs `ANTHROPIC_API_KEY`)
- `mock` → the original templated placeholder, no key or network needed

```
# in .env: ANTHROPIC_API_KEY=...
python3 pipeline.py            # uses ClaudeGenerate

GENERATE_PROVIDER=mock python3 pipeline.py   # forces the free template
```

Note stage 5 (the browser-use "deep dive" on survivors) still doesn't exist
in this demo — `generate.py` writes straight from the triage-stage
description, not from an enriched deep-dive read. Real deep-dive detail
would only make the brief better, not change the plumbing.

## Making it fully live

1. **Extraction** — done. Set `ANTHROPIC_API_KEY` and `EXTRACT_PROVIDER=browser-use`;
   see "Extract provider selection" above.
2. **Triage** — done. Set `TYPESAFE_API_KEY` and it calls the real API; see
   "Triage provider selection" above.
3. **Generation** — done. Set `ANTHROPIC_API_KEY` and it calls Sonnet; see
   "Generate provider selection" above. Still missing stage 5's browser-use
   deep dive, so briefs are written from the triage-stage description alone.
4. **Persistence** — replace the two functions in `store.py` with calls to
   your actual `create_brief` / `get_trending_competitors` tools.

Nothing else needs to change — `gate.py`, `pipeline.py`, and the shapes in
`models.py` don't care where a `RawSignal` or `TriageResult` came from.

## Sample data

`sample_sources.py` isn't random filler. It's built from the actual web
research earlier in this conversation — the TypeSafe AI / Jev launch,
`steel-dev`'s web-agent list, Hyperagent, Cloudflare's Jev model listing —
mixed with a few deliberately irrelevant items (a note-taking app, a
planner app, a game engine, a forum thread) so the gate has real noise to
filter, the way an actual trending page would hand you a mix of both.
