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

**Idle, before a run:**

![Dashboard idle](screenshots/dashboard-idle.png)

**After a completed run** — all 8 stages, Jev's live judgments, stage 5's
deep-dive detail, the generated briefs, and the final persisted state:

![Dashboard after a run](screenshots/dashboard-full-run.png)

**A real run** — real Jev triage, real browser-use deep dive, real Claude
generation (the mock run above only differs in provider choice, not in what
the UI shows):

![Dashboard with a real Jev + Claude run](screenshots/dashboard-real-jev-run.png)

### Or touch the judgment layer directly

```
python3 playground.py
open http://localhost:5051
```

The dashboard answers *"does the pipeline run?"*. The playground answers
*"what is Jev actually buying me?"* — it pulls stage 4 out of the table and
makes it something you can poke at. Same `triage.py`, same `gate.py`, same
`TriageResult` contract; only the framing is different.

![Jev playground — a judgment and the gate](screenshots/playground-judgment.png)

Four things you can do with your hands:

1. **Ask Jev something** — tap one of the sample signals or type your own
   headline, and watch Choice / Score / Noul land together with their
   confidences and the measured round-trip latency.
2. **Move the gate** — four sliders for the thresholds in `gate.py`
   (they're loaded from it at page load, not hardcoded in the page). The
   judgment stays fixed; no new calls are made. Only the bars move, and the
   verdict flips under your hand with a plain-English sentence saying
   exactly which of the three answers decided it. Drag the Noul bar below an
   item's Noul score and you can watch the **NOUL OVERRIDE** fire in real
   time — the mechanism `gate.py` describes, made tactile.
3. **Race a full LLM** — the same three questions go to Jev and to Sonnet at
   the same moment, asked for identical JSON. Both lanes show their answer,
   their latency, and (for the LLM) the tokens it burned writing that JSON
   out token by token. Measured runs here came in at 3.8–5.3× faster for the
   same verdict.
4. **Fire a batch** — all 10 sample signals judged concurrently (8 at a
   time), each tile flipping as its own call returns, ending in the funnel:
   how many came in, how many escalated, how many were dropped before
   anything expensive ran.

![Jev playground — race and batch](screenshots/playground-race-batch.png)

Every number on that page is measured in your own session — nothing is
replayed from `benchmark/stats.json`. The bottom ledger only shows "LLM time
saved" *after* you've run a race, because until then it has no measured LLM
latency to subtract, and it won't quote a claimed one. With no
`TYPESAFE_API_KEY` set it runs the same page against `MockTriage` and the
badge says so; the race lane needs `ANTHROPIC_API_KEY` and disables itself
without one.

## Benchmark data

`benchmark/run_benchmark.py` runs the pipeline once against the fixed mock
extraction batch (so the input set stays constant) with real Jev triage,
real deep dive, and real Claude generation, and writes per-item data plus
aggregate stats to `benchmark/stats.json`. `benchmark/trace.txt` is a
cleaned console trace from one such run. Headline numbers from that run:

- 9 real Jev calls: latency 831.6-927.8ms (mean 884.2ms, median 894.0ms) —
  consistently sub-second, though above the 70-500ms figure in TypeSafe's
  own materials (this is round-trip HTTP latency from a local machine, not
  necessarily model inference time)
- 2 of 9 items escalated — the gate filtered 78% of items before either
  expensive stage (deep dive, generation) ran on them
- 0 Noul overrides in this particular run (the mechanism is verified
  separately — see `gate.py` and the commit that added it — this run's
  input just didn't happen to contain a case for it)

```
python3 benchmark/run_benchmark.py   # needs TYPESAFE_API_KEY + ANTHROPIC_API_KEY
```

## What's real vs. mocked

| File | Status | Notes |
|---|---|---|
| `models.py` | real | the `RawSignal` / `TriageResult` / `Signal` Pydantic contracts |
| `extract.py` | real | pluggable `ExtractionProvider` interface — `BrowserUseExtract` runs a real browser-use `Agent` against Hacker News / GitHub Trending (Product Hunt excluded, see below), `MockExtract` returns the canned `sample_sources.py` batch (all 3 sources) |
| `triage.py` | real | pluggable `TriageProvider` interface — `TypeSafeTriage` makes the real `/v1/systemone` call, `MockTriage` is the original keyword heuristic kept as a no-key fallback |
| `gate.py` | real | threshold logic using all three of Jev's judgments — a confident new entrant (Noul) clears the gate at a lower relevance bar than a repost or known name would; see below |
| `store.py` | real | SQLite-backed dedup table + persistence — stands in for your `create_brief` / `get_trending_competitors` tools |
| `deep_dive.py` | real | pluggable `DeepDiveProvider` interface — `BrowserUseDeepDive` opens each escalated item's own url and summarizes what's actually there, `MockDeepDive` passes the stage-1 description straight through |
| `generate.py` | real | pluggable `GenerateProvider` interface — `ClaudeGenerate` calls the Anthropic API using stage 5's enriched detail, `MockGenerate` is the original templated placeholder kept as a no-key fallback |
| `pipeline.py` | real | `run_pipeline()` orchestrates all 8 stages and emits an event per step; `pipeline.py`'s own `main()` prints a trace, `dashboard.py` renders those same events live |
| `dashboard.py` | real | Flask + Server-Sent Events; a local web view of a run, with a dedicated live panel for Jev's per-item judgments |
| `playground.py` | real | Flask + SSE hands-on view of stage 4 alone — live Jev calls, draggable `gate.py` thresholds, a same-moment Jev-vs-LLM race, and a concurrent batch |

Every stage now has a real path — including stage 5's deep dive, which
opens each escalated item's own url and hands `generate.py` a couple of
concrete facts instead of just the stage-1 blurb. Every real integration
either runs for real when its key is set, or falls back to a free, keyless
mock so the pipeline always completes.

### The gate uses all three of Jev's judgments, not just Score

Jev returns three answers per item — Choice (category), Score (relevance),
and Noul (confidence this is a genuinely new entrant, not a repost). The
gate originally only checked Score and its confidence; Noul was requested,
displayed, and persisted, but never changed a decision, which undersold
what Jev actually does. Now:

```python
# gate.py
if triage.relevance_confidence < CONFIDENCE_THRESHOLD:
    return False
if triage.is_new_entrant >= NEW_ENTRANT_THRESHOLD:      # confident new entrant
    return triage.relevance_score >= NEW_ENTRANT_RELEVANCE_THRESHOLD  # lower bar: 0.7
return triage.relevance_score >= RELEVANCE_THRESHOLD    # normal bar: 1.0
```

A confident first-sighting of a genuinely new competitor is exactly the
kind of thing worth catching before it's built up the same relevance a
familiar name would need — so it escalates at 0.7 instead of 1.0. When this
is the deciding factor, the dashboard tags that item's Noul score with a
**NEW→ESCALATED** badge, and the CLI trace prints a `NOUL OVERRIDE` line —
so the fact that Noul changed an outcome is visible, not just logged.

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

### Deep dive provider selection

`deep_dive.get_deep_dive_provider()` reads `DEEP_DIVE_PROVIDER` from the
environment. Like extraction, this **defaults to `mock`** even when
`ANTHROPIC_API_KEY` is set — it's an extra browser-use pass per escalated
item, so it needs an explicit opt-in:

- unset or `mock` → passes the stage-1 description straight through, no key/network/browser
- `browser-use` → a real browser-use `Agent` opens the item's own url and
  summarizes what's actually on the page (needs `ANTHROPIC_API_KEY`, same
  headless Chromium approach as extraction, same `BROWSER_USE_HEADLESS`
  toggle and per-item step cap)

```
# in .env: ANTHROPIC_API_KEY=... and DEEP_DIVE_PROVIDER=browser-use
python3 pipeline.py
```

Both implement the `DeepDiveProvider` interface (`dive(raw: RawSignal) ->
str`), so `generate.py` only ever sees the detail string it returns —
identical whether that string came from a real page read or was just the
original blurb. This is why the full-mock pipeline's output is byte-for-byte
unchanged from before this stage existed.

### Generate provider selection

`generate.get_generate_provider()` follows the same pattern, reading
`GENERATE_PROVIDER` from the environment:

- unset → `claude` if `ANTHROPIC_API_KEY` is set, else `mock`
- `claude` → real call to the Anthropic API, using stage 5's enriched detail
  instead of the raw stage-1 description (needs `ANTHROPIC_API_KEY`)
- `mock` → the original templated placeholder, no key or network needed

```
# in .env: ANTHROPIC_API_KEY=...
python3 pipeline.py            # uses ClaudeGenerate

GENERATE_PROVIDER=mock python3 pipeline.py   # forces the free template
```

## Making it fully live

1. **Extraction** — done. Set `ANTHROPIC_API_KEY` and `EXTRACT_PROVIDER=browser-use`;
   see "Extract provider selection" above.
2. **Triage** — done. Set `TYPESAFE_API_KEY` and it calls the real API; see
   "Triage provider selection" above.
3. **Deep dive** — done. Set `ANTHROPIC_API_KEY` and `DEEP_DIVE_PROVIDER=browser-use`;
   see "Deep dive provider selection" above.
4. **Generation** — done. Set `ANTHROPIC_API_KEY` and it calls Sonnet; see
   "Generate provider selection" above.
5. **Persistence** — replace the two functions in `store.py` with calls to
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
