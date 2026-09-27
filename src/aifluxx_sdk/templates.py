"""Starter packages for `truest init --template`."""
from __future__ import annotations

from dataclasses import dataclass

from aifluxx_sdk.exceptions import AifluxxError


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
        description="List open obligations and missing evidence for a jurisdiction the caller can already see.",
        tools=("list_compliance_obligations", "get_compliance_status", "search_documents", "get_document"),
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
        tools=("search_documents", "get_document", "ask_truest"),
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
        tools=("search_documents", "get_document"),
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
        tools=("list_mandate_tasks", "search_documents", "get_document"),
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
        tools=("list_contacts", "search_documents", "get_document"),
        knowledge=(),
        instructions=(
            "Write a one-page account brief for [[company_name]]. "
            "Cite contacts and documents. Do not invent meetings or amounts.\n"
        ),
    ),
}


def get_template(name: str) -> Template:
    key = (name or "").strip().lower()
    if key == "compliance-checklist":
        key = "compliance"
    if key not in TEMPLATES:
        raise AifluxxError(f"Unknown template {name!r}. Use: {', '.join(sorted(TEMPLATES))}.")
    return TEMPLATES[key]


def slug_to_name(slug: str) -> str:
    return " ".join(part.capitalize() for part in slug.replace("_", "-").split("-"))


def render_spec(slug: str, template: Template) -> str:
    tools = "\n".join(f"  - {tool}" for tool in template.tools)
    knowledge = ""
    if template.knowledge:
        connectors = ", ".join(template.knowledge)
        knowledge = f"knowledge:\n  connectors: [{connectors}]\n  folders: []\n"
    return (
        "schema: truest/agent/v1\n"
        f"slug: {slug}\n"
        f"name: {slug_to_name(slug)}\n"
        f"description: >\n  {template.description}\n"
        "version: 0.1.0\n"
        f"category: {template.category}\n"
        "trigger:\n  type: chat\n"
        f"tools:\n{tools}\n"
        f"{knowledge}"
        "pricing:\n  model: free\n  amount_minor: 0\n  currency: USD\n"
    )
