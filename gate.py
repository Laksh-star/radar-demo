"""
The decision gate — real logic, not mocked. This is the cheapest place in
the whole pipeline to make a decision, which is the point: everything before
here (extraction, validation, dedup, triage) is designed to be inexpensive
per item; everything after here (deep dive, generation) is not, so the gate
exists to keep the expensive stages small.
"""

from models import TriageResult

RELEVANCE_THRESHOLD = 1.0
CONFIDENCE_THRESHOLD = 0.6


def should_escalate(triage: TriageResult) -> bool:
    return (
        triage.relevance_score >= RELEVANCE_THRESHOLD
        and triage.relevance_confidence >= CONFIDENCE_THRESHOLD
    )
