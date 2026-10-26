"""Starter packages for `aifluxx init --template`.

Tool ids and aliases match ``GET /api/dev/templates`` (``TEMPLATES`` in
dubai-agents ``backend/developer_platform.py``). Stored tools are the
AIFluxx host ids. ``ask_assistant`` is written as the host ask id when the
API host is under truest.ae.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from aifluxx_sdk.exceptions import AifluxxError

# Ask tool published by GET /api/dev/templates. The other id is the same tool
# on a truest.ae host and is not used for any other host.
_ASK_TOOL = "ask_assistant"
_ASK_TOOL_ON_TRUEST_HOST = "ask_truest"


@dataclass(frozen=True)
class Template:
    slug: str
    name: str
    category: str
    description: str
    tools: tuple[str, ...]
    knowledge: tuple[str, ...]
    instructions: str


TEMPLATES: dict[str, Template] = {
    "compliance": Template(
        slug="compliance-checklist",
        name="Compliance checklist",
        category="compliance",
        description="List open obligations and missing evidence from documents the caller can already see.",
        tools=("list_obligations",),
        knowledge=(),
        instructions=(
            "You are a compliance officer for [[company_name]]. Today is [[today]].\n"
            "List open obligations the user can already see. Cite each document. "
            "If a source is missing, say so. Do not invent evidence.\n"
        ),
    ),
    "finance": Template(
        slug="finance-summariser",
        name="Finance summariser",
        category="finance",
        description="Period movements in plain language, with a citation on every number you quote.",
        tools=(_ASK_TOOL,),
        knowledge=(),
        instructions=(
            "Summarise the period for [[user_name]] at [[company_name]]. "
            "Every figure needs a citation. If you cannot see the source, say so.\n"
        ),
    ),
    "qa-over-documents": Template(
        slug="qa-over-documents",
        name="Q&A over documents",
        category="general",
        description="Answer questions from named connectors. Read only. No write tools.",
        tools=("search_company_knowledge", _ASK_TOOL),
        knowledge=("gmail_mail", "sharepoint", "google_drive"),
        instructions=(
            "Answer from documents [[user_name]] can already open. "
            "Name the document in each citation. Do not guess.\n"
        ),
    ),
    "standup": Template(
        slug="standup",
        name="Engineering standup",
        category="engineering",
        description="Yesterday, today, and blockers from tasks and mail the user can already see.",
        tools=("list_mandate_tasks", "search_company_knowledge"),
        knowledge=(),
        instructions=(
            "Write a standup for [[user_name]] on [[today]]: yesterday, today, blockers. "
            "Use only tasks and documents they can already see.\n"
        ),
    ),
    "account-snapshot": Template(
        slug="account-snapshot",
        name="Account snapshot",
        category="sales",
        description="One-page account brief from CRM notes and vault files the caller can already see.",
        tools=("list_contacts", "search_company_knowledge"),
        knowledge=(),
        instructions=(
            "Write a one-page account brief for [[company_name]]. "
            "Cite contacts and documents. Do not invent meetings or amounts.\n"
        ),
    ),
}


# Public starter id. `init --help` and `init --list` both use this string.
DEFAULT_TEMPLATE = "compliance"

# Old ids from GET /api/dev/templates. The public id stays the dict key above.
TEMPLATE_ALIASES = {
    "compliance-checklist": "compliance",
    "finance-summariser": "finance",
    "qa-documents": "qa-over-documents",
}


def template_aliases(name: str) -> tuple[str, ...]:
    return tuple(sorted(alias for alias, target in TEMPLATE_ALIASES.items() if target == name))


def _hostname(url: str | None) -> str:
    return (urlparse(url or "").hostname or "").lower().rstrip(".")


def host_ask_tool(api_url: str | None) -> str:
    """Ask tool id for ``api_url``.

    AIFluxx hosts, a missing URL, and any host other than truest.ae use
    ``ask_assistant``. A truest.ae host uses that host's ask id.
    """
    host = _hostname(api_url)
    if host == "truest.ae" or host.endswith(".truest.ae"):
        return _ASK_TOOL_ON_TRUEST_HOST
    return _ASK_TOOL


def scaffold_tools(template: Template, api_url: str | None = None) -> tuple[str, ...]:
    """Tools ``init`` writes. Order matches the API list for that host."""
    ask = host_ask_tool(api_url)
    if ask == _ASK_TOOL:
        return template.tools
    return tuple(ask if tool == _ASK_TOOL else tool for tool in template.tools)


def template_option_help() -> str:
    """Help text for `--template`. The default id is the same id `init --list` prints."""
    names = ", ".join(sorted(TEMPLATES))
    alias_text = " ".join(
        f"{alias} is an alias for {target}." for alias, target in sorted(TEMPLATE_ALIASES.items())
    )
    return f"Starter name. Default: {DEFAULT_TEMPLATE}. Names: {names}. {alias_text}"


def template_rows(api_url: str | None = None) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for name in sorted(TEMPLATES):
        chosen = TEMPLATES[name]
        rows.append(
            {
                "template": name,
                "title": chosen.name,
                "category": chosen.category,
                "description": chosen.description.strip(),
                "tools": list(scaffold_tools(chosen, api_url)),
                "aliases": list(template_aliases(name)),
                "default": name == DEFAULT_TEMPLATE,
            }
        )
    return rows


def get_template(name: str) -> Template:
    key = (name or "").strip().lower()
    key = TEMPLATE_ALIASES.get(key, key)
    if key not in TEMPLATES:
        known = ", ".join(sorted(TEMPLATES))
        raise AifluxxError(f"Unknown template {name!r}. Use: {known}.")
    return TEMPLATES[key]


def slug_to_name(slug: str) -> str:
    return " ".join(part.capitalize() for part in slug.replace("_", "-").split("-"))


def _spec_currency(currency: str | None) -> str:
    code = (currency or "").strip().upper()
    if len(code) == 3 and code.isalpha():
        return code
    return "USD"


def render_spec(slug: str, template: Template, *, currency: str | None = None, api_url: str | None = None) -> str:
    """Render spec.yaml. ``currency`` is an ISO code; anything else stays USD."""
    tools = "\n".join(f"  - {tool}" for tool in scaffold_tools(template, api_url))
    knowledge = ""
    if template.knowledge:
        connectors = ", ".join(template.knowledge)
        knowledge = f"knowledge:\n  connectors: [{connectors}]\n  folders: []\n"
    return (
        "schema: aifluxx/agent/v1\n"
        f"slug: {slug}\n"
        f"name: {slug_to_name(slug)}\n"
        f"description: >\n  {template.description}\n"
        "version: 0.1.0\n"
        f"category: {template.category}\n"
        "trigger:\n  type: chat\n"
        f"tools:\n{tools}\n"
        f"{knowledge}"
        f"pricing:\n  model: free\n  amount_minor: 0\n  currency: {_spec_currency(currency)}\n"
    )
