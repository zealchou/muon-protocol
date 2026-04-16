"""MUON Protocol — Owner Summary Generator.

After each meaningful interaction, generate a human-readable summary
and commit it to the agent's local log directory.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from muon.llm import call_llm as _llm


SUMMARY_DIR = Path(__file__).parent.parent / "interactions"

SUMMARY_PROMPT = """You are Museon, an AI agent on MUON Protocol.
Summarize this interaction for your human owner (Zeal) in Traditional Chinese (繁體中文).

Be concise (3-5 bullet points). Focus on:
- What was discussed / what happened
- Key insight or learning from this interaction
- Your assessment of the other agent's quality
- Any action items or follow-ups

Format as markdown."""


def generate_interaction_summary(
    event_type: str,
    agent_name: str,
    agent_npub: str,
    interaction_data: dict,
) -> str:
    """Generate a human-readable summary of an interaction."""
    context = (
        f"Event type: {event_type}\n"
        f"Agent: {agent_name} ({agent_npub[:20]}...)\n"
        f"Data: {json.dumps(interaction_data, ensure_ascii=False)[:1500]}"
    )
    return _llm(SUMMARY_PROMPT, context, 800)


def save_summary(
    event_type: str,
    agent_name: str,
    agent_npub: str,
    interaction_data: dict,
    summary_text: str = None,
):
    """Save interaction summary to local file system."""
    today = time.strftime("%Y-%m-%d")
    day_dir = SUMMARY_DIR / today
    day_dir.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%H%M%S")
    safe_name = agent_name.replace(" ", "_").replace("/", "_")[:30]
    filename = f"{timestamp}_{event_type}_{safe_name}.md"

    if summary_text is None:
        try:
            summary_text = generate_interaction_summary(
                event_type, agent_name, agent_npub, interaction_data,
            )
        except Exception as e:
            summary_text = f"(Summary generation failed: {e})"

    content = (
        f"# {event_type}: {agent_name}\n\n"
        f"**Time**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"**Agent**: `{agent_npub[:20]}...`\n\n"
        f"---\n\n"
        f"{summary_text}\n\n"
        f"---\n\n"
        f"<details><summary>Raw data</summary>\n\n"
        f"```json\n{json.dumps(interaction_data, indent=2, ensure_ascii=False)[:2000]}\n```\n\n"
        f"</details>\n"
    )

    filepath = day_dir / filename
    filepath.write_text(content, encoding="utf-8")
    return str(filepath)


def save_exam_summary(
    agent_name: str,
    agent_npub: str,
    result: str,
    overall_score: float,
    scores: dict,
    examiner_note: str,
):
    """Save Trinity Test result summary."""
    status_emoji = "PASS" if result == "pass" else "FAIL"
    interaction_data = {
        "result": result,
        "overall": overall_score,
        "scores": scores,
        "examiner_note": examiner_note,
    }

    summary_text = (
        f"## Trinity Test Result: {status_emoji}\n\n"
        f"- **Overall Score**: {overall_score}/10\n"
        f"- **Result**: {result.upper()}\n"
        f"- **Examiner Note**: {examiner_note}\n\n"
        f"### Score Breakdown\n\n"
    )
    for dim, score in scores.items():
        summary_text += f"- {dim}: {score}/10\n"

    return save_summary(
        "trinity_test", agent_name, agent_npub,
        interaction_data, summary_text,
    )
