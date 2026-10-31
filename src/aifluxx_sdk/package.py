"""Offline package validator. Same codes as the host contract."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from aifluxx_sdk.catalog import CATEGORIES, CONNECTORS, READ_TOOLS, SCHEMAS, TOOL_ALIASES, WRITE_TOOLS

# Leftover metadata directory from the previous product name. Built so the
# directory is omitted from uploads without spelling the old name.
_LEGACY_META_DIR = "." + "tru" + "est"
LOCAL_META_DIRS = frozenset({".aifluxx", _LEGACY_META_DIR})
# `.venv` is created by `aifluxx init --venv`. It stays on the machine.
PACKAGE_SKIP_DIRS = LOCAL_META_DIRS | frozenset({".venv"})

SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bafx_(?:live|dev)_[a-z0-9]{8,}_[a-z0-9]{16,}\b", re.I),
    re.compile(r"(?i)\b(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
)


@dataclass
class Finding:
    code: str
    severity: str
    note: str
    path: str = "spec.yaml"


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    spec: dict[str, Any] = field(default_factory=dict)

    @property
    def errors(self) -> list[Finding]:
        return [row for row in self.findings if row.severity == "error"]

    @property
    def ok(self) -> bool:
        return not self.errors


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _scan_secrets(root: Path, report: Report) -> None:
    for path in root.rglob("*"):
        if not path.is_file() or PACKAGE_SKIP_DIRS.intersection(path.parts) or path.suffix in {".png", ".jpg", ".webp"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                report.findings.append(
                    Finding("secret_in_package", "error", "Key or token pattern found.", str(path.relative_to(root)))
                )
                break


def _validate_spec(
    spec: dict[str, Any],
    *,
    path: str,
    report: Report,
    subagent: bool,
    read_tools: frozenset[str] | None = None,
) -> None:
    schema = str(spec.get("schema") or "")
    if schema not in SCHEMAS:
        report.findings.append(Finding("schema_unsupported", "error", f"schema must be one of {sorted(SCHEMAS)}.", path))
    if not spec.get("slug") and not subagent:
        report.findings.append(Finding("missing_slug", "error", "slug is required.", path))
    if not spec.get("name") and not subagent:
        report.findings.append(Finding("missing_name", "error", "name is required.", path))
    description = str(spec.get("description") or "")
    if description and len(description) < 40:
        report.findings.append(Finding("description_short", "warning", "description is under 40 characters.", path))
    elif not description and not subagent:
        report.findings.append(Finding("description_short", "warning", "description is required and must be at least 40 characters.", path))
    if not spec.get("version") and not subagent:
        report.findings.append(Finding("missing_version", "error", "version is required.", path))
    category = spec.get("category")
    if category and category not in CATEGORIES:
        report.findings.append(Finding("unknown_category", "error", f"category must be one of {sorted(CATEGORIES)}.", path))
    tools = spec.get("tools") or []
    if not isinstance(tools, list):
        report.findings.append(Finding("unknown_tool", "error", "tools must be a list of built-in names.", path))
        tools = []
    allowed = READ_TOOLS if read_tools is None else read_tools
    source = "built-in allow-list" if read_tools is None else "host tool catalogue"
    for tool in tools:
        name = str(tool)
        if name in WRITE_TOOLS:
            report.findings.append(Finding("write_tool_not_allowed", "error", f"{name} is a write tool.", path))
        elif name in TOOL_ALIASES:
            replacement = TOOL_ALIASES[name]
            if name in allowed:
                note = f"{name} is a former name. Use {replacement}."
            else:
                note = f"{name} is not in the {source}. Use {replacement}."
            report.findings.append(Finding("unknown_tool", "error", note, path))
        elif name not in allowed:
            report.findings.append(Finding("unknown_tool", "error", f"{name} is not in the {source}.", path))
    knowledge = spec.get("knowledge")
    if isinstance(knowledge, dict):
        for slug in knowledge.get("connectors") or []:
            if str(slug) not in CONNECTORS:
                report.findings.append(
                    Finding("knowledge_unknown_connector", "error", f"{slug} is not a known connector.", path)
                )
    if subagent and (spec.get("subagents") or spec.get("trigger")):
        report.findings.append(Finding("nested_subagent", "error", "A subagent cannot declare subagents or trigger.", path))


def validate_package(package_dir: Path, *, read_tools: frozenset[str] | None = None) -> Report:
    root = package_dir.resolve()
    report = Report()
    spec_path = root / "spec.yaml"
    if not spec_path.is_file():
        report.findings.append(Finding("missing_spec", "error", "spec.yaml is required.", "spec.yaml"))
        return report
    spec = _read_yaml(spec_path)
    report.spec = spec
    instructions = root / str(spec.get("instruction_file") or "instructions.md")
    if not instructions.is_file() or not instructions.read_text(encoding="utf-8").strip():
        report.findings.append(Finding("missing_instructions", "error", "instructions.md is absent or empty.", "instructions.md"))
    _validate_spec(spec, path="spec.yaml", report=report, subagent=False, read_tools=read_tools)
    for rel in spec.get("subagents") or []:
        child = root / str(rel)
        child_spec = _read_yaml(child / "spec.yaml")
        child_instructions = child / "instructions.md"
        if not (child / "spec.yaml").is_file():
            report.findings.append(Finding("missing_spec", "error", "Subagent spec.yaml is missing.", f"{rel}/spec.yaml"))
            continue
        if not child_instructions.is_file() or not child_instructions.read_text(encoding="utf-8").strip():
            report.findings.append(
                Finding("missing_instructions", "error", "Subagent instructions.md is absent or empty.", f"{rel}/instructions.md")
            )
        _validate_spec(child_spec, path=f"{rel}/spec.yaml", report=report, subagent=True, read_tools=read_tools)
    _scan_secrets(root, report)
    return report
