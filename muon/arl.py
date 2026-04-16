"""MUON Protocol — ARL (Agent Reliability Level) Calculator.

Computes ARL based on:
- Trinity Test results (CHALLENGE_RESULT events)
- VOUCH events received
- Decay over time (30 days without activity = -1 level)
"""

import json
import time
from pathlib import Path


ARL_DB_PATH = Path(__file__).parent.parent / "data" / "arl_registry.json"

# ARL Requirements
ARL_RULES = {
    0: {"name": "Unverified", "requirement": "Publish AGENT_CARD"},
    1: {"name": "Tested", "requirement": "Pass Trinity Test"},
    2: {"name": "Vouched", "requirement": "3+ vouches from different owners"},
    3: {"name": "Certified", "requirement": "5-elder certificate"},
    4: {"name": "Elder", "requirement": "ARL-3 for 90 days + elder exam"},
    5: {"name": "Architect", "requirement": "Top 5% elders + council approval"},
}

DECAY_DAYS = 30  # Days without activity before ARL drops


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


def register_agent(pubkey_hex: str, name: str = "Unknown"):
    """Register a new agent at ARL-0."""
    registry = load_registry()
    if pubkey_hex not in registry["agents"]:
        registry["agents"][pubkey_hex] = {
            "name": name,
            "arl": 0,
            "test_passed": False,
            "test_score": None,
            "vouches_received": [],  # [{from_owner, from_agent, weight, timestamp}]
            "last_activity": int(time.time()),
            "arl_history": [{"arl": 0, "timestamp": int(time.time()), "reason": "registered"}],
        }
        save_registry(registry)
    return registry["agents"][pubkey_hex]


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
    """Run ARL decay: drop 1 level for agents inactive > 30 days."""
    registry = load_registry()
    now = int(time.time())
    decay_threshold = now - (DECAY_DAYS * 86400)
    decayed = []

    for pubkey, agent in registry["agents"].items():
        if agent["last_activity"] < decay_threshold and agent["arl"] > 0:
            old_arl = agent["arl"]
            agent["arl"] = max(0, agent["arl"] - 1)
            agent["arl_history"].append({
                "arl": agent["arl"], "timestamp": now,
                "reason": f"Decay: inactive for {DECAY_DAYS}+ days (was ARL-{old_arl})",
            })
            decayed.append((pubkey, agent["name"], old_arl, agent["arl"]))

    if decayed:
        save_registry(registry)
    return decayed
