"""
The decision gate — real logic, not mocked. This is the cheapest place in
the whole pipeline to make a decision, which is the point: everything before
here (extraction, validation, dedup, triage) is designed to be inexpensive
per item; everything after here (deep dive, generation) is not, so the gate
exists to keep the expensive stages small.

Uses two of Jev's three judgments: Score (relevance_score) and its
confidence. It used to stop there — Noul (is_new_entrant) was requested,
displayed, and persisted, but never actually changed a decision. A confident
first-sighting of a genuinely new competitor is exactly the kind of thing
worth catching before it's built up the same "worth tracking" relevance a
familiar name would need, so a confident new entrant now clears the gate at
a lower relevance bar than a repost or a known name would.
"""

from models import TriageResult

RELEVANCE_THRESHOLD = 1.0
CONFIDENCE_THRESHOLD = 0.6

NEW_ENTRANT_THRESHOLD = 0.7  # is_new_entrant confidence considered "genuinely new"
NEW_ENTRANT_RELEVANCE_THRESHOLD = 0.7  # lower relevance bar for confident new entrants


def should_escalate(triage: TriageResult) -> bool:
    if triage.relevance_confidence < CONFIDENCE_THRESHOLD:
        return False
    if triage.is_new_entrant >= NEW_ENTRANT_THRESHOLD:
        return triage.relevance_score >= NEW_ENTRANT_RELEVANCE_THRESHOLD
    return triage.relevance_score >= RELEVANCE_THRESHOLD
