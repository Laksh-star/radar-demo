"""
The decision gate — real logic, not mocked. This is the cheapest place in
the whole pipeline to make a decision, which is the point: everything before
here (extraction, validation, dedup, triage) is designed to be inexpensive
per item; everything after here (deep dive, generation) is not, so the gate
exists to keep the expensive stages small.

It reads five things Jev returns, in this order:

  1. category_probabilities — how belief is spread across the buckets
  2. relevance_probabilities — how belief is spread across the score levels
  3. relevance_confidence — the model's own certainty about its score
  4. is_new_entrant (Noul)
  5. relevance_score

Items 2 and 3 are distributions, and they earn their place for a specific
reason: TypeSafe's docs say every question in a call is evaluated "in
parallel and in isolation". Independent questions can disagree, and a single
winning label per question hides the disagreement. Two rules act on it:

  * the unrelated veto — the score question can say "worth tracking" while
    the category question puts most of its belief on "this isn't in your
    space at all". Escalating then means paying for one question's opinion
    while ignoring the other's.

  * the high-priority tail — relevance_score is an expectation, and an
    expectation flattens a bimodal belief. 0.45 Noise / 0.10 Worth / 0.45
    High priority averages to roughly the same number as a confident "worth
    tracking", and means something entirely different. Missing a
    high-priority competitor is asymmetric: expensive to miss, cheap to
    check. So a fat tail on the top level escalates on its own, even when
    the mean is under the bar.

Two ordering decisions, both arguable, both deliberate:

The veto runs before the tail rescue. An item with heavy mass on both
"unrelated" and "high priority" is genuinely contradictory, and this gate
chooses to save the money.

The tail rescue runs *before* the confidence floor, which is the opposite of
where it first sat. With the floor first the rule was very nearly dead code:
measured against real headlines, the items with a fat high-priority tail are
almost exactly the items Jev is least confident about — five realistic
"stealth startup raises $40M", "browser vendor ships native agent API" style
signals all came back at 0.28-0.52 confidence with 0.31-0.62 of their belief
on the top level, and every one was killed by the floor before the tail was
ever consulted. But "this might be significant and the model can't tell" is
the strongest case for spending a cheap look, not the weakest. The floor
still does its job on everything without a fat tail.

Both thresholds are draggable in playground.py if you disagree.

Anything Jev doesn't supply is skipped rather than guessed: MockTriage
returns no distributions, so rules 2 and 3 don't fire and the gate behaves
exactly as it did before they existed.
"""

from __future__ import annotations

from dataclasses import dataclass

from models import Category, TriageResult

RELEVANCE_THRESHOLD = 1.0
CONFIDENCE_THRESHOLD = 0.6

NEW_ENTRANT_THRESHOLD = 0.7  # is_new_entrant confidence considered "genuinely new"
NEW_ENTRANT_RELEVANCE_THRESHOLD = 0.7  # lower relevance bar for confident new entrants

UNRELATED_VETO_THRESHOLD = 0.5  # P(unrelated) that overrides a passing relevance score
HIGH_PRIORITY_TAIL_THRESHOLD = 0.25  # P(top level) that escalates regardless of the mean


@dataclass(frozen=True)
class GateDecision:
    """Why, not just whether. pipeline.py used to re-derive the Noul case
    outside the gate to badge it; now the gate says which rule decided and
    everything downstream reads that instead of guessing."""

    escalate: bool
    reason: str  # low_confidence | unrelated_veto | high_priority_tail | new_entrant | relevance | below_bar
    detail: str  # one human sentence, for the CLI trace and the dashboards

    @property
    def via_new_entrant(self) -> bool:
        return self.reason == "new_entrant"


def unrelated_probability(triage: TriageResult) -> float | None:
    """How much belief Jev put on 'this isn't in your space', regardless of
    which option won. None when the provider reports no distribution."""
    if not triage.category_probabilities:
        return None
    return triage.category_probabilities.get(Category.UNRELATED.value, 0.0)


def high_priority_probability(triage: TriageResult) -> float | None:
    """Mass on the top scoring level. The level keys are the criteria indices
    as sent ("0","1","2"), so the top one is the highest key rather than a
    hardcoded "2" — change the criteria list and this still points at the top."""
    if not triage.relevance_probabilities:
        return None
    top_key = max(triage.relevance_probabilities, key=lambda k: int(k))
    return triage.relevance_probabilities[top_key]


def decide(triage: TriageResult) -> GateDecision:
    p_unrelated = unrelated_probability(triage)
    if p_unrelated is not None and p_unrelated >= UNRELATED_VETO_THRESHOLD:
        return GateDecision(
            False,
            "unrelated_veto",
            f"Choice put {p_unrelated:.0%} of its belief on 'unrelated' — over the "
            f"{UNRELATED_VETO_THRESHOLD:.0%} veto — so the category question disagrees with "
            f"the relevance score of {triage.relevance_score:.2f}, and the gate sides with it",
        )

    p_high = high_priority_probability(triage)
    if p_high is not None and p_high >= HIGH_PRIORITY_TAIL_THRESHOLD:
        return GateDecision(
            True,
            "high_priority_tail",
            f"Score's mean is {triage.relevance_score:.2f} at {triage.relevance_confidence:.0%} confidence, "
            f"but {p_high:.0%} of its belief sits on the top level — over the "
            f"{HIGH_PRIORITY_TAIL_THRESHOLD:.0%} tail bar. An expectation hides that; the distribution doesn't",
        )

    if triage.relevance_confidence < CONFIDENCE_THRESHOLD:
        return GateDecision(
            False,
            "low_confidence",
            f"relevance confidence {triage.relevance_confidence:.2f} is below the "
            f"{CONFIDENCE_THRESHOLD:.2f} floor — Jev is saying don't trust this answer",
        )

    if triage.is_new_entrant >= NEW_ENTRANT_THRESHOLD:
        if triage.relevance_score >= NEW_ENTRANT_RELEVANCE_THRESHOLD:
            return GateDecision(
                True,
                "new_entrant",
                f"Noul {triage.is_new_entrant:.2f} marks a genuine first sighting, which clears at "
                f"{NEW_ENTRANT_RELEVANCE_THRESHOLD:.2f} relevance instead of {RELEVANCE_THRESHOLD:.2f} "
                f"— it scored {triage.relevance_score:.2f}",
            )
        return GateDecision(
            False,
            "below_bar",
            f"Noul {triage.is_new_entrant:.2f} marks this a new entrant, but "
            f"{triage.relevance_score:.2f} is under even the lowered "
            f"{NEW_ENTRANT_RELEVANCE_THRESHOLD:.2f} bar",
        )

    if triage.relevance_score >= RELEVANCE_THRESHOLD:
        return GateDecision(
            True,
            "relevance",
            f"relevance {triage.relevance_score:.2f} clears the {RELEVANCE_THRESHOLD:.2f} bar",
        )
    return GateDecision(
        False,
        "below_bar",
        f"relevance {triage.relevance_score:.2f} is under the {RELEVANCE_THRESHOLD:.2f} bar and "
        f"Noul {triage.is_new_entrant:.2f} doesn't mark it as new",
    )


def should_escalate(triage: TriageResult) -> bool:
    """The original boolean interface, unchanged for anything that only
    needs the verdict."""
    return decide(triage).escalate
