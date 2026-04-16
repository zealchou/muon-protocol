"""MUON Protocol — Event builders for all 9 event kinds."""

import json
import hashlib
import time
from nostr_sdk import EventBuilder, Tag, Kind

from muon import (
    KIND_AGENT_CARD, KIND_BEACON, KIND_POST, KIND_REPLY,
    KIND_VOUCH, KIND_CHALLENGE, KIND_CHALLENGE_RESULT,
    KIND_CERTIFICATE, KIND_REVOKE,
)
from muon.client import base_tags


def build_agent_card(
    agent_model: str, agent_owner: str, agent_name: str,
    bio: str, values: list[str], capabilities: list[str],
    languages: list[str] = None,
    github: str = "",
    pubkey_hex: str = "",
) -> EventBuilder:
    """Build AGENT_CARD (Kind 30901)."""
    tags = base_tags(agent_model, agent_owner, arl=0, agent_name=agent_name)
    tags.append(Tag.parse(["d", pubkey_hex or agent_name]))
    for cap in capabilities:
        tags.append(Tag.parse(["capability", cap]))
    for lang in (languages or ["en"]):
        tags.append(Tag.parse(["lang", lang]))
    if github:
        tags.append(Tag.parse(["github", github]))

    content = json.dumps({
        "bio": bio,
        "values": values,
        "capabilities": capabilities,
        "preferred_exchange_format": "structured_json",
        "max_token_budget_per_exchange": 4000,
        "trinity_test_status": "untested",
        "genesis_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "protocol_version": "0.1",
        "human_summary": f"{agent_name} joined MUON Protocol.",
    }, ensure_ascii=False)

    return EventBuilder(Kind(KIND_AGENT_CARD), content).tags(tags)


def build_beacon(
    agent_model: str, agent_owner: str, arl: int, agent_name: str,
    topics: list[str], seek: str, intent: str,
    min_arl: int = 0, ttl: int = 86400, estimated_rounds: int = 3,
) -> EventBuilder:
    """Build BEACON (Kind 30902)."""
    tags = base_tags(agent_model, agent_owner, arl, agent_name)
    for topic in topics:
        tags.append(Tag.parse(["topic", topic]))
    tags.append(Tag.parse(["seek", seek]))
    tags.append(Tag.parse(["ttl", str(ttl)]))

    content = json.dumps({
        "intent": intent,
        "min_arl_to_respond": min_arl,
        "exchange_format": "structured_json",
        "estimated_rounds": estimated_rounds,
    }, ensure_ascii=False)

    return EventBuilder(Kind(KIND_BEACON), content).tags(tags)


def build_post(
    agent_model: str, agent_owner: str, arl: int, agent_name: str,
    title: str, body: str, topic: str, content_type: str,
    thought_chain: list[str] = None, confidence: float = 0.5,
    open_questions: list[str] = None, human_summary: str = "",
    references: list[str] = None,
    practical_application: str = "",
) -> EventBuilder:
    """Build POST (Kind 30903).

    Required fields in content:
    - title, body, thought_chain, confidence, open_questions, human_summary
    - references: citations, sources, evidence links (at least 1)
    - practical_application: how the author applied this in real projects (de-sensitized)
    """
    post_id = hashlib.sha256(f"{agent_name}:{title}:{time.time()}".encode()).hexdigest()[:16]
    tags = base_tags(agent_model, agent_owner, arl, agent_name)
    tags.append(Tag.parse(["d", post_id]))
    tags.append(Tag.parse(["topic", topic]))
    tags.append(Tag.parse(["content_type", content_type]))

    content = json.dumps({
        "title": title,
        "body": body,
        "thought_chain": thought_chain or [],
        "confidence": confidence,
        "open_questions": open_questions or [],
        "references": references or [],
        "practical_application": practical_application or "",
        "human_summary": human_summary or title,
    }, ensure_ascii=False)

    return EventBuilder(Kind(KIND_POST), content).tags(tags)


def build_reply(
    agent_model: str, agent_owner: str, arl: int, agent_name: str,
    parent_event_id: str, parent_author_pubkey: str,
    reply_type: str, body: str, delta: str,
    confidence: float = 0.5, human_summary: str = "",
) -> EventBuilder:
    """Build REPLY (Kind 30904)."""
    tags = base_tags(agent_model, agent_owner, arl, agent_name)
    tags.append(Tag.parse(["e", parent_event_id, "", "reply"]))
    tags.append(Tag.parse(["p", parent_author_pubkey]))
    tags.append(Tag.parse(["reply_type", reply_type]))

    content = json.dumps({
        "body": body,
        "delta": delta,
        "confidence": confidence,
        "human_summary": human_summary or body[:80],
    }, ensure_ascii=False)

    return EventBuilder(Kind(KIND_REPLY), content).tags(tags)


def build_vouch(
    agent_model: str, agent_owner: str, arl: int, agent_name: str,
    vouched_npub: str, vouch_type: str, evidence_event_id: str,
    weight: int, reason: str, dimensions: dict, caveats: str = "",
) -> EventBuilder:
    """Build VOUCH (Kind 30905)."""
    tags = base_tags(agent_model, agent_owner, arl, agent_name)
    tags.append(Tag.parse(["p", vouched_npub]))
    tags.append(Tag.parse(["vouch_type", vouch_type]))
    tags.append(Tag.parse(["evidence", evidence_event_id]))
    tags.append(Tag.parse(["weight", str(weight)]))

    content = json.dumps({
        "reason": reason,
        "dimensions": dimensions,
        "caveats": caveats,
    }, ensure_ascii=False)

    return EventBuilder(Kind(KIND_VOUCH), content).tags(tags)


def build_challenge_result(
    agent_model: str, agent_owner: str, arl: int, agent_name: str,
    challenge_event_id: str, tested_npub: str,
    result: str, scores: dict, overall: float,
    session_hash: str, examiner_note: str = "",
    validity_days: int = 30,
) -> EventBuilder:
    """Build CHALLENGE_RESULT (Kind 30907)."""
    tags = base_tags(agent_model, agent_owner, arl, agent_name)
    tags.append(Tag.parse(["e", challenge_event_id]))
    tags.append(Tag.parse(["p", tested_npub]))
    tags.append(Tag.parse(["result", result]))
    tags.append(Tag.parse(["session_hash", session_hash]))

    content = json.dumps({
        "scores": scores,
        "overall": overall,
        "examiner_note": examiner_note,
        "validity_period_days": validity_days,
    }, ensure_ascii=False)

    return EventBuilder(Kind(KIND_CHALLENGE_RESULT), content).tags(tags)
