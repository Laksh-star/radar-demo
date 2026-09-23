"""
Stage 4 — Triage.

One call per item to Jev (TypeSafe AI's System One model), asking three
questions in parallel — category (Choice), relevance (Score), is_new_entrant
(Noul) — and getting a confidence-scored judgment back.

The response carries more than the three answers: a probability distribution
behind each Choice and Score, the legend the levels were scored against,
token usage, and the resolved model build. This used to be parsed off and
dropped; TriageResult now keeps all of it, so the distributions are
available to anything that wants to look at *how* certain the model was
rather than only what it picked.

`TriageProvider` is the interface: anything that can turn a RawSignal into a
TriageResult. Two implementations ship here:

  - TypeSafeTriage — the real thing. POSTs to TypeSafe AI's /v1/systemone.
    Needs TYPESAFE_API_KEY set.
  - MockTriage      — the original keyword heuristic. No key, no network.
    Useful for local runs/tests that shouldn't spend real API calls.

gate.py and everything after it only depends on the TriageResult shape, not
on which provider produced it.

Pick a provider with get_triage_provider(), which reads TRIAGE_PROVIDER
("typesafe" or "mock") from the environment. If unset, it defaults to
"typesafe" when TYPESAFE_API_KEY is present, otherwise "mock".
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod

import httpx

from models import Category, RawSignal, TriageResult


class TriageProvider(ABC):
    """Judges one RawSignal. Implementations are interchangeable — pipeline.py
    and everything downstream only ever sees the TriageResult they return."""

    @abstractmethod
    def triage(self, raw: RawSignal) -> TriageResult: ...


class TypeSafeTriage(TriageProvider):
    """Real call to TypeSafe AI's Jev model (System One)."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.typesafe.ai",
        timeout: float = 10.0,
    ) -> None:
        self.api_key = api_key or os.environ["TYPESAFE_API_KEY"]
        self.base_url = base_url
        self.timeout = timeout

    def triage(self, raw: RawSignal) -> TriageResult:
        resp = httpx.post(
            f"{self.base_url}/v1/systemone",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "state": raw.description,
                "model": "jev-latest",
                "questions": {
                    "category": {
                        "type": "choice",
                        "instructions": "Which competitive bucket does this fall in",
                        "criteria": {
                            "agent-framework": "AI agent orchestration or model platform",
                            "browser-automation": "Browser-controlling agents or tooling",
                            "dev-tooling": "Developer infrastructure adjacent to agents",
                            "unrelated": "Not relevant to AI agent tooling",
                        },
                    },
                    "relevance": {
                        "type": "score",
                        "instructions": "How significant a competitive signal this is",
                        "criteria": ["Noise", "Worth tracking", "High priority"],
                    },
                    "is_new_entrant": {
                        "type": "noul",
                        "instructions": "This is a genuinely new competitor, not a repost",
                    },
                },
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        body = resp.json()
        a = body["answers"]
        usage = body.get("usage") or {}
        return TriageResult(
            category=a["category"]["choice"],
            category_confidence=a["category"]["confidence"],
            relevance_score=a["relevance"]["score"],
            relevance_confidence=a["relevance"]["confidence"],
            is_new_entrant=a["is_new_entrant"]["noul"],
            # everything below is returned on every call whether you read it
            # or not; .get() throughout so an API that stops sending one of
            # them degrades to None instead of breaking the pipeline
            category_probabilities=a["category"].get("probabilities"),
            relevance_probabilities=a["relevance"].get("probabilities"),
            relevance_legend=a["relevance"].get("legend"),
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            model_version=body.get("model"),
        )


class MockTriage(TriageProvider):
    """Keyword heuristic standing in for a Jev call. No key, no network."""

    _RELEVANT_TERMS = {
        "agent",
        "agents",
        "browser",
        "browser-use",
        "llm",
        "model",
        "predictions",
        "typesafe",
        "jev",
        "automation",
        "developer",
        "infrastructure",
        "workers",
    }

    _UNRELATED_TERMS = {
        "note-taking",
        "planner",
        "habit",
        "game",
        "engine",
        "woodworking",
        "discussion",
    }

    @staticmethod
    def _keyword_hits(text: str, vocabulary: set[str]) -> int:
        lowered = text.lower()
        return sum(1 for term in vocabulary if term in lowered)

    def triage(self, raw: RawSignal) -> TriageResult:
        text = f"{raw.title} {raw.description}"
        relevant_hits = self._keyword_hits(text, self._RELEVANT_TERMS)
        unrelated_hits = self._keyword_hits(text, self._UNRELATED_TERMS)

        if unrelated_hits > 0:
            # deliberately checked first: a stray "agent" inside "no AI or agent
            # angle" shouldn't outrank an explicit "no developer tooling angle" —
            # exactly the kind of negation a keyword heuristic gets wrong and a
            # real Jev/LLM judgment call wouldn't.
            category = Category.UNRELATED
            category_confidence = 0.9
            relevance_score = 0.0
            relevance_confidence = 0.85
        elif "browser" in text.lower():
            category = Category.BROWSER_AUTOMATION
            category_confidence = 0.8
            relevance_score = 1.6 if relevant_hits >= 2 else 1.1
            relevance_confidence = 0.75
        elif "typesafe" in text.lower() or "jev" in text.lower() or "model" in text.lower():
            category = Category.AGENT_FRAMEWORK
            category_confidence = 0.82
            relevance_score = 1.7 if relevant_hits >= 2 else 1.2
            relevance_confidence = 0.78
        elif relevant_hits >= 1:
            category = Category.DEV_TOOLING
            category_confidence = 0.65
            relevance_score = 1.0
            relevance_confidence = 0.6
        else:
            category = Category.UNRELATED
            category_confidence = 0.7
            relevance_score = 0.2
            relevance_confidence = 0.6

        # a very light stand-in for "have we plausibly seen this entity narrative before"
        is_new_entrant = 0.85 if relevant_hits >= 2 else 0.4

        return TriageResult(
            category=category,
            category_confidence=category_confidence,
            relevance_score=relevance_score,
            relevance_confidence=relevance_confidence,
            is_new_entrant=is_new_entrant,
            # deliberately no probabilities, legend or usage: a keyword
            # heuristic has no distribution to report, and faking a
            # confident-looking one would misrepresent what a mock knows.
            # Consumers must handle None — which is also what makes the
            # difference visible when you switch providers.
            model_version="mock-keyword-heuristic",
        )


def get_triage_provider() -> TriageProvider:
    choice = os.environ.get("TRIAGE_PROVIDER")
    if choice is None:
        choice = "typesafe" if os.environ.get("TYPESAFE_API_KEY") else "mock"

    if choice == "typesafe":
        return TypeSafeTriage()
    if choice == "mock":
        return MockTriage()
    raise ValueError(f"Unknown TRIAGE_PROVIDER: {choice!r} (expected 'typesafe' or 'mock')")
