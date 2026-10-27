"""One chat call over an OpenAI-compatible or Anthropic-compatible endpoint.
Standard library only. Only `vetskill review` touches the network."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from vetskill.config import Settings

Transport = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]


class LLMError(RuntimeError):
    pass


@dataclass
class Completion:
    text: str
    model: str
    tokens_in: int
    tokens_out: int


def urllib_transport(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    req.add_header("user-agent", "vetskill/0.1")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        raise LLMError(f"HTTP {exc.code} from {url}: {body}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise LLMError(f"cannot reach {url}: {exc}") from exc


def build_request(s: Settings, system: str, user: str) -> tuple[str, dict[str, str], dict[str, Any]]:
    if s.api_style == "anthropic":
        return (
            s.base_url + "/messages",
            {"content-type": "application/json", "x-api-key": s.api_key or "", "anthropic-version": "2023-06-01"},
            {"model": s.model, "max_tokens": 1200, "system": system, "messages": [{"role": "user", "content": user}]},
        )
    return (
        s.base_url + "/chat/completions",
        {"content-type": "application/json", "authorization": f"Bearer {s.api_key or ''}"},
        {
            "model": s.model,
            "temperature": 0,
            "max_tokens": 1200,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        },
    )


def complete(s: Settings, system: str, user: str, transport: Transport | None = None) -> Completion:
    if not s.api_key:
        raise LLMError("no API key: set ATMOROUTER_API_KEY (or VETSKILL_API_KEY / OPENAI_API_KEY)")
    url, headers, payload = build_request(s, system, user)
    data = (transport or urllib_transport)(url, headers, payload, s.timeout)
    if s.api_style == "anthropic":
        parts = data.get("content") or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text")
        usage = data.get("usage") or {}
        return Completion(text, data.get("model", s.model), int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0)))
    try:
        text = data["choices"][0]["message"].get("content") or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"unexpected response: {str(data)[:200]}") from exc
    usage = data.get("usage") or {}
    return Completion(text, data.get("model", s.model), int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0)))


def extract_json(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of a reply that may carry fences or a footer."""
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start : i + 1])
                        if isinstance(obj, dict):
                            return obj
                    except ValueError:
                        pass
                    break
        start = text.find("{", start + 1)
    raise LLMError("model reply contained no JSON object")
