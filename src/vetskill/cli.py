"""Command line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from vetskill import __version__, report
from vetskill.config import load_settings
from vetskill.llm import LLMError
from vetskill.rules import ALL_RULES, INVISIBLE, SEVERITY_ORDER, show_invisible
from vetskill.scanner import installed_locations, scan

FAIL_LEVELS = {"high": 3, "medium": 2, "low": 1, "never": 99}


def _exit_code(reports: list, fail_on: str, reviews: dict[int, Any]) -> int:
    threshold = FAIL_LEVELS[fail_on]
    for i, r in enumerate(reports):
        if any(SEVERITY_ORDER[f.severity] >= threshold for f in r.findings):
            return 1
        rv = reviews.get(i)
        if rv is not None and not isinstance(rv, str) and rv.final_verdict == "block" and threshold < 99:
            return 1
    return 0


def _emit(args: argparse.Namespace, reports: list, reviews: dict[int, Any]) -> None:
    fmt = args.format
    if fmt == "json":
        body = report.as_json(reports, reviews)
    elif fmt == "markdown":
        body = report.markdown(reports, reviews)
    elif fmt == "sarif":
        body = report.sarif(reports)
    else:
        body = report.text(reports, reviews)
    if args.output:
        Path(args.output).write_text(body + ("" if body.endswith("\n") else "\n"), encoding="utf-8")
        print(f"wrote {args.output}", file=sys.stderr)
    else:
        print(body)


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--format", "-f", choices=["text", "json", "markdown", "sarif"], default="text")
    p.add_argument("--output", "-o", help="write the report to a file")
    p.add_argument("--fail-on", choices=list(FAIL_LEVELS), default="high",
                   help="exit 1 when a finding at this severity or above is present (default: high)")


def cmd_scan(args: argparse.Namespace) -> int:
    targets = [Path(p) for p in args.paths]
    missing = [str(t) for t in targets if not t.expanduser().exists()]
    if missing:
        print(f"vetskill: no such path: {', '.join(missing)}", file=sys.stderr)
        return 2
    reports = scan(targets)
    _emit(args, reports, {})
    return _exit_code(reports, args.fail_on, {})


def cmd_installed(args: argparse.Namespace) -> int:
    locs = installed_locations()
    if not locs:
        print("vetskill: no skill folders or MCP configs found in the usual places", file=sys.stderr)
        return 0
    print("scanning: " + ", ".join(str(l) for l in locs), file=sys.stderr)
    reports = scan(locs)
    _emit(args, reports, {})
    return _exit_code(reports, args.fail_on, {})


def cmd_review(args: argparse.Namespace) -> int:
    from vetskill.review import review

    targets = [Path(p) for p in args.paths]
    reports = scan(targets)
    settings = load_settings()
    if args.model:
        settings = settings.__class__(**{**settings.__dict__, "model": args.model})
    reviews: dict[int, Any] = {}
    for i, r in enumerate(reports):
        if not r.findings and not args.all:
            reviews[i] = "no offline findings; pass --all to review anyway"
            continue
        try:
            reviews[i] = review(r, settings)
        except LLMError as exc:
            reviews[i] = str(exc)
            print(f"vetskill: review failed for {r.skill.name}: {exc}", file=sys.stderr)
    _emit(args, reports, reviews)
    return _exit_code(reports, args.fail_on, reviews)


def cmd_rules(args: argparse.Namespace) -> int:
    for rule in sorted(ALL_RULES.values(), key=lambda r: (-SEVERITY_ORDER[r.severity], r.id)):
        print(f"{rule.severity:<6} {rule.id:<20} {rule.category:<17} {rule.title}")
    return 0


def cmd_reveal(args: argparse.Namespace) -> int:
    """Print every line that contains invisible characters, with them spelled out."""
    hits = 0
    for raw in args.paths:
        p = Path(raw)
        files = [p] if p.is_file() else [f for f in p.rglob("*") if f.is_file()]
        for f in files:
            try:
                lines = f.read_text(encoding="utf-8").splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            for no, line in enumerate(lines, 1):
                if INVISIBLE.search(line):
                    hits += 1
                    print(f"{f}:{no}: {show_invisible(line)[:300]}")
    if not hits:
        print("no invisible characters found")
    return 1 if hits else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vetskill", description="Vet agent skills, plugins and MCP configs before your agent runs them.")
    p.add_argument("--version", action="version", version=f"vetskill {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("scan", help="offline scan of skill folders, plugins or MCP configs")
    s.add_argument("paths", nargs="+")
    _common(s)
    s.set_defaults(func=cmd_scan)

    s = sub.add_parser("installed", help="scan the skills and MCP configs your agents already load")
    _common(s)
    s.set_defaults(func=cmd_installed)

    s = sub.add_parser("review", help="offline scan, then ask a model whether flagged behavior matches the stated purpose")
    s.add_argument("paths", nargs="+")
    s.add_argument("--model", help="model id (default: VETSKILL_MODEL or cb/glm-5.3-flash)")
    s.add_argument("--all", action="store_true", help="also review skills with no offline findings")
    _common(s)
    s.set_defaults(func=cmd_review)

    s = sub.add_parser("rules", help="list the rules")
    s.set_defaults(func=cmd_rules)

    s = sub.add_parser("reveal", help="spell out zero-width, bidi and tag characters")
    s.add_argument("paths", nargs="+")
    s.set_defaults(func=cmd_reveal)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))
