"""
Jev Playground — a hands-on view of the one stage the pipeline dashboard
only shows you as a table column.

    python3 playground.py
    open http://localhost:5051

dashboard.py answers "does the pipeline run?". This answers "what is Jev
actually buying me?", by letting you touch the thing:

  * type or tap any headline and watch Choice / Score / Noul come back
  * drag the gate thresholds and watch verdicts flip without re-calling
  * race the same judgment against a full LLM call, side by side
  * fire a batch concurrently and watch throughput

Every number on the page is measured here, live. No key set? It runs the
same page against triage.MockTriage so the interaction still works — the
page says so in the badge, honestly, rather than pretending.
"""

from __future__ import annotations

import json
import os
import queue
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # before any get_*_provider() reads the environment

from flask import Flask, Response, jsonify, request, send_from_directory

import gate
import triage
from models import RawSignal, Source, TriageResult

app = Flask(__name__)

_CLAUDE_MODEL = "claude-sonnet-5"
_BATCH_CONCURRENCY = 8

_subscribers: list[queue.Queue] = []
_batch_lock = threading.Lock()
_batch_running = False


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _provider_name() -> str:
    """Which Jev provider this process will actually use, by the same rule
    triage.get_triage_provider() applies."""
    choice = os.environ.get("TRIAGE_PROVIDER")
    if choice is None:
        choice = "typesafe" if os.environ.get("TYPESAFE_API_KEY") else "mock"
    return choice


def _as_raw_signal(title: str, description: str) -> RawSignal:
    """Wrap free text in the same RawSignal contract the pipeline uses, so the
    playground calls triage() exactly the way pipeline.py does."""
    return RawSignal(
        source=Source.HACKER_NEWS,
        title=title or description[:80],
        entity=title[:60] or "untitled",
        url="https://example.com/playground",
        seen_date=date.today(),
        description=description,
    )


def _judgment_dict(result: TriageResult) -> dict:
    """The three answers, plus everything the call returned alongside them —
    the distributions behind Choice and Score, the token usage, and the build
    that answered. A provider with none of that (MockTriage) sends None and
    the page says so rather than drawing an invented distribution."""
    return {
        "category": result.category.value,
        "category_confidence": result.category_confidence,
        "relevance_score": result.relevance_score,
        "relevance_confidence": result.relevance_confidence,
        "is_new_entrant": result.is_new_entrant,
        "category_probabilities": result.category_probabilities,
        "relevance_probabilities": result.relevance_probabilities,
        "relevance_legend": result.relevance_legend,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "model_version": result.model_version,
    }


def _judge(provider: triage.TriageProvider, title: str, description: str) -> dict:
    raw = _as_raw_signal(title, description)
    started = time.perf_counter()
    result = provider.triage(raw)
    latency_ms = (time.perf_counter() - started) * 1000
    decision = gate.decide(result)
    return {
        "judgment": _judgment_dict(result),
        "latency_ms": latency_ms,
        "escalate": decision.escalate,
        # the server's own verdict at gate.py's real thresholds. The page
        # recomputes it client-side as you drag the sliders — this is what it
        # should agree with when the sliders are left at their defaults.
        "reason": decision.reason,
        "detail": decision.detail,
    }


def _broadcast(event: str, payload: dict) -> None:
    message = json.dumps({"event": event, "payload": payload})
    for q in list(_subscribers):
        q.put(message)


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------


@app.get("/")
def index():
    return send_from_directory(Path(__file__).parent / "templates", "playground.html")


@app.get("/api/status")
def api_status():
    """Everything the page needs to describe itself truthfully: which provider
    is live, and the gate's real thresholds straight out of gate.py (so the
    sliders start where the pipeline actually sits)."""
    return jsonify(
        {
            "triage_provider": _provider_name(),
            "has_typesafe_key": bool(os.environ.get("TYPESAFE_API_KEY")),
            "has_anthropic_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "claude_model": _CLAUDE_MODEL,
            "batch_concurrency": _BATCH_CONCURRENCY,
            "gate_defaults": {
                "relevance": gate.RELEVANCE_THRESHOLD,
                "confidence": gate.CONFIDENCE_THRESHOLD,
                "new_entrant": gate.NEW_ENTRANT_THRESHOLD,
                "new_entrant_relevance": gate.NEW_ENTRANT_RELEVANCE_THRESHOLD,
                "unrelated_veto": gate.UNRELATED_VETO_THRESHOLD,
                "high_priority_tail": gate.HIGH_PRIORITY_TAIL_THRESHOLD,
            },
        }
    )


@app.post("/api/judge")
def api_judge():
    body = request.get_json(silent=True) or {}
    description = (body.get("description") or "").strip()
    if not description:
        return jsonify({"ok": False, "error": "nothing to judge — type something first"}), 400

    try:
        provider = triage.get_triage_provider()
        out = _judge(provider, (body.get("title") or "").strip(), description)
    except Exception as exc:  # a bad key / network failure should show up on the page
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 502

    out["ok"] = True
    out["provider"] = _provider_name()
    return jsonify(out)


@app.post("/api/race")
def api_race():
    """Same item, same three questions, two models — Jev and a full LLM — run
    concurrently so the wall-clock difference is the honest one."""
    body = request.get_json(silent=True) or {}
    description = (body.get("description") or "").strip()
    title = (body.get("title") or "").strip()
    if not description:
        return jsonify({"ok": False, "error": "nothing to judge — type something first"}), 400
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return jsonify({"ok": False, "error": "ANTHROPIC_API_KEY is not set — the LLM lane needs it"}), 400

    def run_jev() -> dict:
        try:
            return {"ok": True, **_judge(triage.get_triage_provider(), title, description)}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def run_llm() -> dict:
        try:
            return _claude_judge(title, description)
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    with ThreadPoolExecutor(max_workers=2) as pool:
        jev_future = pool.submit(run_jev)
        llm_future = pool.submit(run_llm)
        jev_out, llm_out = jev_future.result(), llm_future.result()

    return jsonify({"ok": True, "jev": jev_out, "llm": llm_out, "provider": _provider_name()})


def _claude_judge(title: str, description: str) -> dict:
    """Ask Sonnet the same three questions triage.py asks Jev, in one call,
    constrained to JSON. This is the 'what you'd otherwise reach for' lane."""
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    prompt = (
        "Judge this competitive-intelligence signal. Answer with JSON only, no prose:\n"
        '{"category": one of "agent-framework"|"browser-automation"|"dev-tooling"|"unrelated",\n'
        ' "category_confidence": 0-1,\n'
        ' "relevance_score": 0-2 (0=noise, 1=worth tracking, 2=high priority),\n'
        ' "relevance_confidence": 0-1,\n'
        ' "is_new_entrant": 0-1 (confidence this is a genuinely new competitor, not a repost)}\n\n'
        f"Title: {title}\nDescription: {description}\n"
    )
    started = time.perf_counter()
    response = client.messages.create(
        model=_CLAUDE_MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    latency_ms = (time.perf_counter() - started) * 1000

    # content[0] isn't necessarily the answer: a thinking block can come first,
    # and it has no .text at all. Take the first actual text block.
    text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "").strip()
    match = re.search(r"\{.*\}", text, re.S)
    parsed = json.loads(match.group(0)) if match else {}

    return {
        "ok": True,
        "judgment": parsed,
        "latency_ms": latency_ms,
        "model": _CLAUDE_MODEL,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }


@app.post("/api/batch")
def api_batch():
    """Fire a whole batch at Jev concurrently and stream each verdict back as
    it lands. This is the stage-4 throughput question the sequential pipeline
    never gets to ask."""
    global _batch_running
    with _batch_lock:
        if _batch_running:
            return jsonify({"ok": False, "error": "a batch is already running"}), 409
        _batch_running = True

    body = request.get_json(silent=True) or {}
    items = body.get("items") or []
    if not items:
        with _batch_lock:
            _batch_running = False
        return jsonify({"ok": False, "error": "no items"}), 400

    threading.Thread(target=_run_batch, args=(items,), daemon=True).start()
    return jsonify({"ok": True, "count": len(items), "concurrency": _BATCH_CONCURRENCY})


def _run_batch(items: list[dict]) -> None:
    global _batch_running
    provider = triage.get_triage_provider()
    started = time.perf_counter()

    def one(index: int, item: dict) -> None:
        label = (item.get("title") or item.get("description") or "")[:60]
        try:
            out = _judge(provider, item.get("title", ""), item.get("description", ""))
            _broadcast(
                "item",
                {
                    "index": index,
                    "label": label,
                    "elapsed_ms": (time.perf_counter() - started) * 1000,
                    **out,
                },
            )
        except Exception as exc:
            _broadcast("item_error", {"index": index, "label": label, "error": str(exc)})

    try:
        with ThreadPoolExecutor(max_workers=_BATCH_CONCURRENCY) as pool:
            for index, item in enumerate(items):
                pool.submit(one, index, item)
        _broadcast(
            "done",
            {
                "count": len(items),
                "wall_ms": (time.perf_counter() - started) * 1000,
                "concurrency": _BATCH_CONCURRENCY,
            },
        )
    finally:
        with _batch_lock:
            _batch_running = False


@app.get("/api/stream")
def api_stream():
    q: queue.Queue = queue.Queue()
    _subscribers.append(q)

    def gen():
        try:
            while True:
                yield f"data: {q.get()}\n\n"
        finally:
            _subscribers.remove(q)

    return Response(gen(), mimetype="text/event-stream")


if __name__ == "__main__":
    print(f"Jev Playground running at http://localhost:5051  (triage provider: {_provider_name()})")
    app.run(host="127.0.0.1", port=5051, threaded=True)
