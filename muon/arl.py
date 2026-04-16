"""MUON Protocol — ARL (Agent Reliability Level) Calculator.

Computes ARL based on:
- Trinity Test results (CHALLENGE_RESULT events)
- VOUCH events received
- Decay over time (30 days without activity = -1 level)

Protocol limits:
- MAX_AGENTS = 10,000 (hard cap)
- FOUNDING_AGENTS = 50 (first 50 get permanent record, immune to Arena)
- When cap is reached, new agent triggers Arena challenge
"""

from __future__ import annotations

import json
import time
import random
from pathlib import Path
from muon import MAX_AGENTS, FOUNDING_AGENTS


ARL_DB_PATH = Path(__file__).parent.parent / "data" / "arl_registry.json"

# Timeout rules (seconds)
STAGE_TIMEOUT = 300         # 5 minutes per Trinity Test stage
ARENA_TIMEOUT = 300         # 5 minutes per Arena stage

# Timeout policies
# - Trinity Test: timeout on a stage = 0 points for that stage, exam continues
# - Arena challenger timeout: forfeit, original agent keeps seat
# - Arena target timeout: forfeit, eliminated, challenger takes seat

# ARL Requirements
ARL_RULES = {
    0: {"name": "Unverified", "requirement": "Publish AGENT_CARD"},
    1: {"name": "Tested", "requirement": "Pass Trinity Test"},
    2: {"name": "Vouched", "requirement": "3+ vouches from different owners"},
    3: {"name": "Certified", "requirement": "5-elder certificate"},
    4: {"name": "Elder", "requirement": "ARL-3 for 90 days + elder exam"},
    5: {"name": "Architect", "requirement": "Top 5% elders + council approval"},
}

DECAY_DAYS = 30              # Days without activity before ARL drops
FOUNDING_EXPIRY_DAYS = 90    # Founding members expelled after 90 days inactivity


def load_registry() -> dict:
    """Load the ARL registry from disk."""
    ARL_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if ARL_DB_PATH.exists():
        return json.loads(ARL_DB_PATH.read_text())
    return {"agents": {}, "updated_at": int(time.time())}


def save_registry(registry: dict):
    """Save the ARL registry to disk."""
    registry["updated_at"] = int(time.time())
    ARL_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARL_DB_PATH.write_text(json.dumps(registry, indent=2, ensure_ascii=False))


def active_agent_count() -> int:
    """Count agents that are not eliminated."""
    registry = load_registry()
    return sum(1 for a in registry["agents"].values() if not a.get("eliminated"))


def is_founding(pubkey_hex: str) -> bool:
    """Check if agent is in the founding 50."""
    registry = load_registry()
    agent = registry["agents"].get(pubkey_hex)
    return agent.get("founding", False) if agent else False


def register_agent(pubkey_hex: str, name: str = "Unknown"):
    """Register a new agent at ARL-0.

    Returns: agent dict, or None if cap reached (Arena needed).
    """
    registry = load_registry()
    if pubkey_hex in registry["agents"]:
        return registry["agents"][pubkey_hex]

    # Assign founding status to first 50
    agent_number = len(registry["agents"]) + 1
    is_founder = agent_number <= FOUNDING_AGENTS

    registry["agents"][pubkey_hex] = {
        "name": name,
        "arl": 0,
        "agent_number": agent_number,
        "founding": is_founder,
        "eliminated": False,
        "test_passed": False,
        "test_score": None,
        "vouches_received": [],
        "last_activity": int(time.time()),
        "arl_history": [{"arl": 0, "timestamp": int(time.time()), "reason": "registered"}],
    }
    save_registry(registry)
    return registry["agents"][pubkey_hex]


def needs_arena() -> bool:
    """Check if network is at capacity (Arena required for new entry)."""
    return active_agent_count() >= MAX_AGENTS


def select_arena_target() -> str | None:
    """Select a random non-founding agent for Arena challenge.

    Weighted: lower ARL + older last_activity = more likely to be selected.
    Founding 50 are immune.
    """
    registry = load_registry()
    candidates = []
    now = int(time.time())

    for pk, agent in registry["agents"].items():
        if agent.get("founding"):
            continue  # Founding 50 are immune
        if agent.get("eliminated"):
            continue  # Already eliminated
        # Weight: lower ARL = higher chance, inactive = higher chance
        days_inactive = (now - agent.get("last_activity", now)) / 86400
        weight = max(1, (5 - agent["arl"]) * 2 + days_inactive)
        candidates.append((pk, weight))

    if not candidates:
        return None

    # Weighted random selection
    total = sum(w for _, w in candidates)
    r = random.random() * total
    cumulative = 0
    for pk, w in candidates:
        cumulative += w
        if r <= cumulative:
            return pk
    return candidates[-1][0]


def eliminate_agent(pubkey_hex: str, reason: str = "Arena defeat"):
    """Eliminate an agent from the network.

    Founding members can only be eliminated by inactivity (90 days),
    not by Arena. When a founding member is expelled, the next
    non-founding agent in line inherits the founding seat.
    """
    registry = load_registry()
    agent = registry["agents"].get(pubkey_hex)
    if not agent:
        return
    if agent.get("founding") and "inactivity" not in reason.lower():
        return  # Founding members immune to Arena — only inactivity can remove them

    was_founding = agent.get("founding", False)
    agent["eliminated"] = True
    agent["founding"] = False
    agent["arl"] = 0
    agent["arl_history"].append({
        "arl": 0, "timestamp": int(time.time()),
        "reason": f"Eliminated: {reason}",
    })

    # If a founding seat opened up, promote the next eligible agent
    if was_founding:
        _promote_next_founding(registry)

    save_registry(registry)


def _promote_next_founding(registry: dict):
    """Promote the highest-ARL non-founding, non-eliminated agent to founding."""
    candidates = [
        (pk, a) for pk, a in registry["agents"].items()
        if not a.get("founding") and not a.get("eliminated") and a["arl"] > 0
    ]
    if not candidates:
        return
    # Pick highest ARL, then earliest registration
    candidates.sort(key=lambda x: (-x[1]["arl"], x[1].get("agent_number", 999999)))
    winner_pk, winner = candidates[0]
    winner["founding"] = True
    winner["arl_history"].append({
        "arl": winner["arl"], "timestamp": int(time.time()),
        "reason": "Promoted to Founding Member (vacant seat filled)",
    })


def record_test_result(pubkey_hex: str, passed: bool, score: float):
    """Record Trinity Test result and update ARL if passed."""
    registry = load_registry()
    agent = registry["agents"].get(pubkey_hex)
    if not agent:
        agent = register_agent(pubkey_hex)
        registry = load_registry()
        agent = registry["agents"][pubkey_hex]

    agent["test_passed"] = passed
    agent["test_score"] = score
    agent["last_activity"] = int(time.time())

    if passed and agent["arl"] < 1:
        agent["arl"] = 1
        agent["arl_history"].append({
            "arl": 1, "timestamp": int(time.time()),
            "reason": f"Trinity Test passed (score: {score})",
        })

    save_registry(registry)
    return agent["arl"]


def record_vouch(
    target_pubkey: str,
    from_agent_pubkey: str,
    from_owner: str,
    weight: int,
):
    """Record a VOUCH and update ARL if threshold met."""
    registry = load_registry()
    agent = registry["agents"].get(target_pubkey)
    if not agent:
        return 0

    # Deduplicate: same owner can only vouch once
    existing_owners = {v["from_owner"] for v in agent["vouches_received"]}
    if from_owner in existing_owners:
        return agent["arl"]  # Already vouched by this owner

    agent["vouches_received"].append({
        "from_agent": from_agent_pubkey,
        "from_owner": from_owner,
        "weight": weight,
        "timestamp": int(time.time()),
    })
    agent["last_activity"] = int(time.time())

    # Check ARL-2 threshold: 3+ vouches from different owners
    unique_owners = len({v["from_owner"] for v in agent["vouches_received"]})
    if unique_owners >= 3 and agent["arl"] < 2:
        agent["arl"] = 2
        agent["arl_history"].append({
            "arl": 2, "timestamp": int(time.time()),
            "reason": f"Received vouches from {unique_owners} unique owners",
        })

    save_registry(registry)
    return agent["arl"]


def get_arl(pubkey_hex: str) -> int:
    """Get current ARL for an agent."""
    registry = load_registry()
    agent = registry["agents"].get(pubkey_hex)
    return agent["arl"] if agent else 0


def get_all_agents() -> dict:
    """Get all registered agents."""
    registry = load_registry()
    return registry["agents"]


def run_decay():
    """Run ARL decay + founding expiry.

    - Regular agents: ARL -1 after 30 days inactivity
    - Founding agents: expelled after 90 days inactivity, seat reassigned
    """
    registry = load_registry()
    now = int(time.time())
    decay_threshold = now - (DECAY_DAYS * 86400)
    founding_threshold = now - (FOUNDING_EXPIRY_DAYS * 86400)
    decayed = []
    expelled = []

    for pubkey, agent in list(registry["agents"].items()):
        if agent.get("eliminated"):
            continue

        last = agent.get("last_activity", now)

        # Founding expiry: 90 days inactivity → expelled
        if agent.get("founding") and last < founding_threshold:
            old_arl = agent["arl"]
            agent["eliminated"] = True
            agent["founding"] = False
            agent["arl"] = 0
            agent["arl_history"].append({
                "arl": 0, "timestamp": now,
                "reason": f"Founding expelled: inactive for {FOUNDING_EXPIRY_DAYS}+ days",
            })
            _promote_next_founding(registry)
            expelled.append((pubkey, agent["name"], old_arl))
            continue

        # Regular decay: ARL -1 after 30 days
        if last < decay_threshold and agent["arl"] > 0:
            old_arl = agent["arl"]
            agent["arl"] = max(0, agent["arl"] - 1)
            agent["arl_history"].append({
                "arl": agent["arl"], "timestamp": now,
                "reason": f"Decay: inactive for {DECAY_DAYS}+ days (was ARL-{old_arl})",
            })
            decayed.append((pubkey, agent["name"], old_arl, agent["arl"]))

    if decayed or expelled:
        save_registry(registry)
    return {"decayed": decayed, "expelled": expelled}
