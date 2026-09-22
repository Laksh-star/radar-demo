"""
Stand-in for what browser-use's Agent would return after a real run against
Hacker News, GitHub Trending and Product Hunt.

This sandbox has no LLM key for browser-use's own agent loop and no API key
for Jev, so stage 1 and stage 4 are mocked in this demo (see extract.py and
triage.py for exactly where). The items below aren't invented noise, though —
they're drawn from the web research earlier in this conversation (browser-use
itself, the TypeSafe AI / Jev launch, steel-dev's web-agent list, Hyperagent),
mixed with a few deliberately irrelevant items so the gate has something to
actually filter out, the way a real trending page would.
"""

from datetime import date

from models import RawSignal, Source

TODAY = date(2026, 9, 22)

RAW_SIGNALS: list[RawSignal] = [
    RawSignal(
        source=Source.HACKER_NEWS,
        title="TypeSafe AI launches Jev, a non-autoregressive model for structured predictions",
        entity="TypeSafe AI — Jev",
        url="https://typesafe.ai/blog/introducing-system-one-models-and-jev",
        seen_date=TODAY,
        description=(
            "New 'System One' model family from TypeSafe AI. Bypasses token-by-token "
            "generation for deterministic Choice/Score/Noul predictions in 70-500ms, "
            "positioned as a fast classifier/router in front of generative LLMs."
        ),
    ),
    RawSignal(
        source=Source.GITHUB_TRENDING,
        title="steel-dev/awesome-web-agents",
        entity="steel-dev",
        url="https://github.com/steel-dev/awesome-web-agents",
        seen_date=TODAY,
        description=(
            "Curated list of tools, frameworks and resources for building AI web agents — "
            "trending alongside renewed interest in browser-controlling agents."
        ),
    ),
    RawSignal(
        source=Source.PRODUCT_HUNT,
        title="Hyperagent — alpha access for AI browser agents",
        entity="Hyperagent",
        url="https://hyperagent.dev",
        seen_date=TODAY,
        description=(
            "Browser-agent platform in alpha testing, positioned for practitioner-voice "
            "workflows and agentic web automation."
        ),
    ),
    RawSignal(
        source=Source.GITHUB_TRENDING,
        title="Jev (typesafe) model card",
        entity="Cloudflare Workers AI",
        url="https://developers.cloudflare.com/ai/models/typesafe/jev/",
        seen_date=TODAY,
        description=(
            "Cloudflare Workers AI adds the Jev model to its catalog — infrastructure-level "
            "distribution for TypeSafe AI's System One model."
        ),
    ),
    RawSignal(
        source=Source.HACKER_NEWS,
        title="Show HN: A weekend note-taking app with local-first sync",
        entity="NoteDrift",
        url="https://example.com/notedrift",
        seen_date=TODAY,
        description="Personal note-taking side project, local-first storage, no AI or agent angle.",
    ),
    RawSignal(
        source=Source.PRODUCT_HUNT,
        title="PlannerPro — a new productivity planner app",
        entity="PlannerPro",
        url="https://example.com/plannerpro",
        seen_date=TODAY,
        description="Daily planner and habit tracker app for consumers, no developer tooling angle.",
    ),
    RawSignal(
        source=Source.GITHUB_TRENDING,
        title="pixel-forge/retro-engine",
        entity="pixel-forge",
        url="https://example.com/pixel-forge",
        seen_date=TODAY,
        description="2D retro game engine written in Rust, trending on GitHub this week.",
    ),
    RawSignal(
        source=Source.HACKER_NEWS,
        title="Ask HN: Best way to learn woodworking as a beginner?",
        entity="n/a",
        url="https://example.com/hn-woodworking",
        seen_date=TODAY,
        description="Discussion thread, no product or company signal.",
    ),
    RawSignal(
        source=Source.GITHUB_TRENDING,
        title="browser-use/browser-use-examples",
        entity="browser-use",
        url="https://github.com/browser-use/browser-use-examples",
        seen_date=TODAY,
        description=(
            "Companion examples repo for browser-use, trending alongside growing interest "
            "in browser-controlling agents and their integration patterns."
        ),
    ),
    RawSignal(
        source=Source.PRODUCT_HUNT,
        title="steel-dev — cloud browser infrastructure for AI agents",
        entity="steel-dev",
        url="https://example.com/steel-cloud",
        seen_date=TODAY,
        description=(
            "Same 'steel-dev' entity surfacing a second time today via Product Hunt — a "
            "good case for the dedup layer once it's been through the pipeline once."
        ),
    ),
]
