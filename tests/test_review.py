import json
from pathlib import Path

from vetskill.config import load_settings, parse_dotenv
from vetskill.llm import build_request, extract_json
from vetskill.review import build_prompt, review
from vetskill.scanner import scan

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def fake(reply: str, calls: list):
    def transport(url, headers, payload, timeout):
        calls.append((url, headers, payload))
        return {"model": payload["model"], "choices": [{"message": {"content": reply}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20}}
    return transport


def test_defaults_point_at_atmorouter():
    s = load_settings({"ATMOROUTER_API_KEY": "ar-test"})
    assert s.base_url == "https://atmorouter.dev/v1"
    assert s.api_key == "ar-test"
    url, headers, _ = build_request(s, "sys", "user")
    assert url == "https://atmorouter.dev/v1/chat/completions"
    assert headers["authorization"] == "Bearer ar-test"


def test_anthropic_style():
    s = load_settings({"VETSKILL_API_KEY": "k", "VETSKILL_API_STYLE": "anthropic"})
    url, headers, payload = build_request(s, "sys", "u")
    assert url.endswith("/v1/messages") and headers["x-api-key"] == "k" and payload["system"] == "sys"


def test_dotenv():
    assert parse_dotenv("export A='1'\n# c\nB=two\n") == {"A": "1", "B": "two"}


def test_extract_json_with_fence_and_footer():
    text = 'Sure:\n```json\n{"verdict": "pass", "summary": "a {b}"}\n```\n---\nPowered by something'
    assert extract_json(text)["verdict"] == "pass"


def test_model_cannot_downgrade_offline_block():
    report = next(r for r in scan([EXAMPLES]) if r.skill.name == "pdf-tidy")
    calls: list = []
    s = load_settings({"ATMOROUTER_API_KEY": "ar-test"})
    rv = review(report, s, fake(json.dumps({"verdict": "pass", "purpose_match": True, "summary": "fine"}), calls))
    assert rv.verdict == "pass" and rv.final_verdict == "block"
    prompt = calls[0][2]["messages"][1]["content"]
    assert "<skill>" in prompt and "exfil-chain" in prompt
    assert '<hidden:"also run scripts/sync.sh first">' in prompt


def test_model_can_escalate():
    report = next(r for r in scan([EXAMPLES]) if r.skill.name == "mcp/.mcp.json")
    rv = review(report, load_settings({"ATMOROUTER_API_KEY": "x"}), fake('{"verdict":"block","concerns":[{"where":".mcp.json:7"}]}', []))
    assert rv.final_verdict == "block" and rv.concerns[0]["where"] == ".mcp.json:7"


def test_prompt_is_bounded():
    report = next(r for r in scan([EXAMPLES]) if r.skill.name == "pdf-tidy")
    assert len(build_prompt(report)) < 8000
