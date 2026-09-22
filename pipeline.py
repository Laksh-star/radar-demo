"""
Orchestrator — runs all 8 stages in order.

    python3 pipeline.py            # prints a trace to the terminal
    python3 dashboard.py           # runs it behind a live web view instead

`run_pipeline()` is the single source of truth for the pipeline itself; both
entry points call it and only differ in how they consume the events it emits
via the `emit(event_type, payload)` callback. Providers are pulled from
extract.py/triage.py/generate.py's own `get_*_provider()` unless passed in
explicitly (dashboard.py uses that to force a specific one from the UI).

Each run starts from a fresh local dashboard.sqlite (deleted and rebuilt) so
the trace is reproducible, except that one entity is deliberately pre-seeded
as "already seen from yesterday" so you can watch the dedup stage actually
skip something — in a real deployment that file would persist between runs
and grow over time instead of being reset.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Callable

from dotenv import load_dotenv

load_dotenv()  # populates os.environ from .env before any get_*_provider() reads it

import deep_dive
import extract
import gate
import generate
import store
import triage
from models import Signal, SignalStatus

Emit = Callable[[str, dict], None]


def seed_yesterday() -> None:
    """Pretend the pipeline already saw browser-use's GitHub Trending entry
    yesterday, so today's dedup stage has something real to skip."""
    store.mark_seen("browser-use", "github_trending", "2026-09-21")


def _noop_emit(event: str, payload: dict) -> None:
    pass


def run_pipeline(
    extract_provider: extract.ExtractionProvider | None = None,
    triage_provider: triage.TriageProvider | None = None,
    deep_dive_provider: deep_dive.DeepDiveProvider | None = None,
    generate_provider: generate.GenerateProvider | None = None,
    emit: Emit = _noop_emit,
) -> dict:
    """Runs all 8 stages once. Emits one event per stage boundary plus one
    per item at the stages worth watching live (dedup/triage/gate/deep
    dive/generate), and returns the final run summary dict."""
    extract_provider = extract_provider or extract.get_extract_provider()
    triage_provider = triage_provider or triage.get_triage_provider()
    deep_dive_provider = deep_dive_provider or deep_dive.get_deep_dive_provider()
    generate_provider = generate_provider or generate.get_generate_provider()

    store.reset()
    seed_yesterday()
    emit(
        "run_started",
        {
            "extract_provider": type(extract_provider).__name__,
            "triage_provider": type(triage_provider).__name__,
            "deep_dive_provider": type(deep_dive_provider).__name__,
            "generate_provider": type(generate_provider).__name__,
        },
    )

    emit("stage_start", {"stage": "extract", "index": 1})
    raw_items = extract_provider.extract()
    emit(
        "stage_done",
        {"stage": "extract", "count": len(raw_items), "sources": len({i.source for i in raw_items})},
    )

    emit("stage_start", {"stage": "validate", "index": 2})
    # items already come out of extract.py as RawSignal objects here, but in
    # production this is exactly where model_validate_json() would run
    # against the raw string browser-use returns, and a malformed item would
    # be dropped/retried rather than raise.
    validated = list(raw_items)
    emit("stage_done", {"stage": "validate", "count": len(validated)})

    emit("stage_start", {"stage": "dedup", "index": 3})
    new_items = []
    skipped = []
    for item in validated:
        if store.has_seen(item.entity, item.source.value):
            skipped.append(item)
            emit("dedup_item", {"entity": item.entity, "source": item.source.value, "status": "skip"})
        else:
            new_items.append(item)
            emit("dedup_item", {"entity": item.entity, "source": item.source.value, "status": "new"})
    emit("stage_done", {"stage": "dedup", "new": len(new_items), "skipped": len(skipped)})

    emit("stage_start", {"stage": "triage", "index": 4, "provider": type(triage_provider).__name__})
    judged: list[tuple] = []
    for item in new_items:
        started = time.perf_counter()
        result = triage_provider.triage(item)
        latency_ms = (time.perf_counter() - started) * 1000
        judged.append((item, result))
        emit(
            "triage_item",
            {
                "entity": item.entity,
                "source": item.source.value,
                "category": result.category.value,
                "category_confidence": result.category_confidence,
                "relevance_score": result.relevance_score,
                "relevance_confidence": result.relevance_confidence,
                "is_new_entrant": result.is_new_entrant,
                "latency_ms": latency_ms,
            },
        )
    emit("stage_done", {"stage": "triage", "count": len(judged)})

    emit("stage_start", {"stage": "gate", "index": 0})
    escalated = []
    discarded = []
    for item, t in judged:
        escalate = gate.should_escalate(t)
        (escalated if escalate else discarded).append((item, t))
        emit(
            "gate_item",
            {
                "entity": item.entity,
                "decision": "escalate" if escalate else "discard",
                "relevance_score": t.relevance_score,
                "relevance_confidence": t.relevance_confidence,
            },
        )
    emit("stage_done", {"stage": "gate", "escalated": len(escalated), "discarded": len(discarded)})

    emit(
        "stage_start",
        {"stage": "deep_dive", "index": 5, "provider": type(deep_dive_provider).__name__},
    )
    dived: list[tuple] = []
    for item, t in escalated:
        detail = deep_dive_provider.dive(item)
        dived.append((item, t, detail))
        emit("deep_dive_item", {"entity": item.entity, "source": item.source.value, "detail": detail})
    emit("stage_done", {"stage": "deep_dive", "count": len(dived)})

    emit(
        "stage_start",
        {"stage": "generate", "index": 6, "provider": type(generate_provider).__name__},
    )
    finished_signals: list[Signal] = []
    for item, t, detail in dived:
        brief = generate_provider.generate(item, t, detail)
        signal = Signal(raw=item, triage=t, status=SignalStatus.ESCALATED, brief=brief)
        finished_signals.append(signal)
        emit("brief_written", {"entity": item.entity, "brief": brief})
    for item, t in discarded:
        finished_signals.append(Signal(raw=item, triage=t, status=SignalStatus.DISCARDED, brief=None))
    emit("stage_done", {"stage": "generate", "count": len(escalated)})

    emit("stage_start", {"stage": "persist", "index": 7})
    for signal in finished_signals:
        store.persist(signal)
    emit("stage_done", {"stage": "persist", "count": len(finished_signals)})

    emit("stage_start", {"stage": "deliver", "index": 8})
    emit("stage_done", {"stage": "deliver", "surfaced": len(escalated)})

    summary = {
        "extracted": len(raw_items),
        "validated": len(validated),
        "deduped": len(new_items),
        "skipped": len(skipped),
        "triaged": len(judged),
        "escalated": len(escalated),
        "discarded": len(discarded),
    }
    emit("run_complete", summary)
    return summary


_STAGE_LABELS = {
    "extract": "stage 1 · extract",
    "validate": "stage 2 · validate (pydantic — real)",
    "dedup": "stage 3 · dedup (state store — real, dashboard.sqlite)",
    "triage": "stage 4 · triage",
    "gate": "gate · relevance >= 1.0 and confidence >= 0.6",
    "deep_dive": "stage 5 · deep dive",
    "generate": "stage 6 · generate",
    "persist": "stage 7 · persist (create_brief / get_trending_competitors — real, sqlite)",
    "deliver": "stage 8 · deliver",
}


def divider(label: str) -> None:
    print(f"\n{'─' * 8} {label} {'─' * (60 - len(label))}")


def console_emit(event: str, payload: dict) -> None:
    """Reproduces the original print-trace, driven by run_pipeline()'s events."""
    if event == "stage_start":
        label = _STAGE_LABELS[payload["stage"]]
        if "provider" in payload:
            label += f" ({payload['provider']}, see {payload['stage']}.py)"
        divider(label)
    elif event == "dedup_item" and payload["status"] == "skip":
        print(f"  SKIP  already seen: {payload['entity']} ({payload['source']})")
    elif event == "triage_item":
        print(
            f"  {payload['entity'][:32]:32s}  category={payload['category']:<18s} "
            f"relevance={payload['relevance_score']:.1f} conf={payload['relevance_confidence']:.2f}"
        )
    elif event == "deep_dive_item":
        print(f"  DIVE  {payload['entity']}\n    -> {payload['detail']}")
    elif event == "brief_written":
        print(f"  WROTE BRIEF  {payload['entity']}\n    -> {payload['brief']}")
    elif event == "stage_done":
        stage = payload["stage"]
        if stage == "extract":
            print(f"  extraction returned {payload['count']} raw items across {payload['sources']} source(s)")
        elif stage == "validate":
            print(f"  {payload['count']} / {payload['count']} items passed shape validation")
        elif stage == "dedup":
            print(f"  {payload['new']} new items to triage, {payload['skipped']} skipped")
        elif stage == "gate":
            print(f"  escalate: {payload['escalated']}   discard: {payload['discarded']}")
        elif stage == "deep_dive":
            print(f"  enriched {payload['count']} escalated item(s)")
        elif stage == "persist":
            print(f"  wrote {payload['count']} rows to dashboard.sqlite")
        elif stage == "deliver":
            print(f"  {payload['surfaced']} item(s) surfaced to the dashboard / newsletter queue")
    elif event == "run_complete":
        divider("run summary")
        print(f"  extracted:  {payload['extracted']}")
        print(f"  validated:  {payload['validated']}")
        print(f"  deduped:    {payload['deduped']}  ({payload['skipped']} skipped as already seen)")
        print(f"  triaged:    {payload['triaged']}")
        print(f"  escalated:  {payload['escalated']}  <- only these got a generation call")
        print(f"  discarded:  {payload['discarded']}")


def main() -> None:
    run_pipeline(emit=console_emit)

    divider("dashboard.sqlite contents")
    conn = sqlite3.connect(store.DB_PATH)
    rows = conn.execute(
        "SELECT entity, source, status, category, relevance_score FROM signals ORDER BY status, relevance_score DESC"
    ).fetchall()
    for entity, source, status, category, score in rows:
        print(f"  [{status:9s}] {entity:28s} {source:16s} {category:18s} score={score:.1f}")
    conn.close()


if __name__ == "__main__":
    main()
