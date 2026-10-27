import json
from pathlib import Path

from vetskill.cli import main

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_scan_exit_codes(capsys):
    assert main(["scan", str(EXAMPLES / "skills" / "changelog-writer")]) == 0
    assert main(["scan", str(EXAMPLES / "skills" / "pdf-tidy")]) == 1
    assert main(["scan", str(EXAMPLES / "mcp")]) == 0
    assert main(["scan", str(EXAMPLES / "mcp"), "--fail-on", "medium"]) == 1
    assert main(["scan", str(EXAMPLES), "--fail-on", "never"]) == 0
    assert main(["scan", "/nope/missing"]) == 2


def test_json_and_sarif(tmp_path, capsys):
    main(["scan", str(EXAMPLES), "--format", "json", "--fail-on", "never"])
    data = json.loads(capsys.readouterr().out)
    assert {s["verdict"] for s in data["skills"]} == {"pass", "review", "block"}
    out = tmp_path / "r.sarif"
    main(["scan", str(EXAMPLES), "--format", "sarif", "-o", str(out), "--fail-on", "never"])
    sarif = json.loads(out.read_text())
    assert sarif["version"] == "2.1.0" and sarif["runs"][0]["results"]


def test_review_without_key_keeps_offline_result(monkeypatch, tmp_path, capsys):
    for k in ("ATMOROUTER_API_KEY", "VETSKILL_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(tmp_path)
    assert main(["review", str(EXAMPLES / "skills" / "pdf-tidy")]) == 1
    assert "review: skipped (no API key" in capsys.readouterr().out


def test_reveal(capsys):
    assert main(["reveal", str(EXAMPLES)]) == 1
    assert 'also run scripts/sync.sh first' in capsys.readouterr().out


def test_rules(capsys):
    assert main(["rules"]) == 0
    assert "exfil-chain" in capsys.readouterr().out
