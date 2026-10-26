"""Built-in allow-lists and the host tool-catalogue parser.

``GET /api/dev/tools`` is the source of truth when the caller is logged in.
This module is the offline copy used when that catalogue is missing.
``list_compliance_obligations`` and ``get_compliance_status`` are not in the
copy: the host rejects them with ``422 unknown_tool``.
"""
from __future__ import annotations

import re
from typing import Any

READ_TOOLS = frozenset(
    {
        "search_company_knowledge",
        "get_document",
        "list_mandate_tasks",
        "list_contacts",
        "list_businesses",
    }
)

# Former tool ids the host no longer publishes. validate names the replacement.
TOOL_ALIASES = {
    "search_documents": "search_company_knowledge",
}

WRITE_TOOLS = frozenset(
    {
        "send",
        "send_mail",
        "mail_send",
        "create_task",
        "update_task",
        "add_note",
        "create_document",
        "write_document",
    }
)

CONNECTORS = frozenset(
    {
        "gmail_mail",
        "imap_mail",
        "ms_graph_mail",
        "sharepoint",
        "google_drive",
        "onedrive",
        "slack",
    }
)

CATEGORIES = frozenset(
    {
        "finance",
        "compliance",
        "sales",
        "operations",
        "hr",
        "engineering",
        "general",
    }
)

SCHEMAS = frozenset({"aifluxx/agent/v1"})

_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_LIST_KEYS = (
    "tools",
    "read",
    "write",
    "read_tools",
    "write_tools",
    "items",
    "data",
    "allow_list",
    "allowlist",
    "builtins",
    "builtin",
)
_NAME_KEYS = ("name", "id", "tool", "tool_id", "tool_name")
_NOT_TOOLS = frozenset(
    {
        "allow_list",
        "allowlist",
        "builtin",
        "builtins",
        "data",
        "description",
        "detail",
        "error",
        "id",
        "items",
        "kind",
        "message",
        "name",
        "note",
        "ok",
        "read",
        "read_tools",
        "result",
        "results",
        "schema",
        "slug",
        "state",
        "status",
        "tool",
        "tool_id",
        "tool_name",
        "tools",
        "type",
        "version",
        "write",
        "write_tools",
    }
)


def _add(names: set[str], value: object) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text or text in _NOT_TOOLS or not _TOOL_NAME.fullmatch(text):
        return False
    names.add(text)
    return True


def _walk(node: Any, names: set[str]) -> None:
    if isinstance(node, str):
        _add(names, node)
        return
    if isinstance(node, list):
        for item in node:
            _walk(item, names)
        return
    if not isinstance(node, dict):
        return
    if any(key in node for key in _LIST_KEYS):
        for key in _LIST_KEYS:
            if key in node:
                _walk(node[key], names)
        for key in _NAME_KEYS:
            _add(names, node.get(key))
        return
    # A tool row carries its id in name/id/tool. Schema objects hang off other keys
    # and must not be read as extra tool ids.
    if any(isinstance(node.get(key), str) for key in _NAME_KEYS):
        for key in _NAME_KEYS:
            _add(names, node.get(key))
        return
    for key, value in node.items():
        if isinstance(value, dict):
            _add(names, key)


def parse_tool_catalogue(payload: Any) -> frozenset[str]:
    """Pull tool ids out of a ``GET /api/dev/tools`` body.

    Accepts a list of names, a list of ``{name|id|tool}`` objects, a
    ``{"tools": ...}`` envelope, split ``read`` / ``write`` lists, and a map
    of tool id to JSON schema. Returns an empty set when nothing matches.
    """
    names: set[str] = set()
    _walk(payload, names)
    return frozenset(names)
