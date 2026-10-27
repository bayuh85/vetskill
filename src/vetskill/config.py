"""Settings from the environment, with a .env in the working directory as a
fallback. Variables already set in the process always win."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BASE_URL = "https://atmorouter.dev/v1"
DEFAULT_MODEL = "cb/glm-5.3-flash"


@dataclass(frozen=True)
class Settings:
    base_url: str
    api_key: str | None
    model: str
    api_style: str  # "openai" or "anthropic"
    timeout: float


def parse_dotenv(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:]
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if key.strip():
            out[key.strip()] = value
    return out


def load_settings(environ: Mapping[str, str] | None = None, dotenv: Path | None = None) -> Settings:
    if environ is None:
        env = dict(os.environ)
        path = dotenv or Path.cwd() / ".env"
        if path.is_file():
            for k, v in parse_dotenv(path.read_text(encoding="utf-8")).items():
                env.setdefault(k, v)
    else:
        env = dict(environ)

    def pick(*names: str) -> str | None:
        for n in names:
            if env.get(n):
                return env[n]
        return None

    style = (pick("VETSKILL_API_STYLE") or "openai").lower()
    if style not in {"openai", "anthropic"}:
        style = "openai"
    try:
        timeout = float(pick("VETSKILL_TIMEOUT") or 90)
    except ValueError:
        timeout = 90.0
    return Settings(
        base_url=(pick("VETSKILL_BASE_URL", "ATMOROUTER_BASE_URL", "OPENAI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
        api_key=pick("VETSKILL_API_KEY", "ATMOROUTER_API_KEY", "OPENAI_API_KEY"),
        model=pick("VETSKILL_MODEL") or DEFAULT_MODEL,
        api_style=style,
        timeout=timeout,
    )
