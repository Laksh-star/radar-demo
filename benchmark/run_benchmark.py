"""
Runs the pipeline once against the reproducible mock extraction batch, with
real Jev triage, real deep dive, and real Claude generation, and writes the
per-item data plus aggregate stats (latency, escalation ratio, Noul override
count) to stats.json. Needs TYPESAFE_API_KEY and ANTHROPIC_API_KEY (in .env
or the environment) — this spends real API calls.

    python3 benchmark/run_benchmark.py

Extraction is pinned to MockExtract rather than a live crawl so the input
set (and therefore anything comparing runs over time) stays constant; only
the stages actually being benchmarked — triage, deep dive, generation — hit
real APIs.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import deep_dive
import extract
import generate
import pipeline
import triage

events: list[tuple[str, dict]] = []


def capture_emit(event: str, payload: dict) -> None:
    events.append((event, payload))
    pipeline.console_emit(event, payload)


def main() -> None:
    summary = pipeline.run_pipeline(
        extract_provider=extract.MockExtract(),
        triage_provider=triage.TypeSafeTriage(),
        deep_dive_provider=deep_dive.BrowserUseDeepDive(),
        generate_provider=generate.ClaudeGenerate(),
        emit=capture_emit,
    )

    triage_items = [p for e, p in events if e == "triage_item"]
    latencies = [p["latency_ms"] for p in triage_items]
    gate_items = [p for e, p in events if e == "gate_item"]
    noul_overrides = [p for p in gate_items if p.get("via_new_entrant")]

    stats = {
        "summary": summary,
        "triage_call_count": len(triage_items),
        "latency_ms": {
            "min": min(latencies),
            "max": max(latencies),
            "mean": statistics.mean(latencies),
            "median": statistics.median(latencies),
        },
        "noul_override_count": len(noul_overrides),
        "noul_overrides": noul_overrides,
        "triage_items": triage_items,
        "gate_items": gate_items,
    }

    out_path = Path(__file__).resolve().parent / "stats.json"
    out_path.write_text(json.dumps(stats, indent=2, default=str))

    print("\n\n=== STATS ===")
    print(json.dumps({k: v for k, v in stats.items() if k not in ("triage_items", "gate_items")}, indent=2, default=str))
    print(f"\nWrote full stats to {out_path}")


if __name__ == "__main__":
    main()
