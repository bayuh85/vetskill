"""Render scan results as text, JSON, Markdown or SARIF."""

from __future__ import annotations

import json
from typing import Any

from vetskill import __version__
from vetskill.rules import ALL_RULES
from vetskill.scanner import SkillReport

BADGE = {"pass": "PASS", "review": "REVIEW", "block": "BLOCK"}


def text(reports: list[SkillReport], reviews: dict[int, Any] | None = None) -> str:
    out: list[str] = []
    reviews = reviews or {}
    for i, r in enumerate(reports):
        out.append(f"{BADGE[r.verdict]:<6}  {r.skill.name}  ({r.skill.kind}, {len(r.skill.files)} files, risk {r.score}/100)")
        if r.skill.description:
            out.append(f"        {r.skill.description[:110]}")
        for f in r.findings:
            out.append(f"  {f.severity:<6} {f.rule:<18} {f.path}:{f.line}")
            out.append(f"         {f.snippet}")
            out.append(f"         fix: {f.fix}")
        rv = reviews.get(i)
        if rv is not None:
            if isinstance(rv, str):
                out.append(f"  review: skipped ({rv})")
            else:
                out.append(f"  review ({rv.model}, {rv.tokens_in}+{rv.tokens_out} tokens): {rv.verdict}"
                           f"{'' if rv.purpose_match is None else ', purpose match: ' + ('yes' if rv.purpose_match else 'no')}")
                if rv.summary:
                    out.append(f"         {rv.summary}")
                for c in rv.concerns[:8]:
                    out.append(f"         - {c.get('where', '?')}: {c.get('assessment', '?')}, {c.get('why', '')}")
                out.append(f"  final verdict: {BADGE[rv.final_verdict]}")
        out.append("")
    blocked = sum(1 for r in reports if r.verdict == "block")
    flagged = sum(1 for r in reports if r.verdict == "review")
    out.append(f"{len(reports)} skill(s) scanned: {blocked} block, {flagged} review, {len(reports) - blocked - flagged} pass")
    return "\n".join(out)


def as_json(reports: list[SkillReport], reviews: dict[int, Any] | None = None) -> str:
    items = []
    for i, r in enumerate(reports):
        d = r.to_dict()
        rv = (reviews or {}).get(i)
        if rv is not None:
            d["review"] = rv if isinstance(rv, str) else rv.to_dict()
        items.append(d)
    return json.dumps({"tool": "vetskill", "version": __version__, "skills": items}, indent=2)


def markdown(reports: list[SkillReport], reviews: dict[int, Any] | None = None) -> str:
    out = ["# vetskill report", "", "| Skill | Kind | Risk | Verdict | Findings |", "| --- | --- | --- | --- | --- |"]
    for r in reports:
        out.append(f"| {r.skill.name} | {r.skill.kind} | {r.score} | {BADGE[r.verdict]} | {len(r.findings)} |")
    for i, r in enumerate(reports):
        if not r.findings:
            continue
        out += ["", f"## {r.skill.name}", ""]
        for f in r.findings:
            out.append(f"- **{f.severity}** `{f.rule}` `{f.path}:{f.line}`: {f.title}. {f.fix}")
        rv = (reviews or {}).get(i)
        if rv is not None and not isinstance(rv, str):
            out += ["", f"Model review ({rv.model}): **{rv.verdict}**. {rv.summary}"]
    return "\n".join(out) + "\n"


def sarif(reports: list[SkillReport]) -> str:
    level = {"high": "error", "medium": "warning", "low": "note"}
    used = sorted({f.rule for r in reports for f in r.findings})
    results = []
    for r in reports:
        base = str(r.skill.root)
        for f in r.findings:
            results.append({
                "ruleId": f.rule,
                "level": level[f.severity],
                "message": {"text": f"{f.title}. {f.fix}"},
                "locations": [{"physicalLocation": {
                    "artifactLocation": {"uri": f"{base}/{f.path}" if r.skill.root.is_dir() else base},
                    "region": {"startLine": max(1, f.line)},
                }}],
            })
    doc = {
        "version": "2.1.0",
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "runs": [{
            "tool": {"driver": {"name": "vetskill", "version": __version__, "rules": [
                {"id": rid, "shortDescription": {"text": ALL_RULES[rid].title},
                 "help": {"text": ALL_RULES[rid].fix}} for rid in used
            ]}},
            "results": results,
        }],
    }
    return json.dumps(doc, indent=2)
