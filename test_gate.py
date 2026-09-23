"""
Boundary tests for gate.py — every threshold at, just under, and just over,
plus the ordering decisions between rules.

    python3 test_gate.py

No pytest needed and no API key: these run against hand-built TriageResults,
because the point is the decision logic, not the model. Worth having now
that the gate reads five things in a specific order and templates/playground.html
mirrors the same rules in JavaScript — these are what keep the two honest.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gate
from models import Category, TriageResult

def T(**kw):
    base = dict(category=Category.BROWSER_AUTOMATION, category_confidence=0.9,
                relevance_score=1.2, relevance_confidence=0.8, is_new_entrant=0.3)
    base.update(kw); return TriageResult(**base)

def dist(unrel=0.0, other=None):
    other = other if other is not None else 1.0 - unrel
    return {"unrelated": unrel, "browser-automation": other, "agent-framework": 0.0, "dev-tooling": 0.0}

cases = [
    # name, result, expected escalate, expected reason
    ("no distributions at all -> legacy path, escalates on score",
     T(), True, "relevance"),
    ("no distributions, below bar -> legacy discard",
     T(relevance_score=0.9), False, "below_bar"),
    # the tail deliberately outranks the confidence floor: measured against real
    # headlines, a fat top-level tail and low confidence arrive together, so a
    # floor-first order made the tail rule nearly unreachable. See gate.py.
    ("fat tail outranks the confidence floor — 'might be big, can't tell' is a reason to look",
     T(relevance_confidence=0.59, relevance_probabilities={"0":0.1,"1":0.1,"2":0.8}), True, "high_priority_tail"),
    ("low confidence with a thin tail still discards",
     T(relevance_confidence=0.59, relevance_probabilities={"0":0.5,"1":0.4,"2":0.1}), False, "low_confidence"),
    ("low confidence with no distributions at all still discards",
     T(relevance_confidence=0.59), False, "low_confidence"),
    ("veto fires exactly at 0.50",
     T(category_probabilities=dist(0.50)), False, "unrelated_veto"),
    ("veto does not fire at 0.49",
     T(category_probabilities=dist(0.49)), True, "relevance"),
    ("veto beats a passing score",
     T(relevance_score=1.9, category_probabilities=dist(0.6)), False, "unrelated_veto"),
    ("veto beats the high-priority tail (documented ordering)",
     T(relevance_score=0.5, category_probabilities=dist(0.7),
       relevance_probabilities={"0":0.3,"1":0.1,"2":0.6}), False, "unrelated_veto"),
    ("tail fires exactly at 0.25, under the relevance bar",
     T(relevance_score=0.4, relevance_probabilities={"0":0.55,"1":0.20,"2":0.25}), True, "high_priority_tail"),
    ("tail does not fire at 0.24",
     T(relevance_score=0.4, relevance_probabilities={"0":0.56,"1":0.20,"2":0.24}), False, "below_bar"),
    ("bimodal item the mean flattens: 0.45/0.10/0.45 -> escalates on the tail",
     T(relevance_score=1.0, relevance_probabilities={"0":0.45,"1":0.10,"2":0.45}), True, "high_priority_tail"),
    ("tail rescues below even the new-entrant bar",
     T(relevance_score=0.2, is_new_entrant=0.9,
       relevance_probabilities={"0":0.6,"1":0.1,"2":0.3}), True, "high_priority_tail"),
    ("noul path still works when distributions are present but quiet",
     T(relevance_score=0.8, is_new_entrant=0.85, category_probabilities=dist(0.1),
       relevance_probabilities={"0":0.2,"1":0.7,"2":0.1}), True, "new_entrant"),
    ("noul path still fails under the lowered bar",
     T(relevance_score=0.6, is_new_entrant=0.85, category_probabilities=dist(0.1),
       relevance_probabilities={"0":0.5,"1":0.4,"2":0.1}), False, "below_bar"),
    ("top level derived from highest key, not hardcoded '2'",
     T(relevance_score=0.3, relevance_probabilities={"0":0.4,"1":0.2,"2":0.1,"3":0.3}), True, "high_priority_tail"),
    ("category_probabilities present but no 'unrelated' key -> treated as 0",
     T(category_probabilities={"browser-automation":1.0}), True, "relevance"),
]

fails = 0
for name, result, want_esc, want_reason in cases:
    d = gate.decide(result)
    ok = (d.escalate == want_esc and d.reason == want_reason)
    if not ok:
        fails += 1
        print(f"FAIL  {name}\n      got escalate={d.escalate} reason={d.reason!r}\n      want escalate={want_esc} reason={want_reason!r}")
    else:
        print(f"pass  {name}")
    assert gate.should_escalate(result) == d.escalate, "bool wrapper disagrees with decide()"

print(f"\n{len(cases)-fails}/{len(cases)} passed")
sys.exit(1 if fails else 0)
