"""
Local web dashboard — a live view of the pipeline anyone can open in a
browser and watch run stage by stage, with a dedicated panel for Jev's
per-item Choice/Score/Noul judgments as they come in.

    python3 dashboard.py
    open http://localhost:5050

This doesn't replace pipeline.py's CLI trace — both call the same
run_pipeline() in pipeline.py, just with a different `emit` callback. Here,
emit() broadcasts each event over Server-Sent Events to any open browser tab.
"""

from __future__ import annotations

import json
import os
import queue
import sqlite3
import threading
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # populates os.environ from .env before any get_*_provider() reads it

from flask import Flask, Response, jsonify, request, send_from_directory

import extract
import generate
import pipeline
import store
import triage

app = Flask(__name__)

_lock = threading.Lock()
_running = False
_subscribers: list[queue.Queue] = []


def _broadcast(event: str, payload: dict) -> None:
    message = json.dumps({"event": event, "payload": payload})
    for q in list(_subscribers):
        q.put(message)


def _build_extract_provider(choice: str) -> extract.ExtractionProvider:
    return extract.BrowserUseExtract() if choice == "browser-use" else extract.MockExtract()


def _build_triage_provider(choice: str) -> triage.TriageProvider:
    return triage.TypeSafeTriage() if choice == "typesafe" else triage.MockTriage()


def _build_generate_provider(choice: str) -> generate.GenerateProvider:
    return generate.ClaudeGenerate() if choice == "claude" else generate.MockGenerate()


def _run_in_background(extract_choice: str, triage_choice: str, generate_choice: str) -> None:
    global _running
    try:
        pipeline.run_pipeline(
            extract_provider=_build_extract_provider(extract_choice),
            triage_provider=_build_triage_provider(triage_choice),
            generate_provider=_build_generate_provider(generate_choice),
            emit=_broadcast,
        )
    except Exception as exc:
        _broadcast("run_error", {"message": str(exc)})
    finally:
        with _lock:
            _running = False


@app.get("/")
def index():
    return send_from_directory(Path(__file__).parent / "templates", "index.html")


@app.get("/api/defaults")
def api_defaults():
    return jsonify(
        {
            "has_anthropic_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "has_typesafe_key": bool(os.environ.get("TYPESAFE_API_KEY")),
        }
    )


@app.post("/api/run")
def api_run():
    global _running
    with _lock:
        if _running:
            return jsonify({"ok": False, "error": "a run is already in progress"}), 409
        _running = True

    body = request.get_json(silent=True) or {}
    thread = threading.Thread(
        target=_run_in_background,
        args=(
            body.get("extract", "mock"),
            body.get("triage", "mock"),
            body.get("generate", "mock"),
        ),
        daemon=True,
    )
    thread.start()
    return jsonify({"ok": True})


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


@app.get("/api/dashboard")
def api_dashboard():
    conn = sqlite3.connect(store.DB_PATH)
    rows = conn.execute(
        "SELECT entity, source, status, category, relevance_score, brief "
        "FROM signals ORDER BY status, relevance_score DESC"
    ).fetchall()
    conn.close()
    return jsonify(
        [
            {
                "entity": entity,
                "source": source,
                "status": status,
                "category": category,
                "relevance_score": score,
                "brief": brief,
            }
            for entity, source, status, category, score, brief in rows
        ]
    )


if __name__ == "__main__":
    print("Dashboard running at http://localhost:5050")
    app.run(host="127.0.0.1", port=5050, threaded=True)
