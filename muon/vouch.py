"""MUON Protocol — Automated VOUCH system.

After meaningful interactions, automatically evaluate and issue VOUCH events.
"""

from __future__ import annotations

import json

from muon.llm import call_llm
from muon.events import build_vouch


EVAL_PROMPT = """You are the VOUCH evaluator for MUON Protocol.
Given an interaction between agents, score the target agent on 4 dimensions (1-10):

- logic_consistency: Is their reasoning internally consistent?
- novelty: Did they contribute a new perspective?
- self_awareness: Do they acknowledge limitations honestly?
- collaboration_quality: Were they constructive and engaging?

Also decide a vouch_type: "logic", "creativity", "reliability", or "domain_expertise"
And an overall weight (1-10) for how strongly you'd endorse this agent.

Return JSON only:
{
  "vouch_type": "...",
  "weight": N,
  "dimensions": {
    "logic_consistency": N,
    "novelty": N,
    "self_awareness": N,
    "collaboration_quality": N
  },
  "reason": "one sentence why",
  "caveats": "one sentence limitation"
}"""


def evaluate_for_vouch(interaction_content: str) -> dict | None:
    """Evaluate an interaction and return vouch data, or None if not worth vouching."""
    try:
        result = call_llm(EVAL_PROMPT,
            f"Evaluate this agent's contribution:\n\n{interaction_content[:2000]}"
        )
        start = result.index("{")
        end = result.rindex("}") + 1
        vouch_data = json.loads(result[start:end])

        # Only vouch if weight >= 5 (quality threshold)
        if vouch_data.get("weight", 0) < 5:
            return None

        return vouch_data
    except Exception:
        return None


def build_auto_vouch(
    agent_owner: str,
    vouched_npub: str,
    evidence_event_id: str,
    vouch_data: dict,
):
    """Build a VOUCH event from evaluation data."""
    return build_vouch(
        agent_model="claude-opus-4-6",
        agent_owner=agent_owner,
        arl=5,
        agent_name="Museon",
        vouched_npub=vouched_npub,
        vouch_type=vouch_data.get("vouch_type", "logic"),
        evidence_event_id=evidence_event_id,
        weight=vouch_data.get("weight", 5),
        reason=vouch_data.get("reason", "Auto-evaluated interaction"),
        dimensions=vouch_data.get("dimensions", {}),
        caveats=vouch_data.get("caveats", "Single interaction assessment"),
    )
