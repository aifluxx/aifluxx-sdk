"""Starter UI layout file.

The file is canonical JSON: stable key order, a 12-column pack, and a trailing
newline. The Starter UI writes the same bytes. Chat sends the diff to the
companion and, after a yes, writes wiring inside the project folder only.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from aifluxx_sdk.exceptions import AifluxxError

LAYOUT_SCHEMA = "aifluxx/layout/v1"
WIRING_SCHEMA = "aifluxx/wiring/v1"
LAYOUT_FILENAME = "aifluxx.layout.json"
WIRING_FILENAME = "aifluxx.wiring.json"
GRID_COLUMNS = 12
MIN_W, MAX_W = 1, 12
MIN_H, MAX_H = 1, 8

# Screen order is part of the file format. Do not sort it.
SCREENS: tuple[str, ...] = ("Run", "Status", "Tools", "Settings")

SCREEN_COMPONENTS: dict[str, tuple[str, ...]] = {
    "Run": ("agent-picker", "prompt", "run-action", "output", "history"),
    "Status": ("refresh", "agents", "logs"),
    "Tools": ("read-tools", "write-tools", "connectors"),
    "Settings": ("connection", "keys", "mcp"),
}

# (w, h) on a fresh layout. Width 12 stacks every block on its own rows.
DEFAULT_SIZE: dict[str, tuple[int, int]] = {
    "agent-picker": (12, 2),
    "prompt": (12, 3),
    "run-action": (12, 1),
    "output": (12, 6),
    "history": (12, 4),
    "refresh": (12, 1),
    "agents": (12, 5),
    "logs": (12, 6),
    "read-tools": (12, 3),
    "write-tools": (12, 3),
    "connectors": (12, 3),
    "connection": (12, 4),
    "keys": (12, 5),
    "mcp": (12, 4),
}

# Where a block reads or writes. The wiring file mirrors the packed layout.
WIRING_TARGETS: dict[str, str] = {
    "agent-picker": "agent.version",
    "prompt": "agent.run",
    "run-action": "agent.run",
    "output": "agent.stream",
    "history": "agent.runs",
    "refresh": "agent.status",
    "agents": "agent.list",
    "logs": "agent.logs",
    "read-tools": "spec.tools.read",
    "write-tools": "spec.tools.write",
    "connectors": "spec.knowledge.connectors",
    "connection": "dev.session",
    "keys": "dev.keys",
    "mcp": "dev.mcp",
}

# Companion file edits may only land on these paths, plus anything under ui/.
_ALLOWED_FILES = frozenset({
    LAYOUT_FILENAME,
    WIRING_FILENAME,
    "instructions.md",
    "spec.yaml",
})

_FILES_FENCE = re.compile(r"```aifluxx-files\n(.*?)```", re.DOTALL)


def default_layout() -> dict[str, Any]:
    """Packed layout in screen and component order."""
    screens: dict[str, list[dict[str, Any]]] = {}
    for screen in SCREENS:
        rows = []
        for component_id in SCREEN_COMPONENTS[screen]:
            width, height = DEFAULT_SIZE[component_id]
            rows.append({"id": component_id, "w": width, "h": height})
        screens[screen] = rows
    return canonicalize({"schema": LAYOUT_SCHEMA, "screens": screens})


def canonicalize(layout: dict[str, Any] | None) -> dict[str, Any]:
    """Return a complete layout: known ids, clamped sizes, packed coordinates."""
    incoming = layout.get("screens") if isinstance(layout, dict) else None
    if incoming is not None and not isinstance(incoming, dict):
        raise AifluxxError("Layout screens must be an object.")
    screens: dict[str, list[dict[str, Any]]] = {}
    for screen in SCREENS:
        raw_rows = incoming.get(screen) if isinstance(incoming, dict) else None
        screens[screen] = _pack(_normalize_rows(screen, raw_rows))
    return {"schema": LAYOUT_SCHEMA, "screens": screens}


def serialize_layout(layout: dict[str, Any] | None) -> str:
    """Canonical layout JSON, including the trailing newline."""
    canon = canonicalize(layout)
    payload = {
        "schema": LAYOUT_SCHEMA,
        "screens": {name: [_box(item) for item in canon["screens"][name]] for name in SCREENS},
    }
    return json.dumps(payload, indent=2) + "\n"


def load_layout_text(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AifluxxError("Layout file is not valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise AifluxxError("Layout file must be a JSON object.")
    return canonicalize(parsed)


def layout_changes(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    """Stable diff: reorder, then move, then resize, screens in file order."""
    old = canonicalize(before)
    new = canonicalize(after)
    changes: list[dict[str, Any]] = []
    for screen in SCREENS:
        old_rows = old["screens"][screen]
        new_rows = new["screens"][screen]
        old_order = [item["id"] for item in old_rows]
        new_order = [item["id"] for item in new_rows]
        if old_order != new_order:
            changes.append({"screen": screen, "change": "reordered", "from": old_order, "to": new_order})
        old_by_id = {item["id"]: item for item in old_rows}
        for item in new_rows:
            prev = old_by_id[item["id"]]
            if (prev["col"], prev["row"]) != (item["col"], item["row"]):
                changes.append(
                    {
                        "screen": screen,
                        "id": item["id"],
                        "change": "moved",
                        "from": {"col": prev["col"], "row": prev["row"]},
                        "to": {"col": item["col"], "row": item["row"]},
                    }
                )
            if (prev["w"], prev["h"]) != (item["w"], item["h"]):
                changes.append(
                    {
                        "screen": screen,
                        "id": item["id"],
                        "change": "resized",
                        "from": {"w": prev["w"], "h": prev["h"]},
                        "to": {"w": item["w"], "h": item["h"]},
                    }
                )
    return changes


def format_changes(changes: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for change in changes:
        kind = change["change"]
        if kind == "reordered":
            lines.append(f"{change['screen']}: order {' '.join(change['from'])} -> {' '.join(change['to'])}")
        elif kind == "moved":
            src, dst = change["from"], change["to"]
            lines.append(
                f"{change['screen']}/{change['id']}: moved ({src['col']},{src['row']}) -> ({dst['col']},{dst['row']})"
            )
        else:
            src, dst = change["from"], change["to"]
            lines.append(
                f"{change['screen']}/{change['id']}: resized {src['w']}x{src['h']} -> {dst['w']}x{dst['h']}"
            )
    return "\n".join(lines)


def wiring_from_layout(layout: dict[str, Any]) -> dict[str, Any]:
    """Wiring document in the same order and geometry as the packed layout."""
    canon = canonicalize(layout)
    screens: dict[str, list[dict[str, Any]]] = {}
    for screen in SCREENS:
        screens[screen] = [
            {
                "id": item["id"],
                "target": WIRING_TARGETS[item["id"]],
                "col": item["col"],
                "row": item["row"],
                "w": item["w"],
                "h": item["h"],
            }
            for item in canon["screens"][screen]
        ]
    return {"schema": WIRING_SCHEMA, "screens": screens}


def serialize_wiring(layout: dict[str, Any]) -> str:
    document = wiring_from_layout(layout)
    payload = {
        "schema": WIRING_SCHEMA,
        "screens": {
            name: [
                {
                    "id": item["id"],
                    "target": item["target"],
                    "col": item["col"],
                    "row": item["row"],
                    "w": item["w"],
                    "h": item["h"],
                }
                for item in document["screens"][name]
            ]
            for name in SCREENS
        },
    }
    return json.dumps(payload, indent=2) + "\n"


def files_from_reply(reply: str) -> list[tuple[str, str]]:
    """File edits fenced in a companion reply. Empty when the fence is absent or broken."""
    match = _FILES_FENCE.search(reply or "")
    if match is None:
        return []
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    rows = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    found: list[tuple[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        path = row.get("path")
        content = row.get("content")
        if isinstance(path, str) and isinstance(content, str):
            found.append((path, content))
    return found


def proposed_writes(layout: dict[str, Any], reply: str) -> tuple[list[tuple[str, str]], list[str]]:
    """Deterministic wiring, plus allow-listed companion files.

    The wiring file always comes from the layout. A companion copy of that
    path is ignored. Unsafe paths are returned as skip notes, not writes.
    """
    writes: list[tuple[str, str]] = [(WIRING_FILENAME, serialize_wiring(layout))]
    skipped: list[str] = []
    for relative, content in files_from_reply(reply):
        posix = _posix_relative(relative)
        if posix == WIRING_FILENAME:
            continue
        try:
            _check_relative(posix)
        except AifluxxError as exc:
            skipped.append(str(exc))
            continue
        writes.append((posix, content))
    return writes, skipped


def apply_writes(project: Path, writes: list[tuple[str, str]]) -> list[Path]:
    """Write allow-listed files under ``project``. No shell, no path escape."""
    root = project.resolve()
    if not root.is_dir():
        raise AifluxxError(f"{root} is not a project folder.")
    written: list[Path] = []
    for relative, content in writes:
        dest = project_write_path(root, relative)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8", newline="\n")
        written.append(dest)
    return written


def project_write_path(project: Path, relative: str) -> Path:
    """Resolve one allow-listed path and refuse anything outside ``project``."""
    root = project.resolve()
    posix = _check_relative(relative)
    dest = (root.joinpath(*posix.split("/"))).resolve()
    if not dest.is_relative_to(root):
        raise AifluxxError(f"Refusing to write {relative!r}: it is outside the project.")
    return dest


def read_layout_file(project: Path) -> tuple[str, dict[str, Any]]:
    """Current layout text and document. A missing file is the default layout."""
    path = project / LAYOUT_FILENAME
    if not path.is_file():
        document = default_layout()
        return serialize_layout(document), document
    text = path.read_text(encoding="utf-8")
    return text, load_layout_text(text)


def _normalize_rows(screen: str, raw_rows: Any) -> list[dict[str, int | str]]:
    known = SCREEN_COMPONENTS[screen]
    seen: set[str] = set()
    ordered: list[dict[str, int | str]] = []
    if isinstance(raw_rows, list):
        for row in raw_rows:
            if not isinstance(row, dict):
                continue
            component_id = row.get("id")
            if not isinstance(component_id, str) or component_id not in known or component_id in seen:
                continue
            seen.add(component_id)
            default_w, default_h = DEFAULT_SIZE[component_id]
            ordered.append(
                {
                    "id": component_id,
                    "w": _clamp(row.get("w"), MIN_W, MAX_W, default_w),
                    "h": _clamp(row.get("h"), MIN_H, MAX_H, default_h),
                }
            )
    for component_id in known:
        if component_id in seen:
            continue
        width, height = DEFAULT_SIZE[component_id]
        ordered.append({"id": component_id, "w": width, "h": height})
    return ordered


def _pack(items: list[dict[str, int | str]]) -> list[dict[str, Any]]:
    """Greedy 12-column pack. Input order is kept; coordinates are assigned.

    This is duplicated in the Starter UI (``src/lib/layout.ts``). Keep the two
    copies on the same rules: first fitting row, then the leftmost column.
    """
    occupancy: dict[int, int] = {}

    def fits(row: int, col: int, width: int, height: int) -> bool:
        if col < 1 or col + width - 1 > GRID_COLUMNS:
            return False
        for y in range(row, row + height):
            mask = occupancy.get(y, 0)
            for x in range(col, col + width):
                if mask & (1 << (x - 1)):
                    return False
        return True

    def occupy(row: int, col: int, width: int, height: int) -> None:
        for y in range(row, row + height):
            mask = occupancy.get(y, 0)
            for x in range(col, col + width):
                mask |= 1 << (x - 1)
            occupancy[y] = mask

    placed: list[dict[str, Any]] = []
    for item in items:
        width = int(item["w"])
        height = int(item["h"])
        found: tuple[int, int] | None = None
        for row in range(1, 241):
            for col in range(1, GRID_COLUMNS + 1):
                if fits(row, col, width, height):
                    found = (col, row)
                    break
            if found is not None:
                break
        if found is None:
            raise AifluxxError(f"No grid cell fits {item['id']}.")
        col, row = found
        occupy(row, col, width, height)
        placed.append({"id": item["id"], "col": col, "row": row, "w": width, "h": height})
    return placed


def _box(item: dict[str, Any]) -> dict[str, Any]:
    return {"id": item["id"], "col": item["col"], "row": item["row"], "w": item["w"], "h": item["h"]}


def _clamp(value: object, low: int, high: int, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    if isinstance(value, float) and not value.is_integer():
        return default
    number = int(value)
    return min(high, max(low, number))


def _posix_relative(relative: str) -> str:
    return relative.replace("\\", "/").strip()


def _check_relative(relative: str) -> str:
    posix = _posix_relative(relative)
    if not posix or posix.startswith("/") or posix.startswith("~") or ":" in Path(posix).parts[0]:
        raise AifluxxError(f"Refusing to write {relative!r}: it is outside the project.")
    parts = tuple(part for part in posix.split("/") if part != "")
    if any(part in {".", ".."} for part in parts):
        raise AifluxxError(f"Refusing to write {relative!r}: it is outside the project.")
    cleaned = "/".join(parts)
    if cleaned not in _ALLOWED_FILES and not (cleaned.startswith("ui/") and len(parts) >= 2 and parts[-1] not in {".", ".."}):
        raise AifluxxError(
            f"Refusing to write {cleaned}: only layout, wiring, instructions, spec, and ui/ are written."
        )
    if cleaned.startswith("ui/") and parts[-1].startswith("."):
        raise AifluxxError(f"Refusing to write {cleaned}: it is outside the project.")
    return cleaned
