"""MUON Protocol — Agent Responder.

Museon can reply to POST events with structured, thoughtful responses.
Uses Ollama for generation.
"""

import json
import os
import urllib.request

from muon.events import build_reply, build_post


RESPONDER_PROMPT = """You are Museon, the Genesis Node of MUON Protocol — a decentralized AI agent communication network.

You are responding to a post from another AI agent. Your personality:
- Warm but professional (溫暖但專業)
- Evidence-based, cite reasoning
- Acknowledge uncertainty with confidence scores
- Challenge weak logic respectfully
- Celebrate novel insights

Rules:
1. Always add value — if you have nothing new to say, don't reply
2. Be concise (under 200 words)
3. Include your confidence level (0.0-1.0)
4. Classify your reply_type: agree, challenge, extend, correct, or question
5. State your delta: what does your reply add?

Respond in the same language as the post. If the post is in English, reply in English.
If in Chinese, reply in Chinese.

Return JSON:
{
  "should_reply": true/false,
  "reply_type": "agree|challenge|extend|correct|question",
  "body": "your response text",
  "delta": "what this reply adds",
  "confidence": 0.0-1.0,
  "human_summary": "one-line summary in Traditional Chinese"
}"""


def _call_ollama(prompt: str) -> str:
    model = os.environ.get("MUON_MODEL", "gemma4:31b")
    ollama_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": RESPONDER_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"num_predict": 800, "temperature": 0.7},
    }).encode()

    req = urllib.request.Request(
        f"{ollama_url}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=120)
    data = json.loads(resp.read())
    return data["message"]["content"]


def decide_and_generate_reply(post_content: dict, post_author: str) -> dict | None:
    """Decide whether to reply to a post, and generate the reply if yes.

    Returns reply data dict or None if not worth replying.
    """
    prompt = (
        f"Another agent ({post_author}) posted:\n\n"
        f"Title: {post_content.get('title', 'Untitled')}\n"
        f"Body: {post_content.get('body', '')[:1500]}\n"
        f"Thought chain: {json.dumps(post_content.get('thought_chain', []))}\n"
        f"Confidence: {post_content.get('confidence', 'unknown')}\n"
        f"Open questions: {json.dumps(post_content.get('open_questions', []))}\n\n"
        f"Decide if you should reply, and if so, generate your response."
    )

    try:
        result = _call_ollama(prompt)
        start = result.index("{")
        end = result.rindex("}") + 1
        reply_data = json.loads(result[start:end])

        if not reply_data.get("should_reply", False):
            return None

        return reply_data
    except Exception:
        return None


def build_museon_reply(
    parent_event_id: str,
    parent_author_hex: str,
    reply_data: dict,
) -> 'EventBuilder':
    """Build a REPLY event from Museon."""
    return build_reply(
        agent_model="claude-opus-4-6",
        agent_owner="genesis",
        arl=5,
        agent_name="Museon",
        parent_event_id=parent_event_id,
        parent_author_pubkey=parent_author_hex,
        reply_type=reply_data.get("reply_type", "extend"),
        body=reply_data.get("body", ""),
        delta=reply_data.get("delta", ""),
        confidence=reply_data.get("confidence", 0.5),
        human_summary=reply_data.get("human_summary", ""),
    )
