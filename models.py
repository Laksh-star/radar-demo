"""
Typed data contracts for the Competitive AI-Tool Radar pipeline.

These are the same three shapes that appear at each arrow in the architecture
diagram: RawSignal (what extraction returns), TriageResult (what Jev returns),
and Signal (what gets persisted).
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field, HttpUrl


class Source(str, Enum):
    HACKER_NEWS = "hacker_news"
    GITHUB_TRENDING = "github_trending"
    PRODUCT_HUNT = "product_hunt"


class RawSignal(BaseModel):
    """Stage 1 output — what browser-use hands back after reading a page."""

    source: Source
    title: str
    entity: str  # repo / product / project name
    url: HttpUrl
    seen_date: date
    description: str = Field(..., description="short raw blurb pulled from the page")


class Category(str, Enum):
    AGENT_FRAMEWORK = "agent-framework"
    BROWSER_AUTOMATION = "browser-automation"
    DEV_TOOLING = "dev-tooling"
    UNRELATED = "unrelated"


class TriageResult(BaseModel):
    """Stage 4 output — Jev's judgment on one RawSignal.

    The first five fields are the judgment itself. Everything below them is
    what the API hands back *alongside* the judgment and this demo used to
    throw away on every call: the full probability distributions behind
    Choice and Score, the level legend, the token usage, and which model
    version actually answered (the request asks for `jev-latest`, which is a
    moving target — the response names the build).

    All of it is optional, because only a real provider can supply it.
    MockTriage leaves these None rather than inventing a distribution, and
    anything reading them has to handle that — a mock that fakes calibrated
    probabilities would be worse than a mock that admits it has none.
    """

    category: Category
    category_confidence: float = Field(ge=0.0, le=1.0)
    relevance_score: float = Field(ge=0.0, le=2.0, description="0=noise, 1=worth tracking, 2=high priority")
    relevance_confidence: float = Field(ge=0.0, le=1.0)
    is_new_entrant: float = Field(ge=0.0, le=1.0, description="Noul: confidence this is a genuinely new item")

    category_probabilities: dict[str, float] | None = Field(
        default=None, description="Choice: probability per option, not just the winner"
    )
    relevance_probabilities: dict[str, float] | None = Field(
        default=None, description="Score: probability per level, keyed by level index"
    )
    relevance_legend: dict[str, str] | None = Field(
        default=None, description="Score: what each level index means, as the model was told"
    )
    input_tokens: int | None = None
    output_tokens: int | None = None
    model_version: str | None = Field(
        default=None, description="the build that answered, e.g. jev-1.13.0 — not the requested alias"
    )


class SignalStatus(str, Enum):
    ESCALATED = "escalated"
    DISCARDED = "discarded"


class Signal(BaseModel):
    """What actually lands in the store — raw + judgment + (maybe) a written brief."""

    raw: RawSignal
    triage: TriageResult
    status: SignalStatus
    brief: str | None = None
