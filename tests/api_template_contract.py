"""Single table for GET /api/dev/templates.

Source of truth: TEMPLATES in aifluxx/dubai-agents backend/developer_platform.py,
merged in PR #118, served at https://dev.aifluxx.co.za/api/dev/templates.

``tools`` are the AIFluxx host ids, in API order. ``ask_on_truest_host`` marks
rows whose ``ask_assistant`` entry is ``ask_truest`` when the API host is
under truest.ae. ``aliases`` are every old id the API lists for that starter.
"""

from __future__ import annotations

API_TEMPLATES: tuple[dict[str, object], ...] = (
    {
        "id": "compliance",
        "aliases": ("compliance-checklist",),
        "tools": ("list_obligations",),
        "ask_on_truest_host": False,
    },
    {
        "id": "finance",
        "aliases": ("finance-summariser",),
        "tools": ("ask_assistant",),
        "ask_on_truest_host": True,
    },
    {
        "id": "qa-over-documents",
        "aliases": ("qa-documents",),
        "tools": ("search_company_knowledge", "ask_assistant"),
        "ask_on_truest_host": True,
    },
    {
        "id": "standup",
        "aliases": (),
        "tools": ("list_mandate_tasks", "search_company_knowledge"),
        "ask_on_truest_host": False,
    },
    {
        "id": "account-snapshot",
        "aliases": (),
        "tools": ("list_contacts", "search_company_knowledge"),
        "ask_on_truest_host": False,
    },
)


def tools_for_host(row: dict[str, object], *, truest_host: bool) -> tuple[str, ...]:
    tools = tuple(row["tools"])  # type: ignore[arg-type]
    if truest_host and row["ask_on_truest_host"]:
        return tuple("ask_truest" if tool == "ask_assistant" else tool for tool in tools)
    return tools
