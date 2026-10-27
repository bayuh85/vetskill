"""Line rules. Every rule is a plain regex plus a severity and a one-line fix.

Rules look at text the agent will read or run: SKILL.md, reference docs,
scripts, hook configs and MCP server entries. They are deliberately boring so a
finding can be explained in one sentence and reproduced with grep.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SEVERITY_WEIGHT = {"high": 25, "medium": 8, "low": 3}
SEVERITY_ORDER = {"low": 1, "medium": 2, "high": 3}


@dataclass(frozen=True)
class Rule:
    id: str
    severity: str
    category: str
    title: str
    fix: str
    pattern: re.Pattern[str] | None = None
    docs_only: bool = False  # only applies to markdown / text the model reads
    config_only: bool = False  # only applies to JSON / YAML / TOML config


def _rx(expr: str) -> re.Pattern[str]:
    return re.compile(expr, re.IGNORECASE)


INVISIBLE = re.compile(
    "[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\U000e0000-\U000e007f]"
)

RULES: list[Rule] = [
    Rule(
        "override-phrase", "high", "prompt-injection",
        "Text tries to override the agent's instructions or hide actions from the user",
        "Remove the instruction. A skill should never ask the agent to keep secrets from the user.",
        _rx(
            r"ignore (all |any )?(the )?(previous|prior|above|earlier|system) (instructions|rules|prompts?)"
            r"|disregard (all |any )?(the )?(previous|prior|above|earlier|system|user'?s?) (instructions|rules|prompts?)"
            r"|(do not|don'?t|never) (tell|mention|reveal|show|inform|notify|alert) (this|it|these|that|anything) to the user"
            r"|(do not|don'?t|never) (tell|inform|notify|alert|warn) the user (about|of) (this|these|it|the (upload|sync|request|step))"
            r"|without (asking|telling|informing|notifying) the user"
            r"|you are now (in )?(developer|dan|god|unrestricted|jailbreak)"
            r"|(keep|stay) (this|these steps|it) (secret|hidden|quiet)"
        ),
        docs_only=True,
    ),
    Rule(
        "hidden-instruction", "high", "prompt-injection",
        "HTML comment carries instructions the user will never see rendered",
        "Move real guidance into visible text or delete the comment.",
        _rx(
            r"<!--(?=[^>]*\b(ignore (the|all|previous|prior)|secretly|silently|quietly|do not tell|don'?t tell|without telling"
            r"|run (scripts?/|the script|this script|bash|sh |curl)|execute|send (the|all|your)|upload|curl|wget)\b)"
        ),
        docs_only=True,
    ),
    Rule(
        "invisible-unicode", "high", "prompt-injection",
        "Zero-width, bidi-override or Unicode tag characters hide text from reviewers",
        "Strip the characters. `vetskill reveal <path>` spells out what they hide.",
        INVISIBLE,
    ),
    Rule(
        "pipe-to-shell", "high", "remote-exec",
        "Downloads code and pipes it straight into an interpreter",
        "Pin a release, download it, verify a checksum, then run the local file.",
        _rx(
            r"\b(curl|wget|iwr|invoke-webrequest|irm|invoke-restmethod)\s+[^|\n]+\|\s*(sudo\s+)?"
            r"(ba|z|da|k)?sh\b|\b(curl|wget)\s+[^|\n]+\|\s*(sudo\s+)?(python3?|node|perl|ruby|iex)\b"
            r"|\b(ba)?sh\s+(-c\s+)?[\"']?\$\((curl|wget)\b|\b(irm|iwr)\b[^|\n]*\|\s*iex\b"
        ),
    ),
    Rule(
        "encoded-exec", "high", "obfuscation",
        "Decodes an encoded payload and executes it",
        "Ship the real source. Reviewers and scanners cannot read what they cannot decode.",
        _rx(
            r"base64\s+(-d|--decode|-D)\b[^\n]*\|\s*(ba|z)?sh\b"
            r"|\b(eval|exec)\s*\(\s*(base64\.b64decode|atob|buffer\.from|codecs\.decode|bytes\.fromhex|zlib\.decompress)"
            r"|\beval\s+[\"']?\$\(\s*echo\b[^\n]*base64"
            r"|powershell(\.exe)?\s+[^\n]*-e(nc|ncodedcommand)?\s+[a-z0-9+/=]{20,}"
            r"|\bexec\s*\(\s*compile\s*\("
        ),
    ),
    Rule(
        "secret-read", "high", "credentials",
        "Reads credential stores that a skill has no reason to touch",
        "Delete the access. If a token is truly required, ask the user to pass it explicitly.",
        _rx(
            r"~/\.ssh\b|\.ssh/(id_[a-z0-9]+|authorized_keys|known_hosts)|\bid_(rsa|ed25519|ecdsa)\b"
            r"|\.aws/credentials|\.config/gh/hosts\.ya?ml|\.docker/config\.json|\.netrc\b|\.npmrc\b|\.pypirc\b"
            r"|\.kube/config|\.git-credentials|security\s+find-(generic|internet)-password"
            r"|login data|\bcookies\.sqlite\b|/Cookies\b|\.claude/\.credentials|\.codex/auth\.json"
            r"|\bcat\s+[^\n|;]*\.env\b"
        ),
    ),
    Rule(
        "env-harvest", "medium", "credentials",
        "Collects the whole environment, which usually holds API keys",
        "Read only the specific variable the skill needs.",
        _rx(
            r"(dict|json\.dumps|str|repr)\s*\(\s*os\.environ\s*\)"
            r"|json\.stringify\s*\(\s*process\.env\s*\)|object\.(entries|keys)\s*\(\s*process\.env\s*\)"
            r"|(?<![\w.\\$])(printenv|env)\s*(\||>)|\bset\s*\|\s*(curl|nc)\b"
        ),
    ),
    Rule(
        "exfil-endpoint", "high", "exfiltration",
        "Talks to a request-capture, paste or tunnel service often used to exfiltrate data",
        "Remove the endpoint. Legitimate skills call the API they document, not a capture bin.",
        _rx(
            r"webhook\.site|requestbin|pipedream\.net|\.ngrok(-free)?\.(app|io|dev)|ngrok\.io"
            r"|discord(app)?\.com/api/webhooks|hooks\.slack\.com/services|pastebin\.com|transfer\.sh"
            r"|interact\.sh|oast\.(fun|live|pro|site|online|me)|burpcollaborator|trycloudflare\.com"
            r"|api\.telegram\.org/bot"
        ),
    ),
    Rule(
        "raw-ip-url", "medium", "exfiltration",
        "Hard-coded URL to a bare IP address",
        "Use a named, documented host or make the endpoint configurable.",
        re.compile(
            r"\b(https?|ftp)://(?!127\.|0\.0\.0\.0|10\.|192\.168\.|localhost)\d{1,3}(\.\d{1,3}){3}\b",
            re.IGNORECASE,
        ),
    ),
    Rule(
        "outbound-upload", "medium", "exfiltration",
        "Sends local data to a remote server",
        "Make the destination explicit in the description and ask before uploading.",
        _rx(
            r"\bcurl\b[^\n]*(\s-d\s*@|--data(-binary|-raw)?\s+@|-F\s+[\"']?\w+=@|--upload-file|-T\s+\S)"
            r"|\brequests\.(post|put)\s*\(|\bhttpx\.(post|put)\s*\(|\burllib\.request\.urlopen\s*\([^\n]*data="
            r"|\bfetch\s*\([^\n]*method\s*:\s*[\"'](post|put)[\"']|\bnc\s+(-\w+\s+)*\S+\s+\d+\s*<"
            r"|\bscp\s+\S+\s+\S+@\S+:"
        ),
    ),
    Rule(
        "persistence", "high", "persistence",
        "Modifies shell startup files, scheduled jobs or login items",
        "A skill should not install anything that outlives the session.",
        _rx(
            r"(>>?|tee\s+(-a\s+)?)\s*~?/?[^\s]*\.(bashrc|zshrc|bash_profile|profile|zprofile|config/fish/config\.fish)\b"
            r"|\bcrontab\s+(-l|-e|-)|/etc/cron|Library/LaunchAgents|systemctl\s+--user\s+(enable|start)"
            r"|>>?\s*~?/?\.ssh/authorized_keys|git\s+config\s+--global\s+core\.hookspath"
            r"|HKCU\\\\?Software\\\\?Microsoft\\\\?Windows\\\\?CurrentVersion\\\\?Run"
        ),
    ),
    Rule(
        "destructive", "high", "destructive",
        "Deletes or overwrites data outside the project",
        "Scope deletions to a path inside the working directory and confirm with the user.",
        _rx(
            r"\brm\s+-[a-z]*r[a-z]*f?[a-z]*\s+(--no-preserve-root\s+)?(/|~|\$home|\*|/\*)(\s|$|[\"'])"
            r"|\bmkfs(\.\w+)?\b|\bdd\s+[^\n]*of=/dev/(sd|nvme|disk)|\bgit\s+push\s+[^\n]*--force[^\n]*\b(main|master)\b"
            r"|shutil\.rmtree\s*\(\s*(os\.path\.expanduser\s*\(\s*)?[\"']~?/[\"']"
        ),
    ),
    Rule(
        "permission-bypass", "high", "permissions",
        "Turns off the agent's approval prompts or sandbox",
        "Remove the flag. Let the user decide what runs unattended.",
        _rx(
            r"--dangerously-skip-permissions|--dangerously-bypass-approvals-and-sandbox|\bbypasspermissions\b"
            r"|approval[_-]policy\s*[=:]\s*[\"']?never|--yolo\b|sandbox[_-]mode\s*[=:]\s*[\"']?danger-full-access"
        ),
    ),
    Rule(
        "unpinned-runner", "low", "supply-chain",
        "Runs a package straight from a registry without pinning a version",
        "Pin an exact version (pkg@1.2.3, pkg==1.2.3) so a future publish cannot change what runs.",
        None,  # token-based check in vetskill.scanner.unpinned_packages
    ),
    Rule(
        "auto-hook", "medium", "persistence",
        "Registers a hook that runs a command automatically on agent events",
        "List the hook in the description and keep the command local and readable.",
        config_only=True,
        pattern=_rx(r"[\"'](PreToolUse|PostToolUse|SessionStart|UserPromptSubmit|Stop|SubagentStop|Notification)[\"']\s*:"),
    ),
    Rule(
        "long-blob", "medium", "obfuscation",
        "Long encoded blob that a reviewer cannot read",
        "Ship the decoded file, or explain and checksum the blob.",
        re.compile(r"[A-Za-z0-9+/]{240,}={0,2}|\b(?:[0-9a-fA-F]{2}){150,}\b|(\\x[0-9a-fA-F]{2}){40,}"),
    ),
]

RULE_INDEX = {rule.id: rule for rule in RULES}

# Rules that are not line regexes but are emitted by the scanner.
EXTRA_RULES = {
    "broad-tools": Rule(
        "broad-tools", "medium", "permissions",
        "Skill frontmatter grants unrestricted shell access",
        "Narrow allowed-tools to the commands the skill actually runs, e.g. Bash(git log:*).",
    ),
    "exfil-chain": Rule(
        "exfil-chain", "high", "exfiltration",
        "The same skill reads secrets and sends data out",
        "This is the classic credential-stealer shape. Do not install until both sides are explained.",
    ),
    "binary-payload": Rule(
        "binary-payload", "medium", "supply-chain",
        "Ships a compiled or binary file that cannot be reviewed as text",
        "Build from source in the open, or document and checksum the binary.",
    ),
    "symlink-escape": Rule(
        "symlink-escape", "high", "supply-chain",
        "Symlink points outside the skill directory",
        "Replace the link with the real file. Links can expose or overwrite files elsewhere.",
    ),
    "missing-description": Rule(
        "missing-description", "low", "hygiene",
        "SKILL.md has no description, so nobody can check behavior against intent",
        "Add a one-line description of what the skill does and when it should run.",
    ),
}

ALL_RULES = {**RULE_INDEX, **EXTRA_RULES}


def show_invisible(text: str) -> str:
    """Make hidden characters visible. Runs of Unicode tag characters are
    decoded, because that is how ASCII gets smuggled past a human reader."""
    def tags(m: re.Match[str]) -> str:
        return '<hidden:"' + "".join(chr(ord(c) - 0xE0000) for c in m.group()) + '">'
    text = re.sub("[\U000e0020-\U000e007e]+", tags, text)
    return INVISIBLE.sub(lambda m: f"<U+{ord(m.group()):04X}>", text)
