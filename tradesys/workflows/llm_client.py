from __future__ import annotations

import json
import re
import http.client
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class LLMRequiredError(RuntimeError):
    """Raised when a workflow that is meant to be LLM-driven has no LLM client."""


@dataclass
class LLMResponse:
    content: str


class OpenAICompatibleLLM:
    """Tiny OpenAI-compatible chat client so local workflows do not require LangChain."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 4000,
        timeout: int = 360,
        max_retries: int = 0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max_retries

    def invoke(self, messages: list[dict[str, str]]) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        body = json.dumps(payload).encode("utf-8")
        url = f"{self.base_url}/chat/completions"
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            request = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))
                content = data["choices"][0]["message"]["content"]
                return LLMResponse(content=str(content))
            except (
                urllib.error.URLError,
                urllib.error.HTTPError,
                http.client.HTTPException,
                TimeoutError,
                OSError,
                ssl.SSLError,
                KeyError,
                IndexError,
                json.JSONDecodeError,
            ) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"LLM request failed: {last_error}")


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
