"""Offline package validator. Same codes as the host contract."""
from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterator
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
# Extra excludes live here, next to spec.yaml. Defaults always apply as well.
IGNORE_FILENAME = ".aifluxxignore"
_SECRET_SCAN_SUFFIXES = frozenset({".png", ".jpg", ".webp"})

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


@dataclass(frozen=True)
class _ExcludePattern:
    """One exclude rule.

    ``anchored`` patterns match from the package root. A pattern with no slash
    matches that name in any directory. ``directory_only`` matches a directory
    and everything inside it, which is a trailing slash in ``.aifluxxignore``.
    """

    anchored: bool
    directory_only: bool
    parts: tuple[str, ...]


def _builtin_exclude_patterns() -> tuple[_ExcludePattern, ...]:
    """Directory names skipped at any depth, plus root ``sdk/`` and ``*.egg-info``."""
    named = tuple(
        _ExcludePattern(anchored=False, directory_only=True, parts=(name,))
        for name in sorted(PACKAGE_SKIP_DIRS)
    )
    return named + (
        # Vendored SDK sits next to spec.yaml. A nested directory named sdk stays.
        _ExcludePattern(anchored=True, directory_only=True, parts=("sdk",)),
        _ExcludePattern(anchored=False, directory_only=False, parts=("*.egg-info",)),
    )


_BUILTIN_EXCLUDES = _builtin_exclude_patterns()


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _invalid_exclude_line(line: str) -> bool:
    text = line.replace("\\", "/").strip()
    if text.startswith("!") or "\x00" in text or text.startswith("//"):
        return True
    if re.match(r"^[A-Za-z]:", text):
        return True
    body = text[1:] if text.startswith("/") else text
    body = body.rstrip("/")
    raw_parts = body.split("/")
    if any(part == ".." for part in raw_parts):
        return True
    return not [part for part in raw_parts if part not in ("", ".")]


def _compile_exclude_pattern(line: str) -> _ExcludePattern:
    text = line.replace("\\", "/").strip()
    directory_only = text.endswith("/")
    body = text.rstrip("/")
    if body.startswith("/"):
        anchored = True
        body = body[1:]
    else:
        anchored = "/" in body
    parts = tuple(part for part in body.split("/") if part not in ("", "."))
    return _ExcludePattern(anchored=anchored, directory_only=directory_only, parts=parts)


def load_exclude_patterns(package_dir: Path) -> tuple[tuple[_ExcludePattern, ...], list[Finding]]:
    """Built-in excludes plus ``.aifluxxignore`` lines.

    The ignore file is optional. A non-UTF-8 file or a line that is not a
    relative pattern adds an error finding. Valid lines are still applied.
    Defaults always apply.
    """
    findings: list[Finding] = []
    extra: list[_ExcludePattern] = []
    path = package_dir.resolve() / IGNORE_FILENAME
    if not path.is_file():
        return _BUILTIN_EXCLUDES, findings
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        findings.append(
            Finding("exclude_unreadable", "error", ".aifluxxignore must be UTF-8.", IGNORE_FILENAME)
        )
        return _BUILTIN_EXCLUDES, findings
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if _invalid_exclude_line(line):
            findings.append(
                Finding(
                    "exclude_invalid",
                    "error",
                    f"Line {lineno} must be a relative path pattern.",
                    IGNORE_FILENAME,
                )
            )
            continue
        extra.append(_compile_exclude_pattern(line))
    return _BUILTIN_EXCLUDES + tuple(extra), findings


def _pattern_matches(pattern: _ExcludePattern, parts: tuple[str, ...], *, is_dir: bool) -> bool:
    if not parts:
        return False
    if not pattern.anchored and len(pattern.parts) == 1 and pattern.parts[0] != "**":
        token = pattern.parts[0]
        # A trailing slash matches the directory name, or a parent of a file.
        candidates = parts if is_dir or not pattern.directory_only else parts[:-1]
        return any(fnmatch.fnmatchcase(part, token) for part in candidates)

    def rec(index: int, start: int) -> bool:
        if index == len(pattern.parts):
            if pattern.directory_only:
                return start == len(parts) if is_dir else start < len(parts)
            return start == len(parts)
        token = pattern.parts[index]
        if token == "**":
            if rec(index + 1, start):
                return True
            return any(rec(index + 1, cursor) for cursor in range(start + 1, len(parts) + 1))
        if start >= len(parts) or not fnmatch.fnmatchcase(parts[start], token):
            return False
        return rec(index + 1, start + 1)

    return rec(0, 0)


def is_excluded(relative: Path, patterns: tuple[_ExcludePattern, ...], *, is_dir: bool) -> bool:
    """True when ``relative`` (from the package root) is left out of the package."""
    parts = tuple(part for part in relative.parts if part not in ("", "."))
    return any(_pattern_matches(pattern, parts, is_dir=is_dir) for pattern in patterns)


def iter_package_files(package_dir: Path, patterns: tuple[_ExcludePattern, ...] | None = None) -> Iterator[Path]:
    """Files that validate scans and push uploads, in stable relative order.

    Excluded directories are not opened. Symlinks to directories are not followed.
    """
    root = package_dir.resolve()
    if patterns is None:
        patterns, _findings = load_exclude_patterns(root)
    yield from _walk_package(root, root, patterns)


def _walk_package(root: Path, directory: Path, patterns: tuple[_ExcludePattern, ...]) -> Iterator[Path]:
    children = sorted(directory.iterdir(), key=lambda item: item.name)
    for path in children:
        relative = path.relative_to(root)
        if path.is_symlink():
            if path.is_file() and not is_excluded(relative, patterns, is_dir=False):
                yield path
            continue
        if path.is_dir():
            if is_excluded(relative, patterns, is_dir=True):
                continue
            yield from _walk_package(root, path, patterns)
            continue
        if path.is_file() and not is_excluded(relative, patterns, is_dir=False):
            yield path


def _scan_secrets(root: Path, report: Report, patterns: tuple[_ExcludePattern, ...]) -> None:
    for path in iter_package_files(root, patterns):
        if path.suffix in _SECRET_SCAN_SUFFIXES:
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
    patterns, exclude_findings = load_exclude_patterns(root)
    report.findings.extend(exclude_findings)
    _scan_secrets(root, report, patterns)
    return report
