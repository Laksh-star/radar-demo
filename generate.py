"""
Stage 6 — Generation.

In production this is a full call to a System-2 model (Sonnet), given the
enriched detail from stage 5's browser-use deep dive, writing the actual
brief paragraph.

`GenerateProvider` is the interface: anything that can turn an escalated
RawSignal + its TriageResult into a brief paragraph. Two implementations:

  - ClaudeGenerate — the real thing. Calls the Anthropic API.
  - MockGenerate    — the original templated placeholder. No key, no
    network. Useful for local runs/tests that shouldn't spend real calls.

Pick a provider with get_generate_provider(), which reads GENERATE_PROVIDER
("claude" or "mock") from the environment. If unset, it defaults to
"claude" when ANTHROPIC_API_KEY is present, otherwise "mock".
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod

from models import RawSignal, TriageResult

_MODEL = "claude-sonnet-5"


class GenerateProvider(ABC):
    """Writes the brief paragraph for one escalated signal. Implementations
    are interchangeable — pipeline.py only ever sees the string they return."""

    @abstractmethod
    def generate(self, raw: RawSignal, triage: TriageResult) -> str: ...


class ClaudeGenerate(GenerateProvider):
    """Real call to the Anthropic API."""

    def __init__(self, api_key: str | None = None, model: str = _MODEL) -> None:
        import anthropic

        self.client = anthropic.Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
        self.model = model

    def generate(self, raw: RawSignal, triage: TriageResult) -> str:
        prompt = (
            "Write one short paragraph (2-3 sentences, no preamble) for a "
            "competitive-intelligence dashboard, explaining why this signal is "
            "worth tracking.\n\n"
            f"Entity: {raw.entity}\n"
            f"Source: {raw.source.value.replace('_', ' ')}\n"
            f"Raw description: {raw.description.strip()}\n"
            f"Category: {triage.category.value}\n"
            f"Relevance score: {triage.relevance_score:.1f}/2.0 "
            f"(confidence {triage.relevance_confidence:.0%})\n"
        )
        response = self.client.messages.create(
            model=self.model,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()


class MockGenerate(GenerateProvider):
    """Templated placeholder brief. No key, no network."""

    def generate(self, raw: RawSignal, triage: TriageResult) -> str:
        return (
            f"{raw.entity} ({raw.source.value.replace('_', ' ')}) is worth tracking: "
            f"{raw.description.strip()} Flagged as {triage.category.value} with a "
            f"relevance score of {triage.relevance_score:.1f}/2.0 "
            f"(confidence {triage.relevance_confidence:.0%})."
        )


def get_generate_provider() -> GenerateProvider:
    choice = os.environ.get("GENERATE_PROVIDER")
    if choice is None:
        choice = "claude" if os.environ.get("ANTHROPIC_API_KEY") else "mock"

    if choice == "claude":
        return ClaudeGenerate()
    if choice == "mock":
        return MockGenerate()
    raise ValueError(f"Unknown GENERATE_PROVIDER: {choice!r} (expected 'claude' or 'mock')")
