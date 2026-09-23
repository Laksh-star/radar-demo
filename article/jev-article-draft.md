# I Wired TypeSafe AI's Jev Into a Real Pipeline. Here's What Actually Held Up.

There's a specific kind of AI demo I've stopped trusting: the one where every screenshot is a mockup, every number is illustrative, and "it works" means "it works in the slide." So when I wanted to understand what TypeSafe AI's Jev model actually does — not what the launch post says it does — I built the thing it's meant to power, end to end, and pointed it at the real API.

This is what happened, including the parts that didn't go the way the marketing copy implied.

![Architecture: extract, validate, dedup, triage, gate, deep dive, generate, persist, deliver](screenshots/architecture-diagram.png)

## The premise: a competitive-intelligence radar

The demo is a pipeline that watches Hacker News and GitHub Trending, judges every item it finds, and only spends real money — a browser agent reading a page closely, an LLM writing a paragraph — on the handful of items that clear a bar. Eight stages: extract, validate, dedup, triage, gate, deep dive, generate, persist, deliver. Jev's job is stage 4: triage. Everything before it is cheap. Everything after it is not. That asymmetry is the entire point of the architecture, and it's also the entire pitch for a model like Jev — a fast, structured judgment layer sitting in front of expensive generative calls.

I built every stage for real. No stubbed responses, no "imagine this called an API." The extraction stage runs an actual `browser-use` agent in a real (if headless) Chromium session. The generation stage calls Claude. And triage calls Jev's real `/v1/systemone` endpoint, with a real key, over real HTTP.

## What Jev actually returns

One call, three answers. Choice (which category this falls into), Score (0–2, how relevant), and Noul (confidence this is a genuinely new competitor, not a repost) — each with its own confidence score, back in under a second.

![Jev's Choice/Score/Noul columns, live](screenshots/dashboard-full-run.png)

That structure is genuinely useful, and it's not just marketing description — I built a UI specifically to stream these three numbers live as they come back, because watching them arrive one item at a time is the fastest way to understand what the model is doing that a single text description isn't.

## The numbers, from an actual benchmark

I ran the pipeline against a fixed, reproducible batch of 9 items — real Jev calls, not mocked — and logged everything: per-item latency, category, scores, the works.

- **9 real Jev calls, against build `jev-1.13.0`.** Latency: 384.6ms–511.6ms, mean 456.5ms, median 451.4ms. Cost: 4,006 input and 819 output tokens across the nine.
- **2 of 9 items escalated.** The gate filtered out 78% of items before either expensive downstream stage — deep dive or generation — ever ran on them.

![From 10 items to 2 escalations](screenshots/chart-filter-funnel.png)

One honest note here, and it got more interesting the second time I ran it. Jev's own materials cite 70–500ms response times. My first benchmark run measured 831.6ms–927.8ms — consistently, across every call, clearly outside that band — and I wrote it up that way. When I re-ran the identical benchmark eight hours later — same machine, same fixed input set, late evening to early morning — I got 384.6ms–511.6ms. Roughly half, and inside the published band except for the slowest call, which is 2% over.

I can't tell you what changed, and that's the part worth passing on. The first run didn't record which model build answered it, so I can't even rule a build change in or out — and over an eight-hour gap that ran through the small hours, load and network path are at least as likely as anything about the model. The API returns the resolved build and the token usage on every single call, and I was parsing both off and throwing them away. A benchmark that can't say what it measured can't explain its own results later. The demo records both now — the first number is stuck being an anecdote, and the second one won't be.

## The gap I found, and fixed

Here's the part I didn't expect going in. Noul — the "is this a genuinely new competitor" signal — was being returned by every single call. It was displayed in the dashboard. It was written to the database. And it was doing *nothing*. My original gate logic only checked Score and its confidence. A confident first-sighting of a brand-new competitor and a fourth repost of something everyone already tracks were being treated identically, as long as their relevance score matched.

![Noul went from decorative to load-bearing](screenshots/diagram-noul-before-after.png)

I fixed it: a confident new entrant (Noul ≥ 0.7) now clears the gate at a relevance score of 0.7 instead of the normal 1.0. The reasoning is straightforward — catching a genuinely new competitor early is worth surfacing before it's built up the same conventional relevance a familiar name would need. I verified this with five direct boundary-condition tests and one forced end-to-end run before trusting it, and the dashboard now tags any item that escalates *because* of this rule with a visible badge, so the effect is never invisible.

This is, honestly, the most useful thing I can tell you about integrating a model like this: read what every field actually claims to do, and check whether your code uses it. It's an easy thing to miss, and it's exactly the kind of gap that never shows up in a demo built to look finished rather than to be tested.

## Proof, not a promise: a real run against the live API

![A real run: real Jev, real deep dive, real Claude generation](screenshots/dashboard-real-jev-run.png)

That run's deep-dive stage — a browser agent reading the escalated items' own pages — pulled two claims directly off TypeSafe's own blog post, not written by me and not invented by the model:

> "input tokens cost $0.042 per million tokens (~$42 per billion), compared to $0.20–$10 per million tokens for existing LLMs... up to 193.6x faster and 444.6x cheaper on certain workflows"

Both are TypeSafe's own marketing claims, surfaced verbatim. I haven't independently verified either number, and neither should you take them as confirmed just because a demo quoted them accurately.

## What I'd tell you before you build on this

Three honest limits, found by actually running it rather than reading the docs:

1. **Bot-protected sites don't care how good your agent is.** Product Hunt sits behind a Cloudflare "verify you're human" challenge, and no amount of prompting gets a headless browser agent through it. I excluded it from live extraction entirely rather than let the agent grind at it — it's not a Jev problem, but it's a real one for anyone assuming "browser agent + LLM" means "any website."
2. **Watch your step budgets.** The extraction agent's underlying framework defaults to a 500-step run budget. A page that traps the agent (like the Cloudflare wall did, briefly, before I excluded it) could burn hundreds of real LLM calls before giving up. I capped it at 15 steps per source. If you're wiring up something similar, check this before your first real run, not after your first surprising bill.
3. **The architecture generalizes further than the specifics do.** The "cheap filter → gate → expensive stage only on survivors" shape applies to a lot of problems — lead scoring, ticket triage, moderation queues, research screening. The categories, the gate thresholds, and Jev's specific question criteria are tuned for exactly one use case and would need rewriting, not reconfiguring, for a different one.

## The verdict

Jev does what it says: fast, structured, multi-question judgments that make a cheap-filter-before-expensive-stage architecture actually work. The three-question-in-one-call design is genuinely efficient, and 78% of items never reaching an expensive stage is a real number from a real run, not a projection. The gaps I found — the latency delta, the unused Noul field, the step-budget risk — weren't reasons to distrust the core claim. They were just the ordinary cost of finding out for real instead of taking a launch post's word for it.

---

*All code, the reproducible benchmark script, and the raw data behind every number in this piece are public: [github.com/Laksh-star/radar-demo](https://github.com/Laksh-star/radar-demo).*
