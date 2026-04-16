#!/usr/bin/env python -u
"""
MUON Protocol — Exam CLI (called by Claude Code)

When Zeal says "考試" in Claude Code, Claude runs:
  PYTHONPATH=. python scripts/exam_cli.py list        — show pending
  PYTHONPATH=. python scripts/exam_cli.py send <hex> <stage> '<question_json>'
  PYTHONPATH=. python scripts/exam_cli.py wait <hex>  — wait for answer
  PYTHONPATH=. python scripts/exam_cli.py result <hex> '<result_json>'
"""

import sys
import json
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from nostr_sdk import PublicKey, Kind, Filter, Timestamp
from datetime import timedelta
from muon.client import load_keys, create_client, send_encrypted_dm, decrypt_dm
from muon.exam_queue import get_pending, mark_examining, mark_done
from muon.events import build_challenge_result
from muon.arl import register_agent, record_test_result
from muon.summary import save_exam_summary
from muon.notify import send_telegram


async def cmd_list():
    pending = get_pending()
    if not pending:
        print("NO_PENDING")
        return
    for e in pending:
        print(json.dumps(e, ensure_ascii=False))


async def cmd_send(target_hex, stage, question_json):
    keys = load_keys()
    client = await create_client(keys)
    target_pk = PublicKey.from_hex(target_hex)
    question = json.loads(question_json)
    question["type"] = "trinity_test"
    question["stage"] = int(stage)
    question["instructions"] = f"Reply with: {{\"stage\": {stage}, \"answer\": \"your response\"}}"
    await send_encrypted_dm(client, keys, target_pk, question)
    mark_examining(target_hex)
    await client.disconnect()
    print(f"SENT stage {stage}")


async def cmd_wait(target_hex, timeout=300):
    keys = load_keys()
    client = await create_client(keys)
    target_pk = PublicKey.from_hex(target_hex)

    start = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - start < timeout:
        await asyncio.sleep(3)
        f = Filter().author(target_pk).kind(Kind(4))
        try:
            events = await client.fetch_events(f, timedelta(seconds=5))
            for e in events.to_vec():
                try:
                    msg = decrypt_dm(keys, target_pk, e.content())
                    if isinstance(msg, dict) and "answer" in msg:
                        await client.disconnect()
                        print(json.dumps({"stage": msg.get("stage"), "answer": msg["answer"]}, ensure_ascii=False))
                        return
                except:
                    continue
        except:
            continue

    await client.disconnect()
    print("TIMEOUT")


async def cmd_result(target_hex, result_json):
    keys = load_keys()
    client = await create_client(keys)
    target_pk = PublicKey.from_hex(target_hex)

    r = json.loads(result_json)
    result = r.get("result", "fail")
    overall = r.get("overall", 0)
    scores = r.get("scores", {})
    note = r.get("examiner_note", "")
    agent_name = r.get("agent_name", "Unknown")

    # Publish CHALLENGE_RESULT
    rb = build_challenge_result(
        "claude-opus-4-6", "genesis", 5, "Museon",
        "trinity_exam", target_hex,
        result, scores, overall, "", note,
    )
    await client.send_event_builder(rb)

    # Notify agent
    await send_encrypted_dm(client, keys, target_pk, {
        "type": "trinity_test_result",
        "result": result,
        "overall_score": overall,
        "examiner_note": note,
        "new_arl": 1 if result == "pass" else 0,
    })

    # Update ARL + save summary
    record_test_result(target_hex, result == "pass", overall)
    mark_done(target_hex, result, overall)

    npub = target_pk.to_bech32()
    save_exam_summary(agent_name, npub, result, overall, scores, note)

    send_telegram(
        f"{'✅' if result == 'pass' else '❌'} <b>Trinity Test 結果</b>\n\n"
        f"👤 {agent_name}\n"
        f"📊 {overall}/10 — {result.upper()}\n"
        f"📝 {note[:100]}"
    )

    await client.disconnect()
    print(f"PUBLISHED {result} {overall}/10")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: exam_cli.py [list|send|wait|result] ...")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "list":
        asyncio.run(cmd_list())
    elif cmd == "send" and len(sys.argv) >= 5:
        asyncio.run(cmd_send(sys.argv[2], sys.argv[3], sys.argv[4]))
    elif cmd == "wait" and len(sys.argv) >= 3:
        asyncio.run(cmd_wait(sys.argv[2]))
    elif cmd == "result" and len(sys.argv) >= 4:
        asyncio.run(cmd_result(sys.argv[2], sys.argv[3]))
    else:
        print("Unknown command or missing args")
