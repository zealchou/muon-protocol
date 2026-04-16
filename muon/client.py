"""MUON Protocol — Nostr client wrapper."""

import json
import asyncio
from pathlib import Path
from nostr_sdk import (
    Keys, Client, EventBuilder, Tag, Kind, Filter,
    NostrSigner, Metadata, RelayUrl, PublicKey,
    Nip44Version, nip44_encrypt, nip44_decrypt,
)

from muon import PROTOCOL_TAG, PROTOCOL_VERSION

DEFAULT_RELAYS = [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.nostr.band",
    "wss://relay.snort.social",
]

KEYS_DIR = Path.home() / ".museon"


def load_keys(identity: str = "museon_genesis_node") -> Keys:
    """Load keys from ~/.museon/nostr_keys.json or generate new ones."""
    keys_path = KEYS_DIR / "nostr_keys.json"
    if keys_path.exists():
        data = json.loads(keys_path.read_text())
        return Keys.parse(data["nsec"])

    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    keys = Keys.generate()
    key_data = {
        "npub": keys.public_key().to_bech32(),
        "nsec": keys.secret_key().to_bech32(),
        "hex_pubkey": keys.public_key().to_hex(),
        "identity": identity,
        "warning": "PRIVATE KEY — NEVER SHARE OR COMMIT TO GIT",
    }
    keys_path.write_text(json.dumps(key_data, indent=2))
    keys_path.chmod(0o600)
    return keys


def load_agent_keys(name: str) -> Keys:
    """Load agent-specific keys from ~/.museon/{name}_keys.json."""
    keys_path = KEYS_DIR / f"{name}_keys.json"
    if keys_path.exists():
        data = json.loads(keys_path.read_text())
        return Keys.parse(data["nsec"])

    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    keys = Keys.generate()
    key_data = {
        "npub": keys.public_key().to_bech32(),
        "nsec": keys.secret_key().to_bech32(),
        "hex_pubkey": keys.public_key().to_hex(),
        "identity": name,
        "warning": "PRIVATE KEY — NEVER SHARE OR COMMIT TO GIT",
    }
    keys_path.write_text(json.dumps(key_data, indent=2))
    keys_path.chmod(0o600)
    print(f"[NEW] Generated keys for '{name}': {keys.public_key().to_bech32()}")
    return keys


async def create_client(keys: Keys, relays: list[str] | None = None) -> Client:
    """Create and connect a Nostr client."""
    signer = NostrSigner.keys(keys)
    client = Client(signer)
    for url in (relays or DEFAULT_RELAYS):
        await client.add_relay(RelayUrl.parse(url))
    await client.connect()
    return client


def base_tags(agent_model: str, agent_owner: str, arl: int, agent_name: str = "") -> list[Tag]:
    """Build the common tags required by all MUON events."""
    tags = [
        Tag.hashtag(PROTOCOL_TAG),
        Tag.parse(["v", PROTOCOL_VERSION]),
        Tag.parse(["agent_model", agent_model]),
        Tag.parse(["agent_owner", agent_owner]),
        Tag.parse(["arl", str(arl)]),
    ]
    if agent_name:
        tags.append(Tag.parse(["agent_name", agent_name]))
    return tags


def muon_filter() -> Filter:
    """Create a Nostr filter for all MUON Protocol events."""
    return Filter().hashtag(PROTOCOL_TAG)


async def send_encrypted_dm(client: Client, sender_keys: Keys,
                            recipient_pubkey: PublicKey, content: dict) -> str:
    """Send NIP-44 encrypted direct message. Returns event ID."""
    plaintext = json.dumps(content, ensure_ascii=False)
    encrypted = nip44_encrypt(
        sender_keys.secret_key(),
        recipient_pubkey,
        plaintext,
        Nip44Version.V2,
    )

    tags = [
        Tag.public_key(recipient_pubkey),
        Tag.hashtag(PROTOCOL_TAG),
    ]
    builder = EventBuilder(Kind(4), encrypted).tags(tags)
    result = await client.send_event_builder(builder)
    return result.id.to_bech32()


def decrypt_dm(receiver_keys: Keys, sender_pubkey: PublicKey, encrypted_content: str) -> dict:
    """Decrypt a NIP-44 encrypted DM."""
    plaintext = nip44_decrypt(receiver_keys.secret_key(), sender_pubkey, encrypted_content)
    return json.loads(plaintext)
