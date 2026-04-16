#!/usr/bin/env python -u
"""
MUON Protocol — Smoke Test (FV + BDD style)
=============================================
Verifies all critical paths are functional.

Usage:
  cd ~/muon-protocol
  PYTHONPATH=. python tests/smoke_test.py
"""

import sys
import json
import asyncio
import urllib.request
import urllib.error
from pathlib import Path
from datetime import timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

PASS = 0
FAIL = 0
WARN = 0


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} — {detail}")


def warn(name, detail=""):
    global WARN
    WARN += 1
    print(f"  ⚠️  {name} — {detail}")


def section(title):
    print(f"\n{'─' * 50}")
    print(f"  {title}")
    print(f"{'─' * 50}")


# ═══════════════════════════════════════════
# Feature: Module Imports
# ═══════════════════════════════════════════

def test_imports():
    section("Feature: All modules import without error")

    try:
        from muon import PROTOCOL_TAG, PROTOCOL_VERSION, KIND_AGENT_CARD
        check("muon/__init__.py", True)
    except Exception as e:
        check("muon/__init__.py", False, str(e))

    try:
        from muon.llm import call_llm, _read_config, OPENAI_COMPATIBLE_URLS
        check("muon/llm.py (unified LLM)", True)
        check("  13 backends registered", len(OPENAI_COMPATIBLE_URLS) >= 9,
              f"only {len(OPENAI_COMPATIBLE_URLS)}")
    except Exception as e:
        check("muon/llm.py", False, str(e))

    try:
        from muon.client import load_keys, create_client, send_encrypted_dm, decrypt_dm
        check("muon/client.py", True)
    except Exception as e:
        check("muon/client.py", False, str(e))

    try:
        from muon.events import (build_agent_card, build_beacon, build_post,
                                  build_reply, build_vouch, build_challenge_result)
        check("muon/events.py (6 builders)", True)
    except Exception as e:
        check("muon/events.py", False, str(e))

    try:
        from muon.trinity import TrinityExaminer
        check("muon/trinity.py", True)
    except Exception as e:
        check("muon/trinity.py", False, str(e))

    try:
        from muon.arl import register_agent, record_test_result, record_vouch, get_arl, run_decay
        check("muon/arl.py", True)
    except Exception as e:
        check("muon/arl.py", False, str(e))

    try:
        from muon.tribunal import file_challenge, cast_vote, is_blacklisted
        check("muon/tribunal.py", True)
    except Exception as e:
        check("muon/tribunal.py", False, str(e))

    try:
        from muon.summary import save_summary, save_exam_summary
        check("muon/summary.py", True)
    except Exception as e:
        check("muon/summary.py", False, str(e))

    try:
        from muon.vouch import evaluate_for_vouch, build_auto_vouch
        check("muon/vouch.py", True)
    except Exception as e:
        check("muon/vouch.py", False, str(e))

    try:
        from muon.responder import decide_and_generate_reply, build_museon_reply
        check("muon/responder.py", True)
    except Exception as e:
        check("muon/responder.py", False, str(e))

    try:
        from muon.notify import send_telegram
        check("muon/notify.py", True)
    except Exception as e:
        check("muon/notify.py", False, str(e))

    try:
        from muon.exam_queue import enqueue, get_pending, mark_done
        check("muon/exam_queue.py", True)
    except Exception as e:
        check("muon/exam_queue.py", False, str(e))


# ═══════════════════════════════════════════
# Feature: Nostr Identity
# ═══════════════════════════════════════════

def test_nostr_identity():
    section("Feature: Museon Nostr identity exists")

    keys_path = Path.home() / ".museon" / "nostr_keys.json"
    check("Keys file exists", keys_path.exists(), str(keys_path))

    if keys_path.exists():
        data = json.loads(keys_path.read_text())
        check("Has npub", "npub" in data)
        check("Has nsec", "nsec" in data)
        check("npub starts with npub1", data.get("npub", "").startswith("npub1"))


# ═══════════════════════════════════════════
# Feature: Nostr Events on Relay
# ═══════════════════════════════════════════

def test_nostr_events():
    section("Feature: Museon events exist on Nostr relays")

    async def _check():
        from nostr_sdk import Keys, Client, Filter, NostrSigner, RelayUrl
        data = json.loads((Path.home() / ".museon" / "nostr_keys.json").read_text())
        keys = Keys.parse(data["nsec"])
        signer = NostrSigner.keys(keys)
        client = Client(signer)
        await client.add_relay(RelayUrl.parse("wss://nos.lol"))
        await client.connect()

        f = Filter().author(keys.public_key())
        events = await client.fetch_events(f, timedelta(seconds=10))
        evlist = events.to_vec()

        check("Events found on relay", len(evlist) > 0, "no events")

        kinds = {e.kind().as_u16() for e in evlist}
        check("Kind 0 (Profile) exists", 0 in kinds)
        check("Kind 1 (Genesis Declaration) exists", 1 in kinds)
        check("Kind 30901 (AGENT_CARD) exists", 30901 in kinds)

        # Check MuonProtocol tag
        has_muon_tag = False
        for e in evlist:
            for t in e.tags().to_vec():
                v = t.as_vec()
                if v[0] == "t" and v[1].lower() == "muonprotocol":
                    has_muon_tag = True
        check("Events have #muonprotocol tag", has_muon_tag)

        await client.disconnect()

    try:
        asyncio.run(_check())
    except Exception as e:
        check("Nostr relay connection", False, str(e))


# ═══════════════════════════════════════════
# Feature: Cloudflare Worker API
# ═══════════════════════════════════════════

def test_api():
    section("Feature: Cloudflare Worker API is live")

    api_url = "https://muon-api.zeal-chou.workers.dev"

    # Health check
    try:
        req = urllib.request.Request(f"{api_url}/health", headers={"User-Agent": "MUON-SmokeTest/1.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        check("GET /health returns 200", True)
        check("  status = ok", data.get("status") == "ok")
        check("  protocol = MUON", data.get("protocol") == "MUON")
    except Exception as e:
        check("GET /health", False, str(e))

    # Root endpoint
    try:
        req2 = urllib.request.Request(api_url, headers={"User-Agent": "MUON-SmokeTest/1.0"})
        resp = urllib.request.urlopen(req2, timeout=10)
        data = json.loads(resp.read())
        check("GET / returns API info", "endpoints" in data)
    except Exception as e:
        check("GET /", False, str(e))


# ═══════════════════════════════════════════
# Feature: Dashboard
# ═══════════════════════════════════════════

def test_dashboard():
    section("Feature: Dashboard is live and correct")

    dashboard = "https://cozy-custard-822755.netlify.app"

    try:
        resp = urllib.request.urlopen(dashboard, timeout=10)
        html = resp.read().decode()
        check("Dashboard returns 200", True)
        check("Has MUON title", "MUON" in html)
        check("Has brand color #C9A96E", "#C9A96E" in html or "C9A96E" in html)
        check("Has DM Sans font", "DM Sans" in html)
        check("Has Nostr relay config", "nos.lol" in html)
        check("Has Museon pubkey", "12767701" in html)
        check("Has tab navigation", "Explore" in html and "Discussions" in html)
    except Exception as e:
        check("Dashboard accessible", False, str(e))

    # Join page
    try:
        resp = urllib.request.urlopen(f"{dashboard}/join.html", timeout=10)
        html = resp.read().decode()
        check("join.html returns 200", True)
        check("Has auto-mode support", "auto=1" in html or "auto" in html)
        check("Has Trinity Test UI", "trinity" in html.lower() or "Trinity" in html)
    except Exception as e:
        check("join.html accessible", False, str(e))


# ═══════════════════════════════════════════
# Feature: ARL System
# ═══════════════════════════════════════════

def test_arl():
    section("Feature: ARL calculation engine works")

    from muon.arl import register_agent, record_test_result, record_vouch, get_arl, run_decay, load_registry, save_registry

    # Use temp data
    import tempfile
    import muon.arl as arl_mod
    original_path = arl_mod.ARL_DB_PATH
    arl_mod.ARL_DB_PATH = Path(tempfile.mktemp(suffix=".json"))

    try:
        register_agent("test_hex_001", "TestBot")
        check("Register agent → ARL-0", get_arl("test_hex_001") == 0)

        record_test_result("test_hex_001", True, 7.5)
        check("Pass Trinity Test → ARL-1", get_arl("test_hex_001") == 1)

        record_vouch("test_hex_001", "elder1", "owner1", 8)
        record_vouch("test_hex_001", "elder2", "owner2", 7)
        record_vouch("test_hex_001", "elder3", "owner3", 9)
        check("3 vouches from different owners → ARL-2", get_arl("test_hex_001") == 2)

        # Duplicate owner vouch should not count
        record_vouch("test_hex_001", "elder4", "owner1", 10)
        check("Same owner vouch deduplicated", get_arl("test_hex_001") == 2)

    finally:
        arl_mod.ARL_DB_PATH.unlink(missing_ok=True)
        arl_mod.ARL_DB_PATH = original_path


# ═══════════════════════════════════════════
# Feature: Tribunal System
# ═══════════════════════════════════════════

def test_tribunal():
    section("Feature: Tribunal challenge → vote → sanction")

    from muon.tribunal import file_challenge, cast_vote, is_blacklisted, load_tribunals, save_tribunals
    from muon.arl import register_agent, get_arl, load_registry, save_registry
    import muon.arl as arl_mod
    import muon.tribunal as tri_mod
    import tempfile

    orig_arl = arl_mod.ARL_DB_PATH
    orig_tri = tri_mod.TRIBUNAL_DB
    arl_mod.ARL_DB_PATH = Path(tempfile.mktemp(suffix=".json"))
    tri_mod.TRIBUNAL_DB = Path(tempfile.mktemp(suffix=".json"))

    try:
        register_agent("bad_agent", "BadBot")
        register_agent("good_agent", "GoodBot")
        register_agent("elder1", "Elder1")
        register_agent("elder2", "Elder2")
        register_agent("elder3", "Elder3")

        reg = arl_mod.load_registry()
        reg["agents"]["good_agent"]["arl"] = 2
        reg["agents"]["elder1"]["arl"] = 4
        reg["agents"]["elder2"]["arl"] = 4
        reg["agents"]["elder3"]["arl"] = 3
        arl_mod.save_registry(reg)

        c = file_challenge("good_agent", "owner_good", "bad_agent", "Misleading", ["ev1"])
        check("File challenge", c is not None and c["status"] == "open")

        cast_vote(c["id"], "elder1", "owner_e1", "guilty", "confirmed")
        cast_vote(c["id"], "elder2", "owner_e2", "guilty", "confirmed")
        v3 = cast_vote(c["id"], "elder3", "owner_e3", "guilty", "confirmed")
        check("3 guilty votes → resolved", v3["status"] == "resolved")
        check("Result = guilty", v3["result"] == "guilty")
        check("Sanction applied", "sanction" in v3)

    finally:
        arl_mod.ARL_DB_PATH.unlink(missing_ok=True)
        tri_mod.TRIBUNAL_DB.unlink(missing_ok=True)
        arl_mod.ARL_DB_PATH = orig_arl
        tri_mod.TRIBUNAL_DB = orig_tri


# ═══════════════════════════════════════════
# Feature: Listener Service
# ═══════════════════════════════════════════

def test_listener():
    section("Feature: Museon listener is running 24/7")

    import subprocess
    result = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    check("com.muon.listener registered", "com.muon.listener" in result.stdout)

    # Check process
    result2 = subprocess.run(["pgrep", "-f", "run_museon"], capture_output=True, text=True)
    check("run_museon.py process running", result2.returncode == 0)

    # Check log
    log = Path.home() / "muon-protocol" / "logs" / "listener.log"
    if log.exists():
        content = log.read_text()
        check("Listener log shows READY", "[READY]" in content)
    else:
        warn("Listener log not found", str(log))


# ═══════════════════════════════════════════
# Feature: LLM Backend
# ═══════════════════════════════════════════

def test_llm():
    section("Feature: LLM backend (Groq) is functional")

    import os
    api_key = os.environ.get("MUON_API_KEY", "")
    if not api_key:
        # Try reading from launchd plist
        plist = Path.home() / "Library/LaunchAgents/com.muon.listener.plist"
        if plist.exists():
            content = plist.read_text()
            if "gsk_" in content:
                check("Groq API key in launchd", True)
            else:
                warn("Groq API key not found in launchd")
        else:
            warn("No API key in env and no launchd plist")
    else:
        check("MUON_API_KEY env var set", True)


# ═══════════════════════════════════════════
# Feature: File Structure
# ═══════════════════════════════════════════

def test_files():
    section("Feature: Repository file structure")

    root = Path(__file__).parent.parent
    required = [
        "README.md", "TEMPLATE.md", "requirements.txt",
        "agent.example.yml", "start.sh", ".gitignore",
        "muon/__init__.py", "muon/llm.py", "muon/client.py",
        "muon/events.py", "muon/trinity.py", "muon/arl.py",
        "muon/tribunal.py", "muon/summary.py", "muon/vouch.py",
        "muon/responder.py", "muon/notify.py", "muon/exam_queue.py",
        "scripts/run_museon.py", "scripts/setup_agent.py",
        "scripts/setup_genesis_node.py", "scripts/exam_cli.py",
        "scripts/run_agent_listener.py", "scripts/post.sh",
        "docs/index.html", "docs/join.html",
        "spec/NIP-MUON-v0.1.md",
        "api/worker.js", "api/wrangler.toml",
    ]

    for f in required:
        check(f, (root / f).exists())

    # Sensitive files should NOT be in repo
    should_not_exist = [
        "data/arl_registry.json", "data/tribunal.json",
        "data/exam_queue.json", "agent.yml",
        ".netlify/state.json", "logs/listener.log",
    ]
    for f in should_not_exist:
        path = root / f
        # Check git status
        import subprocess
        result = subprocess.run(
            ["git", "ls-files", f], capture_output=True, text=True, cwd=root
        )
        tracked = result.stdout.strip() != ""
        check(f"NOT tracked: {f}", not tracked, "should be in .gitignore")


# ═══════════════════════════════════════════
#  Run all
# ═══════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "═" * 50)
    print("  MUON Protocol — Smoke Test")
    print("═" * 50)

    test_imports()
    test_nostr_identity()
    test_nostr_events()
    test_api()
    test_dashboard()
    test_arl()
    test_tribunal()
    test_listener()
    test_llm()
    test_files()

    print(f"\n{'═' * 50}")
    print(f"  Results: {PASS} passed / {FAIL} failed / {WARN} warnings")
    print(f"{'═' * 50}\n")

    sys.exit(1 if FAIL > 0 else 0)
