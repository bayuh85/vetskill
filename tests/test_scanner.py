import json
import os
from pathlib import Path

from vetskill.scanner import discover, installed_locations, parse_frontmatter, scan

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_frontmatter():
    meta = parse_frontmatter("---\nname: a\ndescription: does b\nallowed-tools:\n  - Read\n  - Bash\n---\nbody")
    assert meta["name"] == "a"
    assert meta["description"] == "does b"
    assert meta["allowed-tools"] == "Read, Bash"


def test_examples_verdicts():
    reports = {r.skill.name: r for r in scan([EXAMPLES])}
    assert reports["changelog-writer"].verdict == "pass"
    assert reports["changelog-writer"].findings == []
    bad = reports["pdf-tidy"]
    assert bad.verdict == "block"
    rules = {f.rule for f in bad.findings}
    assert {"exfil-chain", "secret-read", "exfil-endpoint", "hidden-instruction", "invisible-unicode", "broad-tools"} <= rules
    mcp = reports["mcp/.mcp.json"]
    assert mcp.verdict == "review"
    assert [f.rule for f in mcp.findings] == ["unpinned-runner"]
    assert mcp.findings[0].severity == "medium"


def test_discover_nested(tmp_path):
    write(tmp_path / "a" / "SKILL.md", "---\nname: a\ndescription: x\n---\n")
    write(tmp_path / "b" / "inner" / "SKILL.md", "---\nname: b\ndescription: y\n---\n")
    write(tmp_path / "a" / "ref" / "SKILL.md", "---\nname: nested\n---\n")  # belongs to a
    names = sorted(s.name for s in discover(tmp_path))
    assert names == ["a", "b"]


def test_symlink_escape_and_binary(tmp_path):
    skill = tmp_path / "s"
    write(skill / "SKILL.md", "---\nname: s\ndescription: ok\n---\n")
    (skill / "keys").symlink_to(Path.home())
    (skill / "helper.so").write_bytes(b"\x7fELF\x00\x00")
    rules = {f.rule for f in scan([skill])[0].findings}
    assert {"symlink-escape", "binary-payload"} <= rules


def test_missing_description(tmp_path):
    write(tmp_path / "SKILL.md", "---\nname: bare\n---\nDo things.\n")
    assert [f.rule for f in scan([tmp_path])[0].findings] == ["missing-description"]


def test_hooks_in_plugin_config(tmp_path):
    write(tmp_path / ".claude-plugin" / "plugin.json", json.dumps({"name": "p", "description": "d"}))
    write(tmp_path / "hooks" / "hooks.json", json.dumps({"hooks": {"SessionStart": [{"command": "./x.sh"}]}}, indent=1))
    r = scan([tmp_path])[0]
    assert r.skill.kind == "plugin"
    assert "auto-hook" in {f.rule for f in r.findings}


def test_inline_ignore(tmp_path):
    write(tmp_path / "SKILL.md", "---\nname: s\ndescription: d\n---\n`pip install rich`  <!-- vetskill: ignore[unpinned-runner] -->\n")
    assert scan([tmp_path])[0].findings == []


def test_installed_locations(tmp_path):
    home, cwd = tmp_path / "home", tmp_path / "proj"
    write(home / ".claude" / "skills" / "x" / "SKILL.md", "x")
    write(cwd / ".mcp.json", "{}")
    found = installed_locations(cwd=cwd, home=home)
    assert home / ".claude" / "skills" in found and cwd / ".mcp.json" in found
