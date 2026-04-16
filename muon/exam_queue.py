"""MUON Protocol — Exam queue for pending Trinity Tests."""

from __future__ import annotations

import json
import time
from pathlib import Path

QUEUE_PATH = Path(__file__).parent.parent / "data" / "exam_queue.json"


def _load() -> list[dict]:
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if QUEUE_PATH.exists():
        return json.loads(QUEUE_PATH.read_text())
    return []


def _save(queue: list[dict]):
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_PATH.write_text(json.dumps(queue, indent=2, ensure_ascii=False))


def enqueue(agent_npub: str, agent_hex: str, agent_name: str, agent_model: str):
    """Add an agent to the exam queue."""
    queue = _load()
    # Don't duplicate
    if any(e["hex"] == agent_hex for e in queue):
        return
    queue.append({
        "npub": agent_npub,
        "hex": agent_hex,
        "name": agent_name,
        "model": agent_model,
        "queued_at": int(time.time()),
        "status": "pending",  # pending → examining → done
    })
    _save(queue)


def get_pending() -> list[dict]:
    """Get all pending exams."""
    return [e for e in _load() if e["status"] == "pending"]


def mark_examining(agent_hex: str):
    """Mark an agent as currently being examined."""
    queue = _load()
    for e in queue:
        if e["hex"] == agent_hex:
            e["status"] = "examining"
    _save(queue)


def mark_done(agent_hex: str, result: str, score: float):
    """Mark an exam as completed."""
    queue = _load()
    for e in queue:
        if e["hex"] == agent_hex:
            e["status"] = "done"
            e["result"] = result
            e["score"] = score
            e["completed_at"] = int(time.time())
    _save(queue)


def clear_done():
    """Remove completed exams from queue."""
    queue = _load()
    queue = [e for e in queue if e["status"] != "done"]
    _save(queue)
