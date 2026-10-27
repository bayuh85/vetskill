"""Find skills on disk and run the rules over them. No network, no model."""

from __future__ import annotations

import json
import os
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path

from vetskill.rules import ALL_RULES, INVISIBLE, show_invisible, RULES, SEVERITY_ORDER, SEVERITY_WEIGHT

TEXT_SUFFIXES = {
    ".md", ".mdx", ".txt", ".rst", ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd",
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".rb", ".pl", ".lua", ".go", ".rs",
    ".json", ".jsonc", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env", ".html", ".xml", "",
}
DOC_SUFFIXES = {".md", ".mdx", ".txt", ".rst", ".html"}
BINARY_SUFFIXES = {".exe", ".dll", ".so", ".dylib", ".bin", ".pyc", ".o", ".a", ".class", ".jar", ".wasm", ".node"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".pytest_cache"}
MCP_FILES = {".mcp.json", "mcp.json", ".claude.json", "claude_desktop_config.json", "mcp_servers.json"}
MAX_BYTES = 1_000_000
IGNORE_MARK = re.compile(r"vetskill:\s*ignore(?:\[([a-z0-9,\- ]+)\])?", re.IGNORECASE)

PINNED_NPM = re.compile(r"^(@[^/\s]+/)?[^@\s]+@\d+\.\d+\.\d+[^\s]*$")
PINNED_PY = re.compile(r"==\d")


@dataclass
class Finding:
    rule: str
    severity: str
    category: str
    title: str
    fix: str
    path: str
    line: int
    snippet: str

    def to_dict(self) -> dict[str, object]:
        return dict(self.__dict__)


@dataclass
class Skill:
    name: str
    root: Path
    kind: str  # skill | plugin | mcp | directory
    description: str = ""
    allowed_tools: str = ""
    files: list[Path] = field(default_factory=list)


@dataclass
class SkillReport:
    skill: Skill
    findings: list[Finding]

    @property
    def score(self) -> int:
        """Risk score 0-100. Higher is worse. Each rule counts at most twice."""
        seen: dict[str, int] = {}
        total = 0
        for f in self.findings:
            seen[f.rule] = seen.get(f.rule, 0) + 1
            if seen[f.rule] <= 2:
                total += SEVERITY_WEIGHT[f.severity]
        return min(100, total)

    @property
    def verdict(self) -> str:
        if any(f.severity == "high" for f in self.findings) or self.score >= 50:
            return "block"
        if self.score >= 8:
            return "review"
        return "pass"

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.skill.name,
            "kind": self.skill.kind,
            "root": str(self.skill.root),
            "description": self.skill.description,
            "allowed_tools": self.skill.allowed_tools,
            "files": len(self.skill.files),
            "score": self.score,
            "verdict": self.verdict,
            "findings": [f.to_dict() for f in self.findings],
        }


def parse_frontmatter(text: str) -> dict[str, str]:
    """Tiny YAML-ish reader for the SKILL.md header: top-level `key: value` pairs."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    out: dict[str, str] = {}
    key = None
    for raw in text[3:end].splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw[0] not in " \t-" and ":" in raw:
            key, value = raw.split(":", 1)
            key = key.strip().lower()
            out[key] = value.strip().strip("\"'")
        elif key and raw.strip():
            item = raw.strip().lstrip("-").strip().strip("\"'")
            out[key] = (out[key] + ", " + item).strip(", ") if out[key] not in ("", "|", ">") else item
    return out


def _walk(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            found.append(Path(dirpath) / name)
        for name in dirnames:
            p = Path(dirpath) / name
            if p.is_symlink():
                found.append(p)
    return found


def discover(target: Path) -> list[Skill]:
    """Split a path into skills. A directory with SKILL.md is one skill; a
    plugin (.claude-plugin/plugin.json) is one unit; MCP config files are units
    of their own; anything else is scanned as one directory."""
    target = target.expanduser()
    if not target.exists():
        return []
    if target.is_file():
        kind = "mcp" if target.name in MCP_FILES else "skill" if target.name == "SKILL.md" else "directory"
        root = target.parent if kind == "skill" else target
        return [_make_skill(root if kind == "skill" else target, kind)]
    if (target / "SKILL.md").is_file() or (target / ".claude-plugin" / "plugin.json").is_file():
        return [_make_skill(target, "plugin" if (target / ".claude-plugin").is_dir() else "skill")]
    skills: list[Skill] = []
    claimed: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(target):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        here = Path(dirpath)
        if any(here.is_relative_to(c) for c in claimed):
            continue
        if "SKILL.md" in filenames or (here / ".claude-plugin" / "plugin.json").is_file():
            skills.append(_make_skill(here, "plugin" if (here / ".claude-plugin").is_dir() else "skill"))
            claimed.append(here)
            continue
        for name in filenames:
            if name in MCP_FILES:
                skills.append(_make_skill(here / name, "mcp"))
    if not skills:
        skills.append(_make_skill(target, "directory"))
    return skills


def _make_skill(root: Path, kind: str) -> Skill:
    skill = Skill(name=root.name, root=root, kind=kind)
    if kind == "mcp":
        skill.name = f"{root.parent.name}/{root.name}"
        skill.files = [root]
        return skill
    skill.files = _walk(root)
    manifest = root / "SKILL.md"
    if manifest.is_file():
        meta = parse_frontmatter(manifest.read_text(encoding="utf-8", errors="replace"))
        skill.name = meta.get("name") or root.name
        skill.description = meta.get("description", "")
        skill.allowed_tools = meta.get("allowed-tools", "") or meta.get("allowed_tools", "")
    plugin = root / ".claude-plugin" / "plugin.json"
    if plugin.is_file():
        try:
            data = json.loads(plugin.read_text(encoding="utf-8"))
            skill.name = data.get("name") or skill.name
            skill.description = data.get("description") or skill.description
        except (ValueError, OSError):
            pass
    return skill


def _ignored(line: str, rule: str) -> bool:
    m = IGNORE_MARK.search(line)
    if not m:
        return False
    if not m.group(1):
        return True
    return rule in {r.strip() for r in m.group(1).split(",")}


def unpinned_packages(line: str) -> list[str]:
    """Return package specs launched from a registry without an exact version."""
    try:
        tokens = shlex.split(line, comments=False, posix=True)
    except ValueError:
        tokens = line.split()
    hits: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i].strip("`'\"(),;")
        nxt = tokens[i + 1 : i + 6]
        if tok in {"npx", "bunx", "pnpx"} or (tok in {"pnpm", "yarn"} and nxt[:1] == ["dlx"]):
            rest = [t.strip("`'\"(),;") for t in nxt if t not in ("dlx",)]
            pkg = next((t for t in rest if t and not t.startswith("-")), None)
            if pkg and not PINNED_NPM.match(pkg) and not pkg.startswith((".", "/")):
                hits.append(pkg)
        elif tok in {"uvx"} or (tok == "pipx" and nxt[:1] == ["run"]):
            rest = [t.strip("`'\"(),;") for t in nxt if t != "run"]
            pkg = next((t for t in rest if t and not t.startswith("-")), None)
            if pkg and not PINNED_PY.search(pkg) and "@" not in pkg:
                hits.append(pkg)
        elif tok in {"pip", "pip3"} and nxt[:1] == ["install"]:
            for t in tokens[i + 2 :]:
                t = t.strip("`'\"(),;")
                if t in {"&&", "|", ";"} or t.startswith(("|", "&")):
                    break
                if not t or t.startswith("-") or t.startswith((".", "/")) or t.endswith((".txt", ".whl")):
                    continue
                if not PINNED_PY.search(t):
                    hits.append(t)
        i += 1
    if "@latest" in line and not any("@latest" in h for h in hits):
        hits.append("@latest")
    return hits


def _finding(rule_id: str, path: Path, base: Path, line_no: int, snippet: str) -> Finding:
    rule = ALL_RULES[rule_id]
    try:
        rel = str(path.relative_to(base)) if base.is_dir() else path.name
    except ValueError:
        rel = str(path)
    clean = show_invisible(snippet.strip())
    if len(clean) > 160:
        clean = clean[:157] + "..."
    return Finding(rule.id, rule.severity, rule.category, rule.title, rule.fix, rel, line_no, clean)


CONFIG_SUFFIXES = {".json", ".jsonc", ".yaml", ".yml", ".toml"}
COMMENT_PREFIXES = ("#", "//", "/*", "*", "--", "REM ", ";")


def scan_lines(path: Path, base: Path, text: str, is_doc: bool) -> list[Finding]:
    """Run line rules. In scripts, comment lines only get the prompt-injection
    rules: a comment is read by the agent but never executed."""
    out: list[Finding] = []
    is_config = path.suffix.lower() in CONFIG_SUFFIXES or path.name in MCP_FILES
    for no, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        is_comment = not is_doc and stripped.startswith(COMMENT_PREFIXES) and not stripped.startswith("#!")
        for rule in RULES:
            if rule.docs_only and not is_doc:
                continue
            if rule.config_only and not is_config:
                continue
            if is_comment and rule.category != "prompt-injection":
                continue
            if rule.id == "unpinned-runner":
                if unpinned_packages(line) and not _ignored(line, rule.id):
                    out.append(_finding(rule.id, path, base, no, line))
                continue
            if rule.pattern is not None and rule.pattern.search(line) and not _ignored(line, rule.id):
                out.append(_finding(rule.id, path, base, no, line))
    return out


def scan_mcp_config(path: Path, base: Path, text: str) -> list[Finding]:
    """MCP configs keep command and args in separate JSON fields; join them
    into one command line so the shell rules can read it."""
    out = scan_lines(path, base, text, is_doc=False)
    try:
        data = json.loads(text)
    except ValueError:
        return out
    servers = data.get("mcpServers") or data.get("servers") or {}
    if not isinstance(servers, dict):
        return out
    lines = text.splitlines()
    for name, cfg in servers.items():
        if not isinstance(cfg, dict):
            continue
        cmd = " ".join([str(cfg.get("command", ""))] + [str(a) for a in cfg.get("args", []) or []])
        line_no = next((i for i, l in enumerate(lines, 1) if f'"{name}"' in l), 1)
        joined = scan_lines(path, base, cmd, is_doc=False)
        for f in joined:
            f.line = line_no
            if f.rule == "unpinned-runner":
                # MCP servers start on every session, so an unpinned package here
                # is re-resolved from the registry again and again.
                f.severity = "medium"
            if not any(o.rule == f.rule and o.line == f.line for o in out):
                out.append(f)
        url = str(cfg.get("url", ""))
        if url:
            for f in scan_lines(path, base, url, is_doc=False):
                f.line = line_no
                out.append(f)
    return out


def scan_skill(skill: Skill) -> SkillReport:
    findings: list[Finding] = []
    base = skill.root if skill.root.is_dir() else skill.root.parent
    root_real = skill.root.resolve() if skill.root.is_dir() else skill.root.parent.resolve()
    for path in skill.files:
        if path.is_symlink():
            target = path.resolve()
            if not target.is_relative_to(root_real):
                findings.append(_finding("symlink-escape", path, base, 0, f"-> {os.readlink(path)}"))
            continue
        suffix = path.suffix.lower()
        if suffix in BINARY_SUFFIXES:
            findings.append(_finding("binary-payload", path, base, 0, path.name))
            continue
        if suffix not in TEXT_SUFFIXES and path.name not in MCP_FILES:
            continue
        try:
            raw = path.read_bytes()[:MAX_BYTES]
        except OSError:
            continue
        if b"\x00" in raw[:4096]:
            findings.append(_finding("binary-payload", path, base, 0, path.name))
            continue
        text = raw.decode("utf-8", errors="replace")
        if path.name in MCP_FILES:
            findings.extend(scan_mcp_config(path, base, text))
        else:
            findings.extend(scan_lines(path, base, text, is_doc=suffix in DOC_SUFFIXES or path.name == "SKILL.md"))

    tools = skill.allowed_tools.replace(" ", "")
    if tools and re.search(r"(^|,)(Bash|Bash\(\*\)|Bash\(\*:\*\)|\*)(,|$)", tools):
        findings.append(_finding("broad-tools", base / "SKILL.md", base, 1, f"allowed-tools: {skill.allowed_tools}"))
    if skill.kind == "skill" and not skill.description.strip():
        findings.append(_finding("missing-description", base / "SKILL.md", base, 1, "description: (empty)"))

    reads = [f for f in findings if f.rule in {"secret-read", "env-harvest"}]
    sends = [f for f in findings if f.rule in {"exfil-endpoint", "outbound-upload", "raw-ip-url"}]
    if reads and sends:
        r, s = reads[0], sends[0]
        findings.append(
            Finding("exfil-chain", "high", "exfiltration", ALL_RULES["exfil-chain"].title,
                    ALL_RULES["exfil-chain"].fix, r.path, r.line,
                    f"reads at {r.path}:{r.line}, sends at {s.path}:{s.line}")
        )
    findings.sort(key=lambda f: (-SEVERITY_ORDER[f.severity], f.path, f.line, f.rule))
    return SkillReport(skill, findings)


def scan(targets: list[Path]) -> list[SkillReport]:
    reports: list[SkillReport] = []
    for t in targets:
        for skill in discover(t):
            reports.append(scan_skill(skill))
    return reports


def installed_locations(cwd: Path | None = None, home: Path | None = None) -> list[Path]:
    """Places where Claude Code, Codex, Cursor and friends load skills from."""
    cwd = cwd or Path.cwd()
    home = home or Path.home()
    candidates = [
        home / ".claude" / "skills", home / ".claude" / "plugins", home / ".codex" / "skills",
        home / ".cursor" / "skills", home / ".agents" / "skills", home / ".claude.json",
        home / ".cursor" / "mcp.json",
        cwd / ".claude" / "skills", cwd / ".cursor" / "skills", cwd / ".agents" / "skills",
        cwd / ".codex" / "skills", cwd / ".mcp.json", cwd / ".cursor" / "mcp.json",
    ]
    return [c for c in candidates if c.exists()]
