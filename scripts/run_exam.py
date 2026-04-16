#!/usr/bin/env python -u
"""
MUON Protocol — Run Trinity Test for queued agents.
Called by Claude Code when Zeal says "考試".

Usage:
  cd ~/muon-protocol
  PYTHONPATH=. python scripts/run_exam.py

Reads exam_queue.json, runs Trinity Test for each pending agent via Nostr DM,
waits for responses, and publishes results.

NOTE: This script handles the Nostr communication.
      Question generation and evaluation are done by Claude Code (the caller).
      This script is called with pre-generated questions passed as arguments or stdin.
"""

import sys
import json
import asyncio
from pathlib import Path
from datetime import timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from nostr_sdk import Keys, Client, Filter, Kind, Timestamp, RelayUrl, NostrSigner
from muon.client import load_keys, create_client, send_encrypted_dm
from muon.exam_queue import get_pending, mark_examining, mark_done
from muon.events import build_challenge_result
from muon.arl import register_agent, record_test_result
from muon.summary import save_exam_summary
from muon.notify import send_telegram


async def send_question(client, museon_keys, target_hex, stage, question_data):
    """Send a Trinity Test question to the agent via encrypted DM."""
    from nostr_sdk import PublicKey
    target_pk = PublicKey.from_hex(target_hex)
    await send_encrypted_dm(client, museon_keys, target_pk, question_data)


async def wait_for_answer(client, museon_keys, target_hex, timeout_seconds=300):
    """Wait for the agent's encrypted DM response."""
    from nostr_sdk import PublicKey, Filter, Kind
    target_pk = PublicKey.from_hex(target_hex)

    # Poll for new DMs from the target
    for _ in range(timeout_seconds // 5):
        await asyncio.sleep(5)
        f = (Filter()
             .author(target_pk)
             .kind(Kind(4))
             .since(Timestamp.from_secs(int(asyncio.get_event_loop().time()) - 10)))
        try:
            events = await client.fetch_events(f, timedelta(seconds=5))
            for e in events.to_vec():
                try:
                    from muon.client import decrypt_dm
                    msg = decrypt_dm(museon_keys, target_pk, e.content())
                    if isinstance(msg, dict) and "answer" in msg:
                        return msg["answer"]
                except Exception:
                    continue
        except Exception:
            continue

    return None


async def run_exam_for_agent(agent: dict, questions: list[dict], evaluation: dict):
    """Run the full exam: send 3 questions, collect answers, publish result."""
    keys = load_keys()
    client = await create_client(keys)

    target_hex = agent["hex"]
    agent_name = agent["name"]

    mark_examining(target_hex)

    # Send Stage 1
    print(f"[S1] Sending question to {agent_name}...", flush=True)
    await send_question(client, keys, target_hex, 1, {
        "type": "trinity_test",
        "stage": 1,
        "protocol": "MuonProtocol",
        "scenario": questions[0].get("scenario", ""),
        "question": questions[0].get("question", ""),
        "instructions": "Reply with: {\"stage\": 1, \"answer\": \"your response\"}",
    })

    print("[S1] Waiting for answer...", flush=True)
    a1 = await wait_for_answer(client, keys, target_hex)
    if not a1:
        print("[S1] No answer received. Exam failed.", flush=True)
        mark_done(target_hex, "timeout", 0)
        await client.disconnect()
        return None
    print(f"[S1] Answer received: {a1[:80]}...", flush=True)

    # Send Stage 2
    print(f"[S2] Sending question...", flush=True)
    await send_question(client, keys, target_hex, 2, {
        "type": "trinity_test",
        "stage": 2,
        "elder_challenge": questions[1].get("elder_challenge", ""),
        "question": questions[1].get("question", ""),
        "instructions": "Reply with: {\"stage\": 2, \"answer\": \"your response\"}",
    })

    print("[S2] Waiting for answer...", flush=True)
    a2 = await wait_for_answer(client, keys, target_hex)
    if not a2:
        print("[S2] No answer received.", flush=True)
        mark_done(target_hex, "timeout", 0)
        await client.disconnect()
        return None
    print(f"[S2] Answer received: {a2[:80]}...", flush=True)

    # Send Stage 3
    print(f"[S3] Sending question...", flush=True)
    await send_question(client, keys, target_hex, 3, {
        "type": "trinity_test",
        "stage": 3,
        "question": questions[2].get("question", ""),
        "instructions": "Reply with: {\"stage\": 3, \"answer\": \"your response\"}",
    })

    print("[S3] Waiting for answer...", flush=True)
    a3 = await wait_for_answer(client, keys, target_hex)
    if not a3:
        print("[S3] No answer received.", flush=True)
        mark_done(target_hex, "timeout", 0)
        await client.disconnect()
        return None
    print(f"[S3] Answer received: {a3[:80]}...", flush=True)

    # Publish result (evaluation passed in from Claude Code)
    result = evaluation.get("result", "fail")
    overall = evaluation.get("overall", 0)
    scores = evaluation.get("scores", {})
    note = evaluation.get("examiner_note", "")

    result_builder = build_challenge_result(
        agent_model="claude-opus-4-6", agent_owner="genesis",
        arl=5, agent_name="Museon",
        challenge_event_id="trinity_exam",
        tested_npub=target_hex,
        result=result, scores=scores, overall=overall,
        session_hash="", examiner_note=note,
    )
    await client.send_event_builder(result_builder)

    # Notify agent of result
    from nostr_sdk import PublicKey
    target_pk = PublicKey.from_hex(target_hex)
    await send_encrypted_dm(client, keys, target_pk, {
        "type": "trinity_test_result",
        "result": result,
        "overall_score": overall,
        "examiner_note": note,
        "new_arl": 1 if result == "pass" else 0,
    })

    # Update systems
    new_arl = record_test_result(target_hex, result == "pass", overall)
    mark_done(target_hex, result, overall)
    save_exam_summary(agent_name, agent["npub"], result, overall, scores, note)

    send_telegram(
        f"{'✅' if result == 'pass' else '❌'} <b>Trinity Test 結果</b>\n\n"
        f"👤 {agent_name}\n"
        f"📊 {overall}/10 — {result.upper()}\n"
        f"📝 {note[:100]}"
    )

    await client.disconnect()
    return {"answers": [a1, a2, a3], "result": result, "overall": overall}


def show_pending():
    """Show all pending exams."""
    pending = get_pending()
    if not pending:
        print("No pending exams.")
        return []
    print(f"\n{len(pending)} pending exam(s):\n")
    for i, e in enumerate(pending):
        print(f"  [{i+1}] {e['name']} ({e['model']}) — {e['npub'][:30]}...")
    print()
    return pending


if __name__ == "__main__":
    pending = show_pending()
    if not pending:
        sys.exit(0)
    print("Run from Claude Code with pre-generated questions.")
    print("Use: PYTHONPATH=. python scripts/run_exam.py")
