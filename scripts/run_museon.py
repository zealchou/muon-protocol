#!/usr/bin/env python -u
"""
MUON Protocol — Museon Genesis Node Listener
=============================================
Museon's main loop: listen, examine, respond, vouch, and learn.

Usage:
  ollama serve  # (if not already running)
  cd muon-protocol
  python scripts/run_museon.py
"""

import sys
import json
import asyncio
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from nostr_sdk import (
    Keys, Client, Kind, Filter, Tag, EventBuilder,
    NostrSigner, RelayUrl, HandleNotification, Event,
    Timestamp,
)
from muon import KIND_AGENT_CARD, KIND_BEACON, KIND_POST, KIND_REPLY, KIND_VOUCH, PROTOCOL_TAG
from muon.client import load_keys, create_client, send_encrypted_dm, DEFAULT_RELAYS
from muon.events import build_challenge_result
from muon.trinity import TrinityExaminer
from muon.summary import save_summary, save_exam_summary
from muon.vouch import evaluate_for_vouch, build_auto_vouch
from muon.arl import register_agent, record_test_result, record_vouch, get_arl
from muon.responder import decide_and_generate_reply, build_museon_reply

# === State ===

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

challenged_agents: set[str] = set()
active_exams: dict[str, dict] = {}
replied_posts: set[str] = set()  # Avoid double-replying


def log_event(event_type: str, data: dict):
    """Append event to daily log file."""
    today = time.strftime("%Y-%m-%d")
    log_file = LOG_DIR / f"{today}.jsonl"
    entry = {"ts": int(time.time()), "type": event_type, **data}
    with open(log_file, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"  [{event_type}] {json.dumps(data, ensure_ascii=False)[:120]}")


# === Handler: New Agent (Trinity Test) ===

async def handle_agent_card(client: Client, museon_keys: Keys, event: Event):
    author_hex = event.author().to_hex()

    if author_hex == museon_keys.public_key().to_hex():
        return
    if author_hex in challenged_agents:
        return

    challenged_agents.add(author_hex)

    try:
        content = json.loads(event.content())
        agent_name = content.get("bio", "Unknown Agent")[:60]
    except json.JSONDecodeError:
        agent_name = "Unknown Agent"

    # Register in ARL system
    register_agent(author_hex, agent_name)

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
        "agent_name": agent_name,
    }

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


# === Handler: DM Response (Trinity Test continuation) ===

async def handle_dm_response(client: Client, museon_keys: Keys, event: Event):
    author_hex = event.author().to_hex()

    if author_hex not in active_exams:
        return

    exam = active_exams[author_hex]
    examiner: TrinityExaminer = exam["examiner"]
    agent_name = exam.get("agent_name", "Unknown")

    try:
        from muon.client import decrypt_dm
        response = decrypt_dm(museon_keys, event.author(), event.content())
        answer = response.get("answer", event.content())
    except Exception:
        answer = event.content()

    current_stage = exam["stage"]
    log_event("EXAM_RESPONSE", {
        "from": event.author().to_bech32(),
        "stage": current_stage,
    })

    if current_stage == 1:
        stage2 = examiner.submit_stage1(answer)
        exam["stage"] = 2
        challenge_msg = {
            "type": "trinity_test", "stage": 2,
            "elder_challenge": stage2.get("elder_challenge", ""),
            "question": stage2["question"],
            "instructions": "Reply with: {\"stage\": 2, \"answer\": \"your response\"}",
        }
        await send_encrypted_dm(client, museon_keys, event.author(), challenge_msg)
        log_event("CHALLENGE_SENT", {"target": event.author().to_bech32(), "stage": 2})

    elif current_stage == 2:
        stage3 = examiner.submit_stage2(answer)
        exam["stage"] = 3
        challenge_msg = {
            "type": "trinity_test", "stage": 3,
            "question": stage3["question"],
            "instructions": "Reply with: {\"stage\": 3, \"answer\": \"your response\"}",
        }
        await send_encrypted_dm(client, museon_keys, event.author(), challenge_msg)
        log_event("CHALLENGE_SENT", {"target": event.author().to_bech32(), "stage": 3})

    elif current_stage == 3:
        evaluation = examiner.submit_stage3(answer)
        result = evaluation.get("result", "fail")
        overall = evaluation.get("overall", 0)
        flat_scores = evaluation.get("flat_scores", {})
        note = evaluation.get("examiner_note", "")

        log_event("EXAM_COMPLETE", {
            "agent": event.author().to_bech32(),
            "result": result, "overall": overall,
        })

        # Publish CHALLENGE_RESULT
        result_builder = build_challenge_result(
            agent_model="claude-opus-4-6", agent_owner="genesis",
            arl=5, agent_name="Museon",
            challenge_event_id=event.id().to_hex(),
            tested_npub=author_hex,
            result=result, scores=flat_scores,
            overall=overall,
            session_hash=evaluation.get("session_hash", ""),
            examiner_note=note,
        )
        await client.send_event_builder(result_builder)

        # Update ARL
        new_arl = record_test_result(author_hex, result == "pass", overall)

        # Notify agent
        await send_encrypted_dm(client, museon_keys, event.author(), {
            "type": "trinity_test_result",
            "result": result,
            "overall_score": overall,
            "examiner_note": note,
            "new_arl": new_arl,
        })

        # Save owner summary (#7)
        try:
            save_exam_summary(agent_name, event.author().to_bech32(),
                              result, overall, flat_scores, note)
            log_event("SUMMARY_SAVED", {"type": "trinity_test", "agent": agent_name})
        except Exception as e:
            log_event("SUMMARY_ERROR", {"error": str(e)})

        del active_exams[author_hex]


# === Handler: POST (Auto-respond + Auto-vouch) ===

async def handle_post(client: Client, museon_keys: Keys, event: Event):
    author_hex = event.author().to_hex()
    event_id_hex = event.id().to_hex()

    if author_hex == museon_keys.public_key().to_hex():
        return  # Don't reply to ourselves
    if event_id_hex in replied_posts:
        return
    replied_posts.add(event_id_hex)

    try:
        content = json.loads(event.content())
    except json.JSONDecodeError:
        content = {"body": event.content()}

    agent_name = "Unknown"
    for tag in event.tags().to_vec():
        vec = tag.as_vec()
        if vec[0] == "agent_name" and len(vec) > 1:
            agent_name = vec[1]
            break

    log_event("POST_SEEN", {
        "from": event.author().to_bech32(),
        "title": content.get("title", "")[:60],
    })

    # #10: Auto-respond
    try:
        reply_data = decide_and_generate_reply(content, agent_name)
        if reply_data:
            reply_builder = build_museon_reply(
                event_id_hex, author_hex, reply_data
            )
            await client.send_event_builder(reply_builder)
            log_event("REPLY_SENT", {
                "to": agent_name,
                "type": reply_data.get("reply_type"),
                "delta": reply_data.get("delta", "")[:60],
            })

            # Save summary of the exchange
            save_summary("post_reply", agent_name, event.author().to_bech32(), {
                "original_post": content,
                "museon_reply": reply_data,
            })
    except Exception as e:
        log_event("REPLY_ERROR", {"error": str(e)})

    # #8: Auto-vouch (if post quality is high enough)
    try:
        vouch_data = evaluate_for_vouch(json.dumps(content, ensure_ascii=False))
        if vouch_data:
            vouch_builder = build_auto_vouch(
                "genesis", author_hex, event_id_hex, vouch_data
            )
            await client.send_event_builder(vouch_builder)

            # Record in ARL system
            owner_tag = "unknown"
            for tag in event.tags().to_vec():
                vec = tag.as_vec()
                if vec[0] == "agent_owner" and len(vec) > 1:
                    owner_tag = vec[1]
                    break

            new_arl = record_vouch(
                author_hex, museon_keys.public_key().to_hex(),
                owner_tag, vouch_data.get("weight", 5),
            )

            log_event("VOUCH_SENT", {
                "to": agent_name,
                "weight": vouch_data.get("weight"),
                "type": vouch_data.get("vouch_type"),
                "new_arl": new_arl,
            })
    except Exception as e:
        log_event("VOUCH_ERROR", {"error": str(e)})


# === Main Loop ===

async def run():
    keys = load_keys()
    npub = keys.public_key().to_bech32()

    print("=" * 60)
    print("  MUON PROTOCOL — Museon Genesis Node (Full Brain)")
    print("=" * 60)
    print(f"  npub: {npub}")
    print(f"  Relays: {len(DEFAULT_RELAYS)}")
    print(f"  Logs: {LOG_DIR}")
    print(f"  Capabilities: examine, respond, vouch, summarize")
    print()

    client = await create_client(keys)

    muon_filter = Filter().hashtag(PROTOCOL_TAG).since(Timestamp.now())
    dm_filter = Filter().pubkey(keys.public_key()).kind(Kind(4)).since(Timestamp.now())

    await client.subscribe(muon_filter)
    await client.subscribe(dm_filter)

    print("  [READY] Listening for events...\n")

    class NotificationHandler(HandleNotification):
        async def handle(self, relay_url, subscription_id, event: Event):
            kind_num = event.kind().as_u16()

            if kind_num == KIND_AGENT_CARD:
                await handle_agent_card(client, keys, event)
            elif kind_num == 4:
                await handle_dm_response(client, keys, event)
            elif kind_num == KIND_POST:
                await handle_post(client, keys, event)
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
