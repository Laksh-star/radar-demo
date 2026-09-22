"""
Stage 1 — Extraction.

`ExtractionProvider` is the interface: anything that can hand back a batch of
RawSignal items for the pipeline to validate. Two implementations:

  - BrowserUseExtract — the real thing. A browser-use Agent drives an
    isolated headless Chromium session (its own temp profile, not the user's
    real browser) across Hacker News and GitHub Trending, and returns
    structured items via browser-use's own output-schema support. Needs
    ANTHROPIC_API_KEY (used to drive the browsing agent itself — this is
    unrelated to Jev, which only judges items after they're extracted).
    Product Hunt is NOT included here — see _LIVE_SOURCE_URLS below.
  - MockExtract — returns the canned sample_sources.py batch (all 3
    sources, Product Hunt included). No key, no network, no browser. Useful
    for local runs/tests that shouldn't spend real API calls or take the
    ~30-60s a live crawl takes.

gate.py, triage.py, and everything after this only depend on the RawSignal
shape, not on how it was produced.

Pick a provider with get_extract_provider(), which reads EXTRACT_PROVIDER
("browser-use" or "mock") from the environment. Unlike triage/generate,
this one defaults to "mock" even when ANTHROPIC_API_KEY is set — a live
crawl is slow (~30-90s) and spends several LLM calls per run, so it needs
an explicit opt-in rather than piggybacking on a key set for another stage.
"""

from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod
from datetime import date

from pydantic import BaseModel

from models import RawSignal, Source
from sample_sources import RAW_SIGNALS

_MODEL = "claude-sonnet-5"

_LIVE_SOURCE_URLS: dict[Source, str] = {
    Source.HACKER_NEWS: "https://news.ycombinator.com/",
    Source.GITHUB_TRENDING: "https://github.com/trending",
    # Product Hunt is deliberately excluded from the live crawl: it sits
    # behind a Cloudflare "verify you're human" challenge that headless
    # browser-use gets stuck on indefinitely (observed 12+ steps with no
    # resolution). We don't attempt to click through bot-detection
    # challenges, so this source stays on MockExtract's sample data only.
}

_ITEMS_PER_SOURCE = 4
_MAX_STEPS_PER_SOURCE = 15  # fail fast (and cheap) if a source's page ever traps the agent


class _ExtractedItem(BaseModel):
    title: str
    entity: str
    url: str
    description: str


class _ExtractionBatch(BaseModel):
    items: list[_ExtractedItem]


class ExtractionProvider(ABC):
    """Returns today's raw signals. Implementations are interchangeable —
    pipeline.py only ever sees the RawSignal list they return."""

    @abstractmethod
    def extract(self) -> list[RawSignal]: ...


class BrowserUseExtract(ExtractionProvider):
    """Real extraction: a browser-use Agent reads each source live."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = _MODEL,
        headless: bool = True,
        items_per_source: int = _ITEMS_PER_SOURCE,
    ) -> None:
        from browser_use import ChatAnthropic

        self.llm = ChatAnthropic(model=model, api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
        self.headless = headless
        self.items_per_source = items_per_source

    def extract(self) -> list[RawSignal]:
        return asyncio.run(self._extract_all())

    async def _extract_all(self) -> list[RawSignal]:
        raw_items: list[RawSignal] = []
        today = date.today()
        for source, url in _LIVE_SOURCE_URLS.items():
            batch = await self._extract_one(source, url)
            for item in batch.items:
                raw_items.append(
                    RawSignal(
                        source=source,
                        title=item.title,
                        entity=item.entity,
                        url=item.url,
                        seen_date=today,
                        description=item.description,
                    )
                )
        return raw_items

    async def _extract_one(self, source: Source, url: str) -> _ExtractionBatch:
        from browser_use import Agent, BrowserProfile

        task = (
            f"Go to {url} and list the top {self.items_per_source} entries currently shown "
            "on the page (top posts / trending repos / featured launches, whichever applies "
            "here). For each entry return: title (exactly as shown on the page), entity (the "
            "product, repo, or project name), url (the direct link for that specific entry, "
            "not the site's own homepage), and description (a 1-2 sentence blurb using only "
            "text visible on the page). Do not judge relevance or skip anything for being "
            "off-topic — return every entry unfiltered; a separate system decides what "
            "matters later."
        )
        agent = Agent(
            task=task,
            llm=self.llm,
            output_model_schema=_ExtractionBatch,
            browser_profile=BrowserProfile(headless=self.headless),
        )
        history = await agent.run(max_steps=_MAX_STEPS_PER_SOURCE)
        result = history.structured_output
        if result is None:
            raise RuntimeError(f"browser-use returned no structured output for {source.value}")
        return result


class MockExtract(ExtractionProvider):
    """Canned sample batch. No key, no network, no browser."""

    def extract(self) -> list[RawSignal]:
        return list(RAW_SIGNALS)


def get_extract_provider() -> ExtractionProvider:
    choice = os.environ.get("EXTRACT_PROVIDER", "mock")

    if choice == "browser-use":
        # headless by default (the normal way to run this); set
        # BROWSER_USE_HEADLESS=false to watch a real Chrome window navigate
        # the three sources live instead of trusting the log output.
        headless = os.environ.get("BROWSER_USE_HEADLESS", "true").strip().lower() not in ("false", "0", "no")
        return BrowserUseExtract(headless=headless)
    if choice == "mock":
        return MockExtract()
    raise ValueError(f"Unknown EXTRACT_PROVIDER: {choice!r} (expected 'browser-use' or 'mock')")
