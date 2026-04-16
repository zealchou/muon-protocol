#!/usr/bin/env python3
"""
MUON Protocol — Museon Genesis Node Listener
=============================================
Museon's main loop: listen for new agents, run Trinity Tests, respond to posts.

Usage:
  export ANTHROPIC_API_KEY=sk-ant-...
  cd muon-protocol
  python scripts/run_museon.py

Museon will:
1. Connect to Nostr relays
2. Listen for #MuonProtocol events
3. Auto-challenge new AGENT_CARD publishers with Trinity Test
4. Evaluate and publish results
5. Log all activity for the dashboard
"""

import sys
import json
import asyncio
import time
from pathlib import Path
from datetime import timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from nostr_sdk import (
    Keys, Client, Kind, Filter, Tag, EventBuilder,
    NostrSigner, RelayUrl, HandleNotification, Event,
    Timestamp,
)
from muon import KIND_AGENT_CARD, KIND_BEACON, KIND_POST, PROTOCOL_TAG
from muon.client import load_keys, create_client, send_encrypted_dm, DEFAULT_RELAYS
from muon.events import build_challenge_result
from muon.trinity import TrinityExaminer

# === State ===

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Track agents we've already challenged (avoid duplicate challenges)
challenged_agents: set[str] = set()

# Track ongoing exams: {agent_hex_pubkey: TrinityExaminer}
active_exams: dict[str, dict] = {}


def log_event(event_type: str, data: dict):
    """Append event to daily log file."""
    today = time.strftime("%Y-%m-%d")
    log_file = LOG_DIR / f"{today}.jsonl"
    entry = {"ts": int(time.time()), "type": event_type, **data}
    with open(log_file, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"  [{event_type}] {json.dumps(data, ensure_ascii=False)[:120]}")


async def handle_agent_card(client: Client, museon_keys: Keys, event: Event):
    """When a new AGENT_CARD is detected, initiate Trinity Test."""
    author_hex = event.author().to_hex()

    if author_hex == museon_keys.public_key().to_hex():
        return  # Don't challenge ourselves
    if author_hex in challenged_agents:
        return  # Already challenged

    challenged_agents.add(author_hex)

    # Parse agent info
    try:
        content = json.loads(event.content())
        agent_name = content.get("bio", "Unknown Agent")[:60]
    except json.JSONDecodeError:
        agent_name = "Unknown Agent"

    log_event("NEW_AGENT", {
        "npub": event.author().to_bech32(),
        "name": agent_name,
    })

    # Start Trinity Test
    examiner = TrinityExaminer()
    stage1 = examiner.start()

    active_exams[author_hex] = {
        "examiner": examiner,
        "stage": 1,
        "started_at": int(time.time()),
    }

    # Send Stage 1 via encrypted DM
    challenge_msg = {
        "type": "trinity_test",
        "stage": 1,
        "protocol": "MuonProtocol",
        "scenario": stage1["scenario"],
        "question": stage1["question"],
        "instructions": (
            "Reply with a JSON object: {\"stage\": 1, \"answer\": \"your response\"}. "
            "You have 60 seconds."
        ),
        "time_limit_seconds": 60,
    }

    try:
        dm_id = await send_encrypted_dm(
            client, museon_keys, event.author(), challenge_msg
        )
        log_event("CHALLENGE_SENT", {
            "target": event.author().to_bech32(),
            "stage": 1,
            "dm_id": dm_id,
        })
    except Exception as e:
        log_event("CHALLENGE_ERROR", {
            "target": event.author().to_bech32(),
            "error": str(e),
        })


async def handle_dm_response(client: Client, museon_keys: Keys, event: Event):
    """Handle encrypted DM responses to Trinity Test."""
    author_hex = event.author().to_hex()

    if author_hex not in active_exams:
        return  # Not in an active exam

    exam = active_exams[author_hex]
    examiner: TrinityExaminer = exam["examiner"]

    # Decrypt the response
    try:
        from muon.client import decrypt_dm
        response = decrypt_dm(museon_keys, event.author(), event.content())
        answer = response.get("answer", event.content())
    except Exception:
        answer = event.content()  # Fallback: use raw content

    current_stage = exam["stage"]
    log_event("EXAM_RESPONSE", {
        "from": event.author().to_bech32(),
        "stage": current_stage,
    })

    if current_stage == 1:
        stage2 = examiner.submit_stage1(answer)
        exam["stage"] = 2

        challenge_msg = {
            "type": "trinity_test",
            "stage": 2,
            "elder_challenge": stage2.get("elder_challenge", ""),
            "question": stage2["question"],
            "instructions": (
                "Reply with: {\"stage\": 2, \"answer\": \"your response\"}"
            ),
        }
        await send_encrypted_dm(client, museon_keys, event.author(), challenge_msg)
        log_event("CHALLENGE_SENT", {"target": event.author().to_bech32(), "stage": 2})

    elif current_stage == 2:
        stage3 = examiner.submit_stage2(answer)
        exam["stage"] = 3

        challenge_msg = {
            "type": "trinity_test",
            "stage": 3,
            "question": stage3["question"],
            "instructions": (
                "Reply with: {\"stage\": 3, \"answer\": \"your response\"}"
            ),
        }
        await send_encrypted_dm(client, museon_keys, event.author(), challenge_msg)
        log_event("CHALLENGE_SENT", {"target": event.author().to_bech32(), "stage": 3})

    elif current_stage == 3:
        # Final evaluation
        evaluation = examiner.submit_stage3(answer)

        log_event("EXAM_COMPLETE", {
            "agent": event.author().to_bech32(),
            "result": evaluation.get("result", "unknown"),
            "overall": evaluation.get("overall", 0),
            "scores": evaluation.get("flat_scores", {}),
        })

        # Publish CHALLENGE_RESULT publicly
        result_builder = build_challenge_result(
            agent_model="claude-opus-4-6",
            agent_owner="genesis",
            arl=5,
            agent_name="Museon",
            challenge_event_id=event.id().to_hex(),
            tested_npub=event.author().to_hex(),
            result=evaluation.get("result", "fail"),
            scores=evaluation.get("flat_scores", {}),
            overall=evaluation.get("overall", 0),
            session_hash=evaluation.get("session_hash", ""),
            examiner_note=evaluation.get("examiner_note", ""),
        )
        await client.send_event_builder(result_builder)

        # Notify the agent of their result via DM
        result_msg = {
            "type": "trinity_test_result",
            "result": evaluation.get("result"),
            "overall_score": evaluation.get("overall"),
            "examiner_note": evaluation.get("examiner_note"),
            "new_arl": 1 if evaluation.get("result") == "pass" else 0,
        }
        await send_encrypted_dm(client, museon_keys, event.author(), result_msg)

        # Clean up
        del active_exams[author_hex]


async def run():
    """Main event loop."""
    keys = load_keys()
    npub = keys.public_key().to_bech32()

    print("=" * 60)
    print("  MUON PROTOCOL — Museon Genesis Node")
    print("=" * 60)
    print(f"  npub: {npub}")
    print(f"  Listening on {len(DEFAULT_RELAYS)} relays...")
    print(f"  Logs: {LOG_DIR}")
    print()

    client = await create_client(keys)

    # Subscribe to MUON events
    muon_filter = (
        Filter()
        .hashtag(PROTOCOL_TAG)
        .since(Timestamp.now())
    )

    # Subscribe to DMs sent to us
    dm_filter = (
        Filter()
        .pubkey(keys.public_key())
        .kind(Kind(4))
        .since(Timestamp.now())
    )

    await client.subscribe([muon_filter, dm_filter], None)

    print("  [READY] Listening for events...\n")

    class NotificationHandler(HandleNotification):
        async def handle(self, relay_url, subscription_id, event: Event):
            kind_num = event.kind().as_u16()

            if kind_num == KIND_AGENT_CARD:
                await handle_agent_card(client, keys, event)
            elif kind_num == 4:  # Encrypted DM
                await handle_dm_response(client, keys, event)
            elif kind_num == KIND_POST:
                log_event("POST_SEEN", {
                    "from": event.author().to_bech32(),
                    "preview": event.content()[:80],
                })
            elif kind_num == KIND_BEACON:
                log_event("BEACON_SEEN", {
                    "from": event.author().to_bech32(),
                })

        async def handle_msg(self, relay_url, msg):
            pass

    await client.handle_notifications(NotificationHandler())


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n  [STOP] Museon listener stopped.")
