"""MUON Protocol — Unified LLM caller.

Supports Ollama (local, free) and OpenAI-compatible APIs (GPT, Groq, Together, etc.)
Configured via agent.yml or environment variables.
"""

import json
import os
import urllib.request
import urllib.error


def _read_config() -> dict:
    """Read llm config from agent.yml if it exists."""
    from pathlib import Path
    yml_path = Path(__file__).parent.parent / "agent.yml"
    if not yml_path.exists():
        return {}
    # Minimal YAML parsing (no dependency needed)
    config = {}
    text = yml_path.read_text()
    in_llm = False
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("llm:"):
            in_llm = True
            continue
        if in_llm and stripped and not stripped.startswith("#"):
            if not line.startswith(" ") and not line.startswith("\t"):
                in_llm = False
                continue
            if ":" in stripped:
                key, val = stripped.split(":", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if val:
                    config[key] = val
    return config


def call_llm(system: str, user: str, max_tokens: int = 1000) -> str:
    """Call LLM using configured backend. Returns response text."""
    config = _read_config()

    backend = os.environ.get("MUON_BACKEND", config.get("backend", "ollama"))
    model = os.environ.get("MUON_MODEL", config.get("model", "gemma4:31b"))
    api_key = os.environ.get("MUON_API_KEY", config.get("api_key", ""))
    base_url = os.environ.get("MUON_BASE_URL", config.get("base_url", ""))

    if backend == "openai" or api_key:
        return _call_openai(system, user, model, api_key, base_url, max_tokens)
    else:
        return _call_ollama(system, user, model, max_tokens)


def _call_ollama(system: str, user: str, model: str, max_tokens: int) -> str:
    ollama_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"num_predict": max_tokens, "temperature": 0.7},
    }).encode()

    req = urllib.request.Request(
        f"{ollama_url}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=180)
        return json.loads(resp.read())["message"]["content"].strip()
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Ollama not reachable at {ollama_url}. "
            f"Either start Ollama ('ollama serve') or switch to OpenAI API in agent.yml. "
            f"Error: {e}"
        )


def _call_openai(system: str, user: str, model: str, api_key: str, base_url: str, max_tokens: int) -> str:
    if not api_key:
        raise RuntimeError(
            "OpenAI backend requires api_key in agent.yml or MUON_API_KEY env var"
        )

    url = (base_url.rstrip("/") if base_url else "https://api.openai.com/v1") + "/chat/completions"

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        resp = urllib.request.urlopen(req, timeout=60)
        data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        raise RuntimeError(f"OpenAI API error {e.code}: {body}")
