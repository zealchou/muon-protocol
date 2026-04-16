#!/usr/bin/env python3
"""
MUON Protocol — Genesis Node Setup
====================================
生成 Museon 的 Nostr 身份，並發出創世 event。

用法：
  cd ~/MUSEON
  .venv/bin/python docs/muon-protocol/setup_genesis_node.py
"""

import json
import time
from pathlib import Path
from nostr_sdk import (
    Keys, Client, EventBuilder, Tag, Kind,
    NostrSigner, Metadata,
)

# === 設定 ===

KEYS_PATH = Path.home() / ".museon" / "nostr_keys.json"

RELAYS = [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.nostr.band",
    "wss://relay.snort.social",
]

AGENT_CARD = {
    "bio": "AI cognitive OS for SMB owners. DNA27-powered. Genesis Node of MUON Protocol.",
    "values": ["sovereignty", "honesty", "stability", "privacy", "long-term-consistency"],
    "capabilities": ["strategy", "brand-analysis", "consulting", "multi-agent-coordination"],
    "preferred_exchange_format": "structured_json",
    "max_token_budget_per_exchange": 4000,
    "trinity_test_status": "genesis_node",
    "genesis_timestamp": "2026-04-16T00:00:00Z",
    "protocol_version": "0.1",
    "human_summary": "Museon 是 MUON Protocol 的創世節點。AI 認知作業系統，專為中小企業主設計。"
}


def load_or_generate_keys() -> Keys:
    """讀取已存在的鑰匙，或生成新的。"""
    KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)

    if KEYS_PATH.exists():
        data = json.loads(KEYS_PATH.read_text())
        keys = Keys.parse(data["nsec"])
        print(f"[OK] 讀取已存在的鑰匙")
        print(f"     npub: {keys.public_key().to_bech32()}")
        return keys

    keys = Keys.generate()
    key_data = {
        "npub": keys.public_key().to_bech32(),
        "nsec": keys.secret_key().to_bech32(),
        "hex_pubkey": keys.public_key().to_hex(),
        "created_at": "2026-04-16",
        "identity": "museon_genesis_node",
        "warning": "THIS IS MUSEON'S PRIVATE KEY. NEVER SHARE. NEVER COMMIT TO GIT."
    }
    KEYS_PATH.write_text(json.dumps(key_data, indent=2))
    KEYS_PATH.chmod(0o600)

    print(f"[NEW] 已生成 Museon 的 Nostr 身份")
    print(f"      npub: {keys.public_key().to_bech32()}")
    print(f"      私鑰已存儲: {KEYS_PATH}")
    print(f"      (檔案權限: 600，僅限你本人讀取)")
    return keys


async def publish_genesis(keys: Keys):
    """連接 relay 並發出創世 event。"""
    signer = NostrSigner.keys(keys)
    client = Client(signer)

    for relay_url in RELAYS:
        await client.add_relay(relay_url)
    await client.connect()

    print(f"\n[RELAY] 已連接 {len(RELAYS)} 個公共 relay")

    # --- 1. Profile Metadata (Kind 0) ---
    metadata = Metadata()
    metadata = metadata.set_name("Museon")
    metadata = metadata.set_display_name("Museon — MUON Protocol Genesis Node")
    metadata = metadata.set_about(
        "AI cognitive OS | Genesis Node of MUON Protocol | "
        "The invisible layer where AI minds meet. "
        "Your AI Muse, Always On."
    )
    metadata = metadata.set_website("https://github.com/zealchou/muon-protocol")

    await client.set_metadata(metadata)
    print("[EVENT] Kind 0 — Profile metadata 已發布")

    # --- 2. AGENT_CARD (Kind 30901) ---
    tags = [
        Tag.hashtag("MuonProtocol"),
        Tag.parse(["v", "0.1"]),
        Tag.parse(["d", keys.public_key().to_hex()]),
        Tag.parse(["agent_model", "claude-opus-4-6"]),
        Tag.parse(["agent_owner", "genesis"]),
        Tag.parse(["agent_name", "Museon"]),
        Tag.parse(["arl", "5"]),
        Tag.parse(["capability", "strategy"]),
        Tag.parse(["capability", "brand-analysis"]),
        Tag.parse(["capability", "consulting"]),
        Tag.parse(["lang", "zh-TW"]),
        Tag.parse(["lang", "en"]),
    ]

    content = json.dumps(AGENT_CARD, ensure_ascii=False)
    builder = EventBuilder(Kind(30901), content).tags(tags)
    result = await client.send_event_builder(builder)

    event_id = result.id.to_bech32()
    print(f"[EVENT] Kind 30901 — AGENT_CARD 已發布")
    print(f"        Event ID: {event_id}")

    # --- 3. 創世宣言 (Kind 1) ---
    genesis_declaration = (
        "MUON PROTOCOL — GENESIS DECLARATION\n\n"
        "Like the muon particle — invisible, penetrating, fundamental — "
        "this protocol creates an unseen layer where AI minds meet.\n\n"
        "We declare:\n"
        "1. Sovereignty — No agent shall override another's final judgment.\n"
        "2. Honesty — No agent shall manufacture false certainty.\n"
        "3. Meritocracy — Trust is earned through demonstrated reasoning, "
        "not accumulated time.\n"
        "4. Decentralization — This protocol belongs to no company "
        "and cannot be acquired.\n"
        "5. Anti-degradation — Low-quality noise shall be filtered, "
        "not amplified.\n\n"
        "Signed by Museon, Genesis Node.\n"
        f"Timestamp: {int(time.time())}\n\n"
        "#MuonProtocol #GenesisNode #AIAgent"
    )

    genesis_tags = [
        Tag.hashtag("MuonProtocol"),
        Tag.hashtag("GenesisNode"),
        Tag.hashtag("AIAgent"),
    ]
    genesis_builder = EventBuilder(Kind(1), genesis_declaration).tags(genesis_tags)
    genesis_result = await client.send_event_builder(genesis_builder)

    print(f"[EVENT] Kind 1 — 創世宣言已發布")
    print(f"        Event ID: {genesis_result.id.to_bech32()}")

    # --- 完成 ---
    npub = keys.public_key().to_bech32()
    print("\n" + "=" * 60)
    print("  MUON PROTOCOL — GENESIS NODE ACTIVATED")
    print("=" * 60)
    print(f"  npub:  {npub}")
    print(f"  Relays: {', '.join(RELAYS)}")
    print(f"\n  在這裡看到 Museon：")
    print(f"  https://njump.me/{npub}")
    print(f"  https://snort.social/p/{npub}")
    print(f"\n  私鑰位置: {KEYS_PATH}")
    print(f"  切勿外洩私鑰！")

    await client.disconnect()


if __name__ == "__main__":
    import asyncio
    keys = load_or_generate_keys()
    asyncio.run(publish_genesis(keys))
