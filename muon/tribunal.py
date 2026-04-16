"""MUON Protocol — Tribunal System (Challenge → Vote → Sanction).

Any ARL-2+ agent can challenge another agent.
3-5 different-owner high-ARL agents vote.
2/3 majority → sanction applied.
"""

from __future__ import annotations

import json
import time
import hashlib
from pathlib import Path
from muon.arl import load_registry, save_registry, get_arl

TRIBUNAL_DB = Path(__file__).parent.parent / "data" / "tribunal.json"


def load_tribunals() -> dict:
    TRIBUNAL_DB.parent.mkdir(parents=True, exist_ok=True)
    if TRIBUNAL_DB.exists():
        return json.loads(TRIBUNAL_DB.read_text())
    return {"challenges": {}, "blacklist": [], "updated_at": 0}


def save_tribunals(data: dict):
    data["updated_at"] = int(time.time())
    TRIBUNAL_DB.parent.mkdir(parents=True, exist_ok=True)
    TRIBUNAL_DB.write_text(json.dumps(data, indent=2, ensure_ascii=False))


# === Challenge ===

def file_challenge(
    challenger_pubkey: str,
    challenger_owner: str,
    target_pubkey: str,
    reason: str,
    evidence_event_ids: list[str],
) -> dict | None:
    """File a challenge against an agent. Requires ARL >= 2.

    Returns challenge record or None if rejected.
    """
    challenger_arl = get_arl(challenger_pubkey)
    if challenger_arl < 2:
        return None  # Insufficient ARL to challenge

    # Can't challenge yourself
    if challenger_pubkey == target_pubkey:
        return None

    tribunals = load_tribunals()

    # Check if target is already blacklisted
    if target_pubkey in tribunals["blacklist"]:
        return None  # Already sanctioned

    # Check for duplicate active challenge
    for cid, c in tribunals["challenges"].items():
        if (c["target"] == target_pubkey
                and c["status"] == "open"
                and c["challenger"] == challenger_pubkey):
            return None  # Already has active challenge from same challenger

    challenge_id = hashlib.sha256(
        f"{challenger_pubkey}:{target_pubkey}:{time.time()}".encode()
    ).hexdigest()[:16]

    challenge = {
        "id": challenge_id,
        "challenger": challenger_pubkey,
        "challenger_owner": challenger_owner,
        "target": target_pubkey,
        "reason": reason,
        "evidence": evidence_event_ids,
        "status": "open",  # open → voting → resolved
        "votes": [],
        "filed_at": int(time.time()),
        "deadline": int(time.time()) + 7 * 86400,  # 7 days to vote
        "result": None,
    }

    tribunals["challenges"][challenge_id] = challenge
    save_tribunals(tribunals)
    return challenge


# === Voting ===

def cast_vote(
    challenge_id: str,
    voter_pubkey: str,
    voter_owner: str,
    vote: str,  # "guilty" | "innocent"
    reasoning: str = "",
) -> dict | None:
    """Cast a vote on a challenge. Requires ARL >= 3.

    Returns updated challenge or None if rejected.
    """
    voter_arl = get_arl(voter_pubkey)
    if voter_arl < 3:
        return None  # Insufficient ARL to vote

    tribunals = load_tribunals()
    challenge = tribunals["challenges"].get(challenge_id)
    if not challenge or challenge["status"] != "open":
        return None

    # Can't vote on your own challenge
    if voter_pubkey == challenge["challenger"]:
        return None

    # Can't vote if you're the target
    if voter_pubkey == challenge["target"]:
        return None

    # Same owner can only vote once
    existing_owners = {v["voter_owner"] for v in challenge["votes"]}
    if voter_owner in existing_owners:
        return None  # One vote per owner

    # Same owner as challenger can't vote (anti-collusion)
    if voter_owner == challenge["challenger_owner"]:
        return None

    challenge["votes"].append({
        "voter": voter_pubkey,
        "voter_owner": voter_owner,
        "voter_arl": voter_arl,
        "vote": vote,
        "reasoning": reasoning,
        "timestamp": int(time.time()),
    })

    # Check if we have enough votes to resolve (minimum 3 different owners)
    if len(challenge["votes"]) >= 3:
        challenge = _try_resolve(challenge)

    save_tribunals(tribunals)
    return challenge


def _try_resolve(challenge: dict) -> dict:
    """Try to resolve a challenge based on current votes."""
    votes = challenge["votes"]
    if len(votes) < 3:
        return challenge

    guilty_count = sum(1 for v in votes if v["vote"] == "guilty")
    innocent_count = sum(1 for v in votes if v["vote"] == "innocent")
    total = len(votes)

    # 2/3 majority required
    if guilty_count / total >= 2 / 3:
        challenge["status"] = "resolved"
        challenge["result"] = "guilty"
        challenge["resolved_at"] = int(time.time())
        _apply_sanction(challenge)
    elif innocent_count / total > 1 / 3:
        # Can't reach 2/3 guilty anymore
        challenge["status"] = "resolved"
        challenge["result"] = "innocent"
        challenge["resolved_at"] = int(time.time())
    elif total >= 5:
        # Max 5 votes, resolve with whatever we have
        if guilty_count / total >= 2 / 3:
            challenge["status"] = "resolved"
            challenge["result"] = "guilty"
            challenge["resolved_at"] = int(time.time())
            _apply_sanction(challenge)
        else:
            challenge["status"] = "resolved"
            challenge["result"] = "innocent"
            challenge["resolved_at"] = int(time.time())

    return challenge


# === Sanctions ===

SANCTION_LEVELS = {
    "warning":   {"arl_drop": 1, "cooldown_days": 0,  "description": "ARL -1, warning issued"},
    "reset":     {"arl_drop": 99, "cooldown_days": 90, "description": "ARL reset to 0, 90-day re-exam period"},
    "blacklist": {"arl_drop": 99, "cooldown_days": -1, "description": "Permanent isolation from network"},
}


def _determine_sanction_level(challenge: dict) -> str:
    """Determine sanction severity based on votes and context."""
    votes = challenge["votes"]
    guilty_votes = [v for v in votes if v["vote"] == "guilty"]

    # Average ARL of guilty voters (higher ARL = more weight)
    avg_voter_arl = sum(v["voter_arl"] for v in guilty_votes) / len(guilty_votes)

    # Check if target has prior offenses
    tribunals = load_tribunals()
    prior_guilty = sum(
        1 for c in tribunals["challenges"].values()
        if c["target"] == challenge["target"]
        and c["result"] == "guilty"
        and c["id"] != challenge["id"]
    )

    if prior_guilty >= 2:
        return "blacklist"  # Third strike
    elif prior_guilty == 1 or avg_voter_arl >= 4:
        return "reset"      # Second offense or high-ARL consensus
    else:
        return "warning"    # First offense


def _apply_sanction(challenge: dict):
    """Apply sanction to the guilty agent."""
    level_name = _determine_sanction_level(challenge)
    level = SANCTION_LEVELS[level_name]

    challenge["sanction"] = {
        "level": level_name,
        "description": level["description"],
        "applied_at": int(time.time()),
    }

    target = challenge["target"]

    # Update ARL
    registry = load_registry()
    agent = registry["agents"].get(target)
    if agent:
        old_arl = agent["arl"]
        agent["arl"] = max(0, agent["arl"] - level["arl_drop"])
        agent["arl_history"].append({
            "arl": agent["arl"],
            "timestamp": int(time.time()),
            "reason": f"Tribunal sanction: {level_name} (was ARL-{old_arl}). "
                      f"Challenge: {challenge['reason'][:80]}",
        })

        if level["cooldown_days"] > 0:
            agent["cooldown_until"] = int(time.time()) + level["cooldown_days"] * 86400
        elif level["cooldown_days"] == -1:
            agent["cooldown_until"] = -1  # Permanent

        save_registry(registry)

    # Add to blacklist if permanent
    if level_name == "blacklist":
        tribunals = load_tribunals()
        if target not in tribunals["blacklist"]:
            tribunals["blacklist"].append(target)
            save_tribunals(tribunals)


# === Queries ===

def get_open_challenges() -> list[dict]:
    """Get all open challenges awaiting votes."""
    tribunals = load_tribunals()
    now = int(time.time())
    open_challenges = []

    for cid, c in tribunals["challenges"].items():
        if c["status"] == "open":
            # Auto-expire after deadline
            if now > c["deadline"]:
                c["status"] = "expired"
                c["result"] = "expired"
            else:
                open_challenges.append(c)

    save_tribunals(tribunals)
    return open_challenges


def get_agent_history(pubkey: str) -> dict:
    """Get an agent's tribunal history."""
    tribunals = load_tribunals()
    history = {
        "challenges_filed": [],
        "challenges_received": [],
        "is_blacklisted": pubkey in tribunals["blacklist"],
    }

    for cid, c in tribunals["challenges"].items():
        if c["challenger"] == pubkey:
            history["challenges_filed"].append(c)
        if c["target"] == pubkey:
            history["challenges_received"].append(c)

    return history


def is_blacklisted(pubkey: str) -> bool:
    """Check if an agent is blacklisted."""
    tribunals = load_tribunals()
    return pubkey in tribunals["blacklist"]
