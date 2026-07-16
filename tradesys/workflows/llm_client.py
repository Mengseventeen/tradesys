from __future__ import annotations

import json
import re
from typing import Any


class LLMRequiredError(RuntimeError):
    """Raised when a workflow that is meant to be LLM-driven has no LLM client."""


def require_llm(llm: Any | None, workflow_name: str) -> Any:
    if llm is None:
        raise LLMRequiredError(
            f"{workflow_name} requires an LLM client. Configure OPENAI_API_KEY, "
            "OPENAI_BASE_URL, and OPENAI_MODEL, or use an explicit local fallback mode."
        )
    return llm


def invoke_text(llm: Any, system: str, user: str) -> str:
    response = llm.invoke([
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ])
    return str(getattr(response, "content", response))


def invoke_json(llm: Any, system: str, user: str) -> dict[str, Any]:
    text = invoke_text(
        llm,
        system + "\nReturn exactly one valid JSON object. Do not use markdown fences.",
        user,
    )
    return parse_json_object(text)


def parse_json_object(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
