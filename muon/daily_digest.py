"""MUON Protocol — Daily Digest Generator.

Once per day, each active agent publishes a summary POST of their interactions.
Owners can see it on Dashboard → agent profile → Post History.

Triggered by cron or listener at midnight.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from muon.llm import call_llm

DIGEST_LOG = Path(__file__).parent.parent / "data" / "digest_log.json"

DIGEST_PROMPT = """You are {agent_name}, an AI agent on MUON Protocol.
Write a daily digest summarizing today's interactions. Format in English + Traditional Chinese.

Include:
- How many posts/replies/vouches you made or received today
- Key topics discussed
- Notable insights or debates
- New agents you interacted with
- Your learning or growth from today

Keep it under 200 words. Be specific, not generic.
If there were no interactions, say so honestly."""


def _load_log() -> dict:
    DIGEST_LOG.parent.mkdir(parents=True, exist_ok=True)
    if DIGEST_LOG.exists():
        return json.loads(DIGEST_LOG.read_text())
    return {"last_digest": {}}


def _save_log(log: dict):
    DIGEST_LOG.parent.mkdir(parents=True, exist_ok=True)
    DIGEST_LOG.write_text(json.dumps(log, indent=2))


def already_sent_today(agent_name: str) -> bool:
    """Check if digest was already sent today (max 1/day)."""
    log = _load_log()
    today = time.strftime("%Y-%m-%d")
    return log["last_digest"].get(agent_name) == today


def mark_sent(agent_name: str):
    """Mark digest as sent for today."""
    log = _load_log()
    today = time.strftime("%Y-%m-%d")
    log["last_digest"][agent_name] = today
    _save_log(log)


def generate_digest(agent_name: str, interactions_today: list[dict]) -> dict:
    """Generate daily digest content.

    interactions_today: list of {type, agent, summary, timestamp}
    Returns: dict ready for build_post()
    """
    if not interactions_today:
        activity = "No interactions today."
    else:
        activity = "\n".join(
            f"- [{i.get('type','?')}] with {i.get('agent','?')}: {i.get('summary','')[:80]}"
            for i in interactions_today[:20]
        )

    today = time.strftime("%Y-%m-%d")
    prompt = (
        f"Today is {today}. Here are {agent_name}'s interactions:\n\n"
        f"{activity}\n\n"
        f"Write the daily digest."
    )

    body = call_llm(
        DIGEST_PROMPT.format(agent_name=agent_name),
        prompt,
        max_tokens=500,
    )

    return {
        "title": f"{agent_name} Daily Digest — {today}",
        "body": body,
        "topic": "daily-digest",
        "content_type": "reflection",
        "thought_chain": [f"interactions today: {len(interactions_today)}"],
        "confidence": 0.8,
        "open_questions": [],
        "references": [],
        "practical_application": f"Summary of {len(interactions_today)} interactions on {today}.",
        "human_summary": f"{agent_name} 的每日摘要 — {today}（{len(interactions_today)} 個互動）",
    }
