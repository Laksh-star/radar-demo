# I Wired TypeSafe AI's Jev Into a Real Pipeline. Here's What Actually Held Up.

There's a specific kind of AI demo I've stopped trusting: the one where every screenshot is a mockup, every number is illustrative, and "it works" means "it works in the slide." So when I wanted to understand what TypeSafe AI's Jev model actually does — not what the launch post says it does — I built the thing it's meant to power, end to end, and pointed it at the real API.

This is what happened, including the parts that didn't go the way the marketing copy implied.

![Everything before the gate is cheap. Everything after it isn't — and that asymmetry is the only reason a model like Jev has a job here.](screenshots/architecture-diagram.png)

## The premise: a competitive-intelligence radar

The demo is a pipeline that watches Hacker News and GitHub Trending, judges every item it finds, and only spends real money — a browser agent reading a page closely, an LLM writing a paragraph — on the handful of items that clear a bar. Eight stages: extract, validate, dedup, triage, gate, deep dive, generate, persist, deliver. Jev's job is stage 4: triage. Everything before it is cheap. Everything after it is not. That asymmetry is the entire point of the architecture, and it's also the entire pitch for a model like Jev — a fast, structured judgment layer sitting in front of expensive generative calls.

I built every stage for real. No stubbed responses, no "imagine this called an API." The extraction stage runs an actual `browser-use` agent in a real (if headless) Chromium session. The generation stage calls Claude. And triage calls Jev's real `/v1/systemone` endpoint, with a real key, over real HTTP.

## What Jev actually returns

One call, three answers. Choice (which category this falls into), Score (0–2, how relevant), and Noul (confidence this is a genuinely new competitor, not a repost) — each with its own confidence score, back in under a second.

![Three answers per item from a single call, landing live as the run works through its queue.](screenshots/dashboard-full-run.png)

That structure is genuinely useful, and it's not just marketing description — I built a UI specifically to stream these three numbers live as they come back, because watching them arrive one item at a time is the fastest way to understand what the model is doing that a single text description isn't.

## The numbers, from an actual benchmark

I ran the pipeline against a fixed, reproducible batch of 9 items — real Jev calls, not mocked — and logged everything: per-item latency, category, scores, the works.

- **9 real Jev calls, against build `jev-1.13.0`.** Latency: 384.6ms–511.6ms, mean 456.5ms, median 451.4ms. Cost: 4,006 input and 819 output tokens across the nine.
- **2 of 9 items escalated.** The gate filtered out 78% of items before either expensive downstream stage — deep dive or generation — ever ran on them.

![Nine real Jev calls. The two survivors are the only items that went on to cost anything.](screenshots/chart-filter-funnel.png)

One honest note here, and it got more interesting the second time I ran it. Jev's own materials cite 70–500ms response times. My first benchmark run measured 831.6ms–927.8ms — consistently, across every call, clearly outside that band — and I wrote it up that way. When I re-ran the identical benchmark eight hours later — same machine, same fixed input set, late evening to early morning — I got 384.6ms–511.6ms. Roughly half, and inside the published band except for the slowest call, which is 2% over.

I can't tell you what changed, and that's the part worth passing on. The first run didn't record which model build answered it, so I can't even rule a build change in or out — and over an eight-hour gap that ran through the small hours, load and network path are at least as likely as anything about the model. The API returns the resolved build and the token usage on every single call, and I was parsing both off and throwing them away. A benchmark that can't say what it measured can't explain its own results later. The demo records both now — the first number is stuck being an anecdote, and the second one won't be.

## The gap I found, and fixed

Here's the part I didn't expect going in. Noul — the "is this a genuinely new competitor" signal — was being returned by every single call. It was displayed in the dashboard. It was written to the database. And it was doing *nothing*. My original gate logic only checked Score and its confidence. A confident first-sighting of a brand-new competitor and a fourth repost of something everyone already tracks were being treated identically, as long as their relevance score matched.

![The field was returned, displayed and written to the database from the first run. Nothing ever read it.](screenshots/diagram-noul-before-after.png)

I fixed it: a confident new entrant (Noul ≥ 0.7) now clears the gate at a relevance score of 0.7 instead of the normal 1.0. The reasoning is straightforward — catching a genuinely new competitor early is worth surfacing before it's built up the same conventional relevance a familiar name would need. I verified this with five direct boundary-condition tests and one forced end-to-end run before trusting it, and the dashboard now tags any item that escalates *because* of this rule with a visible badge, so the effect is never invisible.

This is, honestly, the most useful thing I can tell you about integrating a model like this: read what every field actually claims to do, and check whether your code uses it. It's an easy thing to miss, and it's exactly the kind of gap that never shows up in a demo built to look finished rather than to be tested.

## Then I found the same mistake one level down

Fixing Noul made me suspicious, so I did the boring thing and diffed what Jev actually returns against what my code read. Here is one real call's response, reformatted for width but otherwise untouched:

```json
"category":   { "choice": "browser-automation", "confidence": 0.98,
                "probabilities": {"browser-automation":0.99,"agent-framework":0.01,
                                  "dev-tooling":0.0,"unrelated":0.0} },
"relevance":  { "score": 0.9, "confidence": 0.81,
                "legend": {"0":"Noise","1":"Worth tracking","2":"High priority"},
                "probabilities": {"0":0.11,"1":0.88,"2":0.01} },
"is_new_entrant": { "noul": 0.52 },
"model": "jev-1.13.0",
"usage": { "input_tokens": 441, "output_tokens": 92 }
```

My `TriageResult` had fields for five of those values. Everything else — the probability distribution behind each answer, the legend, the token usage, the build that actually answered — was parsed off and dropped on every single call. Same shape of bug as Noul, one level deeper: not an unused field this time, but an unused *dimension* of every field I was already using.

The token counts and the model build are the dull ones, and they cost me something concrete: my first benchmark couldn't say which model produced its numbers, which is exactly why I can't explain the latency change above. The distributions are the interesting ones.

**A confidence score and a probability distribution are not the same thing.** Jev's docs are explicit that confidence is a separate axis from probability, and once you can see both, the difference has teeth. A 0.99/0.01 split across options and a 0.51/0.49 split both arrive as one confident-looking winning label. Worse, on the Score question the number itself is an expectation — and an expectation flattens a split belief. A model that thinks an item is 45% noise and 45% high priority reports almost the same score as one that is calmly certain it is worth tracking.

![Real numbers from one benchmark run against jev-1.13.0. The mean cannot tell these two apart.](screenshots/chart-score-distribution.png)

So I wrote two gate rules that read distributions instead of labels. Both lean on one line in TypeSafe's docs: every question in a call is evaluated *in parallel and in isolation*. Independent questions can disagree — and the winning label is exactly where that disagreement goes to hide.

![pixel-forge and Cloudflare Workers AI — both real items, both from the same nine calls.](screenshots/diagram-distribution-rules.png)

The first is an **unrelated veto**: when Choice puts most of its belief on "not your space", that overrules a relevance score that squeaked over the bar. The second is a **high-priority tail**: enough probability mass on the top level escalates an item on its own, whatever the mean says.

And then I got the second one wrong, in a way that only measuring caught.

I wrote the tail rule *below* the existing confidence floor, which seemed obviously right — don't spend money on an answer the model says it doesn't trust. Then I fired five realistic headlines at it. "Stealth startup raises $40M for agent infrastructure." "Browser vendor ships a native agent API." Every one came back with 0.31–0.62 of its belief on *high priority* — and confidence between 0.28 and 0.52. The floor killed all five before the tail rule was ever consulted.

That is not a coincidence, and it is the whole point: **the items with a split belief are precisely the items the model is least confident about.** Ordering the rules the obvious way made the new one into dead code — the third piece of decoration in a row, for the same reason. I moved the tail check above the floor. "This might be significant and I can't tell" is the strongest case for spending a cheap look, not the weakest.

On the benchmark run, the gate outcomes break down as: four discards by the unrelated veto, three below the relevance bar, one escalation on the bar, and one on the tail. That last one is Cloudflare Workers AI — relevance 1.27 at 52% confidence, with 30% of its belief on high priority. The gate as it stood one commit earlier discarded it on the confidence floor. The filter ratio didn't move at all: still 2 of 9, still 78%. What changed was *which* two.

It is also, finally, something you can put your hands on. The playground I built for this exposes every threshold as a slider, and the distribution row a rule is acting on lights up the moment its bar crosses it. Below, a signal Jev scored 1.33 on but was only 44% confident about, with 35% of its belief on *high priority*. While the tail bar sits under that 35%, the distribution escalates it. Drag the bar above it and the rule stops applying — the verdict drops through to the confidence floor that used to decide it, and the item changes columns. No new calls are made. Only the bar moves.

![Drag the bar above the item's own tail and the rule stops applying. No new calls are made — only the bar moves.](screenshots/playground-gate-drag.gif)

## Proof, not a promise: a real run against the live API

![One run, nothing mocked: real Jev triage, a real browser agent reading the pages, real Claude writing the briefs.](screenshots/dashboard-real-jev-run.png)

That run's deep-dive stage — a browser agent reading the escalated items' own pages — pulled two claims directly off TypeSafe's own blog post, not written by me and not invented by the model:

> "input tokens cost $0.042 per million tokens (~$42 per billion), compared to $0.20–$10 per million tokens for existing LLMs... up to 193.6x faster and 444.6x cheaper on certain workflows"

Both are TypeSafe's own marketing claims, surfaced verbatim. I haven't independently verified either number, and neither should you take them as confirmed just because a demo quoted them accurately.

## What I'd tell you before you build on this

Three honest limits, found by actually running it rather than reading the docs:

1. **Bot-protected sites don't care how good your agent is.** Product Hunt sits behind a Cloudflare "verify you're human" challenge, and no amount of prompting gets a headless browser agent through it. I excluded it from live extraction entirely rather than let the agent grind at it — it's not a Jev problem, but it's a real one for anyone assuming "browser agent + LLM" means "any website."
2. **Watch your step budgets.** The extraction agent's underlying framework defaults to a 500-step run budget. A page that traps the agent (like the Cloudflare wall did, briefly, before I excluded it) could burn hundreds of real LLM calls before giving up. I capped it at 15 steps per source. If you're wiring up something similar, check this before your first real run, not after your first surprising bill.
3. **The architecture generalizes further than the specifics do.** The "cheap filter → gate → expensive stage only on survivors" shape applies to a lot of problems — lead scoring, ticket triage, moderation queues, research screening. The categories, the gate thresholds, and Jev's specific question criteria are tuned for exactly one use case and would need rewriting, not reconfiguring, for a different one.

## The verdict

Jev does what it says: fast, structured, multi-question judgments that make a cheap-filter-before-expensive-stage architecture actually work. The three-question-in-one-call design is genuinely efficient, and 78% of items never reaching an expensive stage is a real number from a real run, not a projection. The gaps I found — the latency delta, the unused Noul field, the discarded distributions, the step-budget risk — weren't reasons to distrust the core claim. They were just the ordinary cost of finding out for real instead of taking a launch post's word for it.

---

*All code, the reproducible benchmark script, and the raw data behind every number in this piece are public: [github.com/Laksh-star/radar-demo](https://github.com/Laksh-star/radar-demo).*
