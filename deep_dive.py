"""
Stage 5 — Deep dive.

Runs only on items that survive the gate — the small remainder. A single
browser-use pass reads the item's own page (README, landing copy, pricing,
or discussion thread — whichever is there) and pulls out a couple of
concrete facts, which stage 6 then writes into the brief instead of just
rephrasing the stage-1 blurb. Because this only runs on survivors, it's one
of only two genuinely expensive stages in the pipeline (the other is
generate.py) — the whole point of the gate is to keep this stage small.

`DeepDiveProvider` is the interface: anything that can turn an escalated
RawSignal into a short block of enriched detail text. Two implementations:

  - BrowserUseDeepDive — real: a browser-use Agent opens the item's own url
    and summarizes what's actually on the page. Needs ANTHROPIC_API_KEY
    (drives the browsing agent, same as extract.py's real provider).
  - MockDeepDive — returns the raw signal's own stage-1 description
    unchanged. No key, no network, no browser. This makes the full-mock
    pipeline byte-identical to before this stage existed: generate.py sees
    the same text either way, just now routed through an explicit stage.

Pick a provider with get_deep_dive_provider(), which reads
DEEP_DIVE_PROVIDER ("browser-use" or "mock") from the environment. Like
extraction, this defaults to "mock" even when ANTHROPIC_API_KEY is set —
it's an extra browser-use pass per escalated item, so it needs an explicit
opt-in rather than piggybacking on a key set for another stage.
"""

from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod

from pydantic import BaseModel

from models import RawSignal

_MODEL = "claude-sonnet-5"
_MAX_STEPS = 10  # fail fast (and cheap) if a page traps the agent


class _DeepDiveResult(BaseModel):
    detail: str


class DeepDiveProvider(ABC):
    """Enriches one escalated RawSignal with a short block of extra detail.
    Implementations are interchangeable — generate.py only ever sees the
    detail string they return."""

    @abstractmethod
    def dive(self, raw: RawSignal) -> str: ...


class BrowserUseDeepDive(DeepDiveProvider):
    """Real deep dive: a browser-use Agent reads the item's own page."""

    def __init__(self, api_key: str | None = None, model: str = _MODEL, headless: bool = True) -> None:
        from browser_use import ChatAnthropic

        self.llm = ChatAnthropic(model=model, api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
        self.headless = headless

    def dive(self, raw: RawSignal) -> str:
        return asyncio.run(self._dive(raw))

    async def _dive(self, raw: RawSignal) -> str:
        from browser_use import Agent, BrowserProfile

        task = (
            f"Go to {raw.url} and read the page (README, landing copy, pricing, or "
            "discussion thread — whichever is there). In 2-3 sentences, using only "
            "text visible on the page: what it actually does, any pricing or "
            "licensing detail shown, and any sign of activity (stars, comments, "
            "launch date). Do not invent anything not on the page."
        )
        agent = Agent(
            task=task,
            llm=self.llm,
            output_model_schema=_DeepDiveResult,
            browser_profile=BrowserProfile(headless=self.headless),
        )
        history = await agent.run(max_steps=_MAX_STEPS)
        result = history.structured_output
        if result is None:
            raise RuntimeError(f"browser-use returned no structured output for deep dive on {raw.entity}")
        return result.detail


class MockDeepDive(DeepDiveProvider):
    """No-op enrichment: passes the stage-1 description straight through."""

    def dive(self, raw: RawSignal) -> str:
        return raw.description


def get_deep_dive_provider() -> DeepDiveProvider:
    choice = os.environ.get("DEEP_DIVE_PROVIDER", "mock")

    if choice == "browser-use":
        headless = os.environ.get("BROWSER_USE_HEADLESS", "true").strip().lower() not in ("false", "0", "no")
        return BrowserUseDeepDive(headless=headless)
    if choice == "mock":
        return MockDeepDive()
    raise ValueError(f"Unknown DEEP_DIVE_PROVIDER: {choice!r} (expected 'browser-use' or 'mock')")
