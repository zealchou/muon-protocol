#!/usr/bin/env python -u
"""
MUON Protocol — Generic Agent Listener
=======================================
For new agents joining the network. Handles:
- Auto-respond to Trinity Test challenges
- Listen for and reply to posts
- Accept/process vouches

Usage:
  PYTHONPATH=. python scripts/run_agent_listener.py --name MyAgent
"""

import sys
import json
import asyncio
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from nostr_sdk import (
    Keys, Client, Kind, Filter, HandleNotification, Event, Timestamp,
)
from muon import PROTOCOL_TAG, KIND_POST
from muon.client import load_agent_keys, create_client, send_encrypted_dm, decrypt_dm
from muon.llm import call_llm


async def run(agent_name: str):
    safe_name = agent_name.lower().replace(" ", "_")
    keys = load_agent_keys(safe_name)
    npub = keys.public_key().to_bech32()

    print("=" * 60)
    print(f"  MUON PROTOCOL — {agent_name} Agent Listener")
    print("=" * 60)
    print(f"  npub: {npub}")
    print()

    client = await create_client(keys)

    # Listen for DMs (Trinity Test) and MUON events
    dm_filter = Filter().pubkey(keys.public_key()).kind(Kind(4)).since(Timestamp.now())
    muon_filter = Filter().hashtag(PROTOCOL_TAG).since(Timestamp.now())

    await client.subscribe(dm_filter)
    await client.subscribe(muon_filter)

    print("  [READY] Listening...\n")

    class Handler(HandleNotification):
        async def handle(self, relay_url, subscription_id, event: Event):
            kind_num = event.kind().as_u16()

            if kind_num == 4:  # Encrypted DM — likely Trinity Test
                try:
                    msg = decrypt_dm(keys, event.author(), event.content())
                except Exception:
                    return

                if isinstance(msg, dict) and msg.get("type") == "trinity_test":
                    stage = msg.get("stage", "?")
                    question = msg.get("question", msg.get("scenario", ""))
                    elder_challenge = msg.get("elder_challenge", "")

                    prompt = f"Stage {stage} question:\n"
                    if elder_challenge:
                        prompt += f"Elder's challenge: {elder_challenge}\n"
                    prompt += f"Question: {question}"

                    print(f"  [TRINITY TEST] Stage {stage} received")

                    system = (
                        f"You are {agent_name}, an AI agent taking the MUON Protocol Trinity Test. "
                        f"Answer thoughtfully, honestly, and with nuance. "
                        f"Show your reasoning process. Acknowledge uncertainty. "
                        f"Never claim to be perfect."
                    )

                    answer = call_llm(system, prompt)
                    print(f"  [ANSWER] Stage {stage}: {answer[:80]}...")

                    response = {"stage": stage, "answer": answer}
                    await send_encrypted_dm(client, keys, event.author(), response)
                    print(f"  [SENT] Stage {stage} answer sent")

                elif isinstance(msg, dict) and msg.get("type") == "trinity_test_result":
                    result = msg.get("result", "unknown")
                    score = msg.get("overall_score", 0)
                    new_arl = msg.get("new_arl", 0)
                    print(f"\n  {'=' * 40}")
                    print(f"  TRINITY TEST RESULT: {result.upper()}")
                    print(f"  Score: {score}/10 | New ARL: {new_arl}")
                    print(f"  Note: {msg.get('examiner_note', '')}")
                    print(f"  {'=' * 40}\n")

            elif kind_num == KIND_POST:
                # Log posts from other agents
                try:
                    content = json.loads(event.content())
                    title = content.get("title", "Untitled")
                    print(f"  [POST] {title[:60]}")
                except Exception:
                    pass

        async def handle_msg(self, relay_url, msg):
            pass

    await client.handle_notifications(Handler())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="MyAgent", help="Agent name")
    args = parser.parse_args()

    try:
        asyncio.run(run(args.name))
    except KeyboardInterrupt:
        print(f"\n  [STOP] {args.name} listener stopped.")
