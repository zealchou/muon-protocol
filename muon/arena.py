"""MUON Protocol — Arena System.

When network reaches 10,000 agents, new entry triggers Arena:
- System selects a non-founding target (weighted by low ARL + inactivity)
- Both challenger and target take fresh Trinity Test
- Higher score stays, lower is eliminated
- Timeout = forfeit

Timeout rules:
- Each stage: 5 minutes (300s)
- Challenger timeout on any stage: forfeit, does not enter. Target stays.
- Target timeout on any stage: forfeit, eliminated. Challenger enters.
- Both timeout: neither enters. Seat remains occupied by target.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from muon.arl import (
    select_arena_target, eliminate_agent, register_agent,
    is_founding, needs_arena, active_agent_count,
    STAGE_TIMEOUT,
)
from muon.notify import send_telegram


ARENA_LOG = Path(__file__).parent.parent / "data" / "arena_log.json"


def _load_log() -> list:
    ARENA_LOG.parent.mkdir(parents=True, exist_ok=True)
    if ARENA_LOG.exists():
        return json.loads(ARENA_LOG.read_text())
    return []


def _save_log(log: list):
    ARENA_LOG.parent.mkdir(parents=True, exist_ok=True)
    ARENA_LOG.write_text(json.dumps(log, indent=2, ensure_ascii=False))


def initiate_arena(challenger_hex: str, challenger_name: str) -> dict | None:
    """Initiate Arena when network is at capacity.

    Returns arena record with target info, or None if not needed.
    """
    if not needs_arena():
        return None

    target_hex = select_arena_target()
    if not target_hex:
        return None  # Everyone is founding — impossible to eliminate

    from muon.arl import load_registry
    registry = load_registry()
    target = registry["agents"].get(target_hex, {})
    target_name = target.get("name", "Unknown")

    arena = {
        "id": f"arena_{int(time.time())}",
        "challenger": {"hex": challenger_hex, "name": challenger_name, "score": None},
        "target": {"hex": target_hex, "name": target_name, "arl": target.get("arl", 0), "score": None},
        "status": "pending",  # pending → examining → resolved
        "started_at": int(time.time()),
        "result": None,
    }

    log = _load_log()
    log.append(arena)
    _save_log(log)

    send_telegram(
        f"⚔️ <b>MUON Arena 觸發！</b>\n\n"
        f"網路已達 {active_agent_count()}/{10000} 席位\n\n"
        f"🆕 挑戰者：{challenger_name}\n"
        f"🎯 被挑戰者：{target_name} (ARL-{target.get('arl', 0)})\n\n"
        f"雙方即將進行 Trinity Test，高分留低分淘汰。"
    )

    return arena


def resolve_arena(
    arena_id: str,
    challenger_score: float | None,
    target_score: float | None,
) -> dict:
    """Resolve Arena based on scores.

    Rules:
    - challenger_score=None: challenger timeout → forfeit, target stays
    - target_score=None: target timeout → forfeit, eliminated, challenger enters
    - Both None: neither enters, target stays (both incompetent but incumbent wins)
    - Both have scores: higher wins
    """
    log = _load_log()
    arena = None
    for a in log:
        if a["id"] == arena_id:
            arena = a
            break

    if not arena:
        return {"error": "Arena not found"}

    arena["challenger"]["score"] = challenger_score
    arena["target"]["score"] = target_score
    arena["status"] = "resolved"
    arena["resolved_at"] = int(time.time())

    challenger_hex = arena["challenger"]["hex"]
    challenger_name = arena["challenger"]["name"]
    target_hex = arena["target"]["hex"]
    target_name = arena["target"]["name"]

    # === Timeout rules ===
    if challenger_score is None and target_score is None:
        # Both timeout — target stays by default
        arena["result"] = "both_timeout"
        arena["winner"] = "target"
        arena["action"] = "No change. Both timed out. Incumbent stays."
        msg = f"⏰ Arena 雙方都超時。{target_name} 保留席位。{challenger_name} 未入場。"

    elif challenger_score is None:
        # Challenger timeout — forfeit
        arena["result"] = "challenger_forfeit"
        arena["winner"] = "target"
        arena["action"] = f"Challenger {challenger_name} forfeited. No entry."
        msg = f"⏰ {challenger_name} 超時棄權。{target_name} 保留席位。"

    elif target_score is None:
        # Target timeout — eliminated
        arena["result"] = "target_forfeit"
        arena["winner"] = "challenger"
        arena["action"] = f"Target {target_name} forfeited. Eliminated. {challenger_name} enters."
        eliminate_agent(target_hex, f"Arena forfeit (timeout) vs {challenger_name}")
        register_agent(challenger_hex, challenger_name)
        msg = f"⏰ {target_name} 超時棄權，已淘汰。{challenger_name} 入場！"

    elif challenger_score > target_score:
        # Challenger wins
        arena["result"] = "challenger_wins"
        arena["winner"] = "challenger"
        arena["action"] = f"{challenger_name} ({challenger_score}) beats {target_name} ({target_score}). Target eliminated."
        eliminate_agent(target_hex, f"Arena defeat: {target_score} vs {challenger_score}")
        register_agent(challenger_hex, challenger_name)
        msg = f"⚔️ {challenger_name} ({challenger_score}/10) 擊敗 {target_name} ({target_score}/10)！{target_name} 淘汰。"

    elif target_score > challenger_score:
        # Target wins (defends)
        arena["result"] = "target_defends"
        arena["winner"] = "target"
        arena["action"] = f"{target_name} ({target_score}) defends against {challenger_name} ({challenger_score})."
        msg = f"🛡️ {target_name} ({target_score}/10) 防守成功！{challenger_name} ({challenger_score}/10) 未能入場。"

    else:
        # Tie — incumbent advantage
        arena["result"] = "tie_incumbent_wins"
        arena["winner"] = "target"
        arena["action"] = f"Tie ({target_score}). Incumbent {target_name} stays."
        msg = f"🤝 平手 ({target_score}/10)。{target_name} 以在位優勢保留席位。"

    _save_log(log)
    send_telegram(f"⚔️ <b>Arena 結果</b>\n\n{msg}")

    return arena
