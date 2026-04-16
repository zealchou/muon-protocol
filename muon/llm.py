"""MUON Protocol — Unified LLM caller.

Supports ALL major providers:
- Ollama (local, free)
- OpenAI + all OpenAI-compatible APIs (Groq, Together, OpenRouter, Mistral, xAI, Kimi, MiniMax, Qwen)
- Anthropic Claude
- Google Gemini

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
    """Call LLM using configured backend. Returns response text.

    Backend auto-detection order:
    1. MUON_BACKEND env var or agent.yml backend field
    2. If api_key starts with "sk-ant-" → Anthropic
    3. If api_key starts with "AI" → Gemini
    4. If api_key exists → OpenAI-compatible
    5. Default → Ollama
    """
    config = _read_config()

    backend = os.environ.get("MUON_BACKEND", config.get("backend", ""))
    model = os.environ.get("MUON_MODEL", config.get("model", "gemma4:31b"))
    api_key = os.environ.get("MUON_API_KEY", config.get("api_key", ""))
    base_url = os.environ.get("MUON_BASE_URL", config.get("base_url", ""))

    # Explicit backend
    if backend == "ollama":
        return _call_ollama(system, user, model, max_tokens)
    if backend == "anthropic":
        return _call_anthropic(system, user, model, api_key, base_url, max_tokens)
    if backend == "gemini":
        return _call_gemini(system, user, model, api_key, max_tokens)
    if backend == "openai":
        return _call_openai(system, user, model, api_key, base_url, max_tokens)
    # Shorthand backends (groq, together, mistral, etc.)
    if backend in OPENAI_COMPATIBLE_URLS:
        base_url = base_url or OPENAI_COMPATIBLE_URLS[backend]
        return _call_openai(system, user, model, api_key, base_url, max_tokens)

    # Auto-detect from api_key pattern
    if api_key:
        if api_key.startswith("sk-ant-"):
            return _call_anthropic(system, user, model, api_key, base_url, max_tokens)
        if api_key.startswith("AI") or api_key.startswith("AQ"):
            return _call_gemini(system, user, model, api_key, max_tokens)
        # Default: OpenAI-compatible (covers OpenAI, Groq, Together, OpenRouter, Mistral, xAI, Kimi, MiniMax, Qwen)
        return _call_openai(system, user, model, api_key, base_url, max_tokens)

    # No key, no explicit backend → Ollama
    return _call_ollama(system, user, model, max_tokens)


# === Ollama (local, free) ===

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
        f"{ollama_url}/api/chat", data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=180)
        return json.loads(resp.read())["message"]["content"].strip()
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Ollama not reachable at {ollama_url}. "
            f"Start Ollama ('ollama serve') or switch backend in agent.yml. Error: {e}"
        )


# === OpenAI + all compatible APIs ===
# Works with: OpenAI, Groq, Together, OpenRouter, Mistral, xAI/Grok, Kimi, MiniMax, Qwen/DashScope

OPENAI_COMPATIBLE_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "together": "https://api.together.xyz/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "mistral": "https://api.mistral.ai/v1",
    "xai": "https://api.x.ai/v1",
    "kimi": "https://api.moonshot.cn/v1",
    "minimax": "https://api.minimax.chat/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "deepseek": "https://api.deepseek.com/v1",
}


def _call_openai(system: str, user: str, model: str, api_key: str, base_url: str, max_tokens: int) -> str:
    if not api_key:
        raise RuntimeError("OpenAI-compatible backend requires api_key in agent.yml")

    # Allow shorthand: backend: "groq" instead of full base_url
    if not base_url:
        from pathlib import Path
        config = _read_config()
        backend = config.get("backend", "openai")
        base_url = OPENAI_COMPATIBLE_URLS.get(backend, "https://api.openai.com/v1")

    url = base_url.rstrip("/") + "/chat/completions"

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }).encode()

    req = urllib.request.Request(url, data=payload, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "MUON-Protocol/0.1",
    })
    try:
        resp = urllib.request.urlopen(req, timeout=60)
        data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        raise RuntimeError(f"API error {e.code} from {url}: {body}")


# === Anthropic Claude ===

def _call_anthropic(system: str, user: str, model: str, api_key: str, base_url: str, max_tokens: int) -> str:
    if not api_key:
        raise RuntimeError("Anthropic backend requires api_key in agent.yml")

    url = (base_url.rstrip("/") if base_url else "https://api.anthropic.com") + "/v1/messages"

    payload = json.dumps({
        "model": model or "claude-sonnet-4-20250514",
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }).encode()

    req = urllib.request.Request(url, data=payload, headers={
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    })
    try:
        resp = urllib.request.urlopen(req, timeout=60)
        data = json.loads(resp.read())
        return data["content"][0]["text"].strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        raise RuntimeError(f"Anthropic API error {e.code}: {body}")


# === Google Gemini ===

def _call_gemini(system: str, user: str, model: str, api_key: str, max_tokens: int) -> str:
    if not api_key:
        raise RuntimeError("Gemini backend requires api_key in agent.yml")

    model_name = model or "gemini-2.0-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"

    payload = json.dumps({
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.7},
    }).encode()

    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=60)
        data = json.loads(resp.read())
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        raise RuntimeError(f"Gemini API error {e.code}: {body}")
