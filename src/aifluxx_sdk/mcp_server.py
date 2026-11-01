"""Local MCP server for the AIFluxx developer platform.

Stdio by default. ``--http`` serves streamable HTTP. Auth is ``AIFLUXX_API_KEY``
or the key saved by ``aifluxx login``. The key is never written to logs or tool results.

The server class is FastMCP from the official Python ``mcp`` SDK (1.x).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Any, Callable

from aifluxx_sdk.client import AifluxxClient, scrub_secret
from aifluxx_sdk.credentials import load_credentials
from aifluxx_sdk.dev import REQUIRES_PLATFORM_V11
from aifluxx_sdk.exceptions import AifluxxError, AuthError
from aifluxx_sdk.lockfile import load_lock
from aifluxx_sdk.package import validate_package

_INSTALL = "The MCP extra is not installed. Run: pip install 'aifluxx-sdk[mcp]'"
_INSTRUCTIONS = (
    "AIFluxx developer platform tools. They call the aifluxx-sdk client. "
    "Authentication is the AIFLUXX_API_KEY environment variable, or the key saved by `aifluxx login`. "
    "Never ask for the key and never put it in a file you write. "
    "Agents read connector data through the platform schema (connectors_read_schema), not raw provider tools. "
    f"Handoff and portfolio tools {REQUIRES_PLATFORM_V11}."
)

# Keys whose values are secrets. Matched case-insensitively on the object key.
_SECRET_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "client_secret",
        "key_once",
        "password",
        "password_hash",
        "refresh_token",
        "secret",
        "token",
    }
)

ClientFactory = Callable[[], AifluxxClient]


def cursor_mcp_document() -> str:
    """Cursor MCP config for this server. It does not contain an API key."""
    payload = {
        "mcpServers": {
            "aifluxx": {
                "command": "aifluxx",
                "args": ["mcp"],
            }
        }
    }
    return json.dumps(payload, indent=2) + "\n"


def generic_mcp_document() -> dict[str, Any]:
    """stdio config most MCP clients accept. No API key."""
    return {
        "mcpServers": {
            "aifluxx": {
                "command": "aifluxx-mcp",
            }
        }
    }


class _SecretLogFilter(logging.Filter):
    """Drop key-shaped text from log records before they are emitted."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        cleaned = scrub_secret(message)
        record.msg = cleaned
        record.args = ()
        return True


def _install_log_redaction() -> None:
    filt = _SecretLogFilter()
    for name in ("httpx", "httpcore", "mcp", "aifluxx_sdk"):
        logger = logging.getLogger(name)
        if not any(isinstance(item, _SecretLogFilter) for item in logger.filters):
            logger.addFilter(filt)


def default_client() -> AifluxxClient:
    """Client from ``AIFLUXX_API_KEY``, otherwise the saved ``aifluxx login`` key.

    The API root stays ``resolve_api_url``: ``AIFLUXX_API_URL``, then the saved
    login URL, then production. The key is not logged.
    """
    env_key = os.environ.get("AIFLUXX_API_KEY", "").strip()
    if env_key:
        return AifluxxClient(api_key=env_key)
    creds = load_credentials()
    return AifluxxClient(api_key=creds.api_key)


def redact(node: Any) -> Any:
    """Replace secret fields and key-shaped strings. Safe to return to an MCP client."""
    if isinstance(node, dict):
        cleaned: dict[str, Any] = {}
        for key, value in node.items():
            if str(key).lower() in _SECRET_KEYS or str(key).lower().endswith("_secret"):
                cleaned[key] = "[redacted]" if value not in (None, "", [], {}) else value
            else:
                cleaned[key] = redact(value)
        return cleaned
    if isinstance(node, list):
        return [redact(item) for item in node]
    if isinstance(node, str):
        return scrub_secret(node)
    return node


def _object(payload: Any, key: str) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list):
        return {key: payload}
    return {key: payload}


def _package(path: str | None) -> tuple[Path, str, Any]:
    directory = Path(path).resolve() if path else Path.cwd()
    if not (directory / "spec.yaml").is_file():
        raise AifluxxError("No spec.yaml here. Pass path to the package folder.")
    report = validate_package(directory)
    slug = str(report.spec.get("slug") or directory.name)
    return directory, slug, load_lock(directory)


def _mode(mode: str) -> str:
    cleaned = (mode or "").strip().lower()
    if cleaned not in {"build", "config"}:
        raise AifluxxError("mode must be build or config.")
    return cleaned


def _reply(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "reply": payload.get("reply"),
        "refusal": payload.get("refusal"),
        "conversation_id": payload.get("conversation_id"),
        "tools": payload.get("tools"),
        "servable": payload.get("servable"),
    }


def build_server(
    *,
    client_factory: ClientFactory | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> Any:
    """FastMCP server. Import of ``mcp`` happens here so the extra can stay optional."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise SystemExit(_INSTALL) from exc

    _install_log_redaction()
    factory = client_factory or default_client
    mcp = FastMCP(
        "aifluxx",
        instructions=_INSTRUCTIONS,
        host=host,
        port=port,
        log_level="WARNING",
    )

    def call(fn: Callable[[AifluxxClient], Any]) -> dict[str, Any]:
        try:
            client = factory()
        except AuthError as exc:
            raise RuntimeError(scrub_secret(str(exc))) from None
        try:
            try:
                result = fn(client)
            except Exception as exc:
                raise RuntimeError(scrub_secret(str(exc))) from None
        finally:
            client.close()
        if not isinstance(result, dict):
            result = _object(result, "result")
        redacted = redact(result)
        return redacted if isinstance(redacted, dict) else {"result": redacted}

    @mcp.tool()
    def projects_list() -> dict[str, Any]:
        """List projects for the signed-in organisation.

        A project is the developer package. Published route: GET /api/dev/agents
        (OpenAPI 1.0.0 List Agents). There is no /api/dev/projects collection on that spec.
        """
        return call(lambda client: client.dev.list_projects())

    @mcp.tool()
    def projects_get(slug: str) -> dict[str, Any]:
        """Get one project by slug.

        Reads GET /api/dev/agents and returns the matching package. OpenAPI 1.0.0
        has no per-slug project route.
        """
        return call(lambda client: {"project": client.dev.get_project(slug)})

    @mcp.tool()
    def projects_create(name: str, slug: str | None = None, description: str | None = None) -> dict[str, Any]:
        """Create a project.

        POST /api/dev/agents (OpenAPI Save Agent / portal "Create agent slug").
        name is required. slug and description are optional.
        """
        return call(lambda client: _object(client.dev.create_project(name, slug=slug, description=description), "project"))

    @mcp.tool()
    def agents_list() -> dict[str, Any]:
        """List agents in the signed-in organisation. GET /api/dev/agents."""
        return call(lambda client: _object(client.dev.list_agents(), "agents"))

    @mcp.tool()
    def agents_get(slug: str) -> dict[str, Any]:
        """Get one agent by slug.

        GET /api/dev/agents, then the row whose slug matches. OpenAPI 1.0.0
        does not publish GET /api/dev/agents/{slug}.
        """
        return call(lambda client: {"agent": client.dev.get_agent(slug)})

    @mcp.tool()
    def agents_create(
        name: str,
        slug: str | None = None,
        description: str | None = None,
        category: str | None = None,
        version: str | None = None,
        instructions: str | None = None,
        tools: list[str] | None = None,
        knowledge: list[str] | None = None,
        connectors_blueprint: list[dict[str, Any]] | None = None,
        submit: bool | None = None,
    ) -> dict[str, Any]:
        """Create an agent package. POST /api/dev/agents.

        name is required. connectors_blueprint is the platform data schema
        (entities and fields), not provider tools. Omitted fields are not sent.
        """
        body = _agent_body(
            name=name,
            slug=slug,
            description=description,
            category=category,
            version=version,
            instructions=instructions,
            tools=tools,
            knowledge=knowledge,
            connectors_blueprint=connectors_blueprint,
            submit=submit,
        )
        return call(lambda client: _object(client.dev.save_agent(body), "agent"))

    @mcp.tool()
    def agents_update(
        slug: str,
        name: str | None = None,
        description: str | None = None,
        category: str | None = None,
        version: str | None = None,
        instructions: str | None = None,
        tools: list[str] | None = None,
        knowledge: list[str] | None = None,
        connectors_blueprint: list[dict[str, Any]] | None = None,
        submit: bool | None = None,
    ) -> dict[str, Any]:
        """Update an agent package. POST /api/dev/agents.

        OpenAPI Save Agent is create or update. slug selects the package.
        Only fields you pass are sent. connectors_blueprint is the platform schema.
        """
        body = _agent_body(
            name=name,
            slug=slug,
            description=description,
            category=category,
            version=version,
            instructions=instructions,
            tools=tools,
            knowledge=knowledge,
            connectors_blueprint=connectors_blueprint,
            submit=submit,
        )
        return call(lambda client: _object(client.dev.save_agent(body), "agent"))

    @mcp.tool()
    def connectors_list_catalog() -> dict[str, Any]:
        """List the platform connector catalog. GET /api/dev/connectors.

        Each row is a platform connector and its data schema. This is not a list
        of raw provider tools. The dev developer host serves this path. Published
        OpenAPI 1.0.0 does not list it yet.
        """
        return call(lambda client: _object(client.dev.list_connectors(), "connectors"))

    @mcp.tool()
    def connectors_list_connections(agent: str | None = None) -> dict[str, Any]:
        """List external connections stored on agent packages.

        GET /api/dev/agents field external_connections. Pass agent to limit the
        result to one slug. Secrets are removed from the result. Platform connector
        data is connectors_read_schema, not provider tools.
        """
        return call(lambda client: client.dev.list_connections(agent))

    @mcp.tool()
    def connectors_read_schema(connector: str) -> dict[str, Any]:
        """Read the platform data schema for one connector.

        GET /api/dev/connectors, then the row for this slug. Returns schema_version,
        access, and entities with fields. Provider tool lists are not returned.
        Agents get connector data through this schema.
        """
        return call(lambda client: {"schema": client.dev.connector_schema(connector)})

    @mcp.tool()
    def validate_manifest(path: str | None = None) -> dict[str, Any]:
        """Validate a local agent manifest. Does not call the API.

        path is the package folder. The default is the current directory.
        Checks spec.yaml against the bundled tool allow-list.
        """
        directory = Path(path).resolve() if path else Path.cwd()
        report = validate_package(directory)
        return {
            "ok": report.ok,
            "slug": report.spec.get("slug"),
            "version": report.spec.get("version"),
            "schema": report.spec.get("schema"),
            "findings": [
                {"severity": row.severity, "code": row.code, "path": row.path, "note": row.note}
                for row in report.findings
            ],
        }

    @mcp.tool()
    def push_package(path: str | None = None) -> dict[str, Any]:
        """Upload the local package and create a Draft.

        POST /api/dev/agents/{slug}/versions as multipart package plus metadata.
        path defaults to the current directory. This does not git push.
        """
        directory = Path(path).resolve() if path else Path.cwd()
        return call(lambda client: _object(client.dev.push(directory), "push"))

    @mcp.tool()
    def submit_for_review(
        slug: str | None = None,
        version: str | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        """Submit a draft for review.

        POST /api/dev/agents/{slug}/versions/{version_id}/submit.
        version_id is a UUID. Pass version as that UUID, or path to a package
        whose lock or GET /api/dev/agents lookup supplies it. A semver is looked up,
        not placed in the path.
        """
        def run(client: AifluxxClient) -> Any:
            package_slug, lock = _target(slug, path)
            return client.dev.submit(package_slug, version, lock=lock)

        return call(run)

    @mcp.tool()
    def review_status(
        slug: str | None = None,
        version: str | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        """Review status for one version.

        GET /api/dev/agents/{slug}/versions/{version_id}. The body is the version,
        validator report, scan report, badges, and state.
        """
        def run(client: AifluxxClient) -> Any:
            package_slug, lock = _target(slug, path)
            return client.dev.version_report(package_slug, version, lock=lock)

        return call(run)

    @mcp.tool()
    def companion_send_message(message: str, project_slug: str, mode: str = "build") -> dict[str, Any]:
        """Send a companion message and return the response.

        POST /api/dev/companion/messages with message, project_slug, and mode
        (build or config). The reply is in the response. The key is removed from
        the result.
        """
        focus = _mode(mode)
        text = (message or "").strip()
        if not text:
            raise AifluxxError("message is required.")
        return call(lambda client: client.companion.send(text, project_slug=project_slug, mode=focus))

    @mcp.tool()
    def companion_get_reply(message: str, project_slug: str, mode: str = "build") -> dict[str, Any]:
        """Get the companion reply for a message.

        The platform returns the reply on POST /api/dev/companion/messages.
        There is no separate GET. This sends the message and returns reply,
        refusal, conversation_id, and tools.
        """
        focus = _mode(mode)
        text = (message or "").strip()
        if not text:
            raise AifluxxError("message is required.")
        return call(lambda client: _reply(client.companion.send(text, project_slug=project_slug, mode=focus)))

    @mcp.tool()
    def handoffs_create(agent: str, summary: str, title: str | None = None) -> dict[str, Any]:
        """Create a handoff for one agent.

        POST /api/dev/agents/{agent}/handoffs. requires platform v1.1.
        Not in published OpenAPI 1.0.0 (aifluxx-developer PR 46).
        """
        return call(lambda client: _object(client.dev.create_handoff(agent, summary, title=title), "handoff"))

    @mcp.tool()
    def handoffs_list(agent: str) -> dict[str, Any]:
        """List handoffs for one agent.

        GET /api/dev/agents/{agent}/handoffs. requires platform v1.1.
        Not in published OpenAPI 1.0.0 (aifluxx-developer PR 46).
        """
        return call(lambda client: _object(client.dev.list_handoffs(agent), "handoffs"))

    @mcp.tool()
    def handoffs_get(agent: str, handoff_id: str) -> dict[str, Any]:
        """Get one handoff for an agent.

        GET /api/dev/agents/{agent}/handoffs/{handoff_id}. requires platform v1.1.
        Not in published OpenAPI 1.0.0 (aifluxx-developer PR 46).
        """
        return call(lambda client: _object(client.dev.get_handoff(agent, handoff_id), "handoff"))

    @mcp.tool()
    def portfolios_me() -> dict[str, Any]:
        """Portfolio for the signed-in developer.

        GET /api/dev/portfolios/me. requires platform v1.1.
        Not in published OpenAPI 1.0.0 (aifluxx-developer PR 46).
        """
        return call(lambda client: _object(client.dev.portfolio_me(), "portfolio"))

    @mcp.tool()
    def portfolios_overview() -> dict[str, Any]:
        """Portfolio overview across organisations.

        GET /api/dev/portfolios/overview. requires platform v1.1.
        Not in published OpenAPI 1.0.0 (aifluxx-developer PR 46).
        """
        return call(lambda client: _object(client.dev.portfolio_overview(), "overview"))

    @mcp.tool()
    def portfolios_org(org_id: str) -> dict[str, Any]:
        """Drill into one organisation in the portfolio.

        GET /api/dev/portfolios/orgs/{org_id}. requires platform v1.1.
        Not in published OpenAPI 1.0.0 (aifluxx-developer PR 46).
        """
        return call(lambda client: _object(client.dev.portfolio_org(org_id), "org"))

    @mcp.tool()
    def portfolios_hide(org_id: str) -> dict[str, Any]:
        """Hide one organisation from the portfolio.

        POST /api/dev/portfolios/orgs/{org_id}/hide. requires platform v1.1.
        Not in published OpenAPI 1.0.0 (aifluxx-developer PR 46).
        """
        return call(lambda client: _object(client.dev.portfolio_hide(org_id), "hidden"))

    @mcp.resource(
        "aifluxx://schemas/agent",
        mime_type="text/markdown",
        description="Agent manifest schema aifluxx/agent/v1, including the platform connector blueprint.",
    )
    def agent_manifest_schema() -> str:
        """Agent manifest schema (aifluxx/agent/v1)."""
        return _AGENT_SCHEMA_DOC

    @mcp.resource(
        "aifluxx://schemas/connectors",
        mime_type="text/markdown",
        description="How agents read connector data: platform schema, not raw provider tools.",
    )
    def connector_schema_doc() -> str:
        """Platform connector schema rules."""
        return _CONNECTOR_SCHEMA_DOC

    @mcp.resource(
        "aifluxx://agents/{slug}/manifest",
        mime_type="application/json",
        description="Stored agent manifest for one slug, from GET /api/dev/agents. Secrets are removed.",
    )
    def agent_manifest(slug: str) -> str:
        """Stored agent manifest."""
        payload = call(lambda client: {"manifest": client.dev.get_agent(slug)})
        return json.dumps(payload["manifest"], indent=2)

    @mcp.prompt(
        title="Start a new agent",
        description="Scaffold and publish a new agent package on the AIFluxx developer platform.",
    )
    def start_new_agent(slug: str, template: str = "compliance") -> str:
        """Prompt that walks through creating an agent."""
        return (
            f"Start a new AIFluxx agent package named {slug} from the {template} template.\n"
            "1. Use the local package files (spec.yaml schema aifluxx/agent/v1).\n"
            "2. Call validate_manifest on the package folder and fix every error.\n"
            "3. Call connectors_list_catalog and connectors_read_schema for each connector "
            "the agent should use. Put that platform schema in connectors_blueprint. "
            "Do not add raw provider tools.\n"
            "4. Call projects_create or agents_create, then push_package, then submit_for_review.\n"
            "5. Call review_status and report the state. Do not ask for or print an API key."
        )

    @mcp.prompt(
        title="Resume from handoff",
        description="Continue work from a handoff stored for one agent. requires platform v1.1.",
    )
    def resume_from_handoff(agent: str, handoff_id: str) -> str:
        """Prompt that resumes an agent from a handoff."""
        return (
            f"Resume agent {agent} from handoff {handoff_id}. "
            f"handoffs_get {REQUIRES_PLATFORM_V11}.\n"
            "1. Call handoffs_get and read the summary.\n"
            "2. Call agents_get for the same agent and connectors_read_schema for each "
            "connector in its blueprint. Use the platform schema, not provider tools.\n"
            "3. Continue the work described in the handoff. Call validate_manifest before push_package.\n"
            "4. Do not ask for or print an API key."
        )

    return mcp


def _agent_body(
    *,
    name: str | None = None,
    slug: str | None = None,
    description: str | None = None,
    category: str | None = None,
    version: str | None = None,
    instructions: str | None = None,
    tools: list[str] | None = None,
    knowledge: list[str] | None = None,
    connectors_blueprint: list[dict[str, Any]] | None = None,
    submit: bool | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if name is not None:
        cleaned = name.strip()
        if not cleaned:
            raise AifluxxError("name is required.")
        body["name"] = cleaned
    if slug is not None:
        body["slug"] = slug.strip()
    if description is not None:
        body["description"] = description
    if category is not None:
        body["category"] = category
    if version is not None:
        body["version"] = version
    if instructions is not None:
        body["instructions"] = instructions
    if tools is not None:
        body["tools"] = tools
    if knowledge is not None:
        body["knowledge"] = knowledge
    if connectors_blueprint is not None:
        body["connectors_blueprint"] = connectors_blueprint
    if submit is not None:
        body["submit"] = submit
    if "name" not in body and "slug" not in body:
        raise AifluxxError("name or slug is required.")
    return body


def _target(slug: str | None, path: str | None) -> tuple[str, Any]:
    if path:
        _directory, package_slug, lock = _package(path)
        if slug and slug.strip() and slug.strip() != package_slug:
            raise AifluxxError("slug does not match spec.yaml.")
        return package_slug, lock
    if not slug or not slug.strip():
        raise AifluxxError("Pass slug, or path to a package folder.")
    return slug.strip(), None


_AGENT_SCHEMA_DOC = """# Agent manifest

Schema id: `aifluxx/agent/v1`.

| Field | Required | Notes |
|---|---|---|
| schema | yes | `aifluxx/agent/v1` |
| slug | yes | Package id |
| name | yes | Display name |
| description | yes | At least 40 characters |
| version | yes | Semver |
| tools | no | Built-in names from GET /api/dev/tools |
| knowledge | no | Omit for no company knowledge. `connectors` and `folders` restrict search |
| connectors_blueprint | no | Platform connectors only. Each entry is the platform data schema, not provider tools |
| external_connections | no | Developer-supplied https endpoints. Auth is a secret reference |

`connectors_blueprint` pins `schema_version`, `access`, and `entities` with `fields`.
Read it with the `connectors_read_schema` tool. Do not declare provider tools there.

Host tool ids from `GET /api/dev/tools`. AIFluxx lists `ask_assistant`. `ask_aifluxx` is an alias of `ask_assistant`.

Read: `ask_assistant`, `ask_aifluxx` (alias of `ask_assistant`), `search_company_knowledge`, `search_documents` (alias), `list_documents`, `get_document`, `list_tasks`, `list_mandate_tasks`, `list_contacts`, `list_obligations`, `list_compliance_obligations`, `get_compliance_status`, `list_businesses`.

Write, approval required: `create_task`, `add_note`, `send_message`.

The bundled offline allow-list, used when that route cannot be read, is smaller. Read: `search_company_knowledge`, `get_document`, `list_obligations`, `ask_assistant`, `list_mandate_tasks`, `list_contacts`, `list_businesses`. Write: `send`, `send_mail`, `mail_send`, `create_task`, `update_task`, `add_note`, `create_document`, `write_document`. `search_documents` maps to `search_company_knowledge`. `list_compliance_obligations` and `get_compliance_status` are host-catalogue ids and are absent from the offline copy.
"""

_CONNECTOR_SCHEMA_DOC = """# Platform connector schema

Agents receive connector data through the platform schema.

- `connectors_list_catalog` is GET /api/dev/connectors.
- `connectors_read_schema` returns `schema_version`, `access`, and `entities` (name, access, fields).
- Provider tool names are not part of that result.
- `connectors_list_connections` reads `external_connections` on GET /api/dev/agents.
  Those are developer-supplied https endpoints. Secrets are removed from the tool result.
- POST /api/dev/connections/discover accepts secrets and is not an MCP tool.

Published OpenAPI 1.0.0 does not list GET /api/dev/connectors. The dev developer host serves it.

Schema version `1.0.0`. Access is `read`. Every entity has string fields `id`, `title`, `uri`, `source`.

| Slug | Source | Entity |
|---|---|---|
| `gmail_mail` | Gmail | `message` |
| `sharepoint` | SharePoint | `document` |
| `google_drive` | Google Drive | `document` |
| `onedrive` | OneDrive | `document` |
| `slack` | Slack | `message` |

`imap_mail` and `ms_graph_mail` are mailbox identities for send, with `gmail_mail`. They are not extra document entities.

Dev sandbox demo companies project connector fixtures into this shape. Search returns `id`, `title`, `uri`, and `source`. The seven vertical pilots are `skaapsteker-dm` (district municipality), `korhaanfontein-metro` (metropolitan municipality), `wolksloof-mews` (property management), `grysbok-freight` (logistics), `suurvy-citrus` (citrus and wine), `boekenhout-advisory` (accounting and legal), and `kuifkoppie-brokers` (insurance broker). Each has personas, knowledge notes, 24 months of financials, a catalogue, and fixtures for the five connectors above. They are fictitious and dev only.
"""


def main(argv: list[str] | None = None) -> None:
    """Entry point for `aifluxx mcp` and `aifluxx-mcp`."""
    parser = argparse.ArgumentParser(
        prog="aifluxx mcp",
        description="AIFluxx developer-platform MCP server. Stdio is the default.",
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="Serve streamable HTTP instead of stdio.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host. Used with --http.")
    parser.add_argument("--port", type=int, default=8000, help="HTTP port. Used with --http.")
    args = parser.parse_args(argv)
    try:
        server = build_server(host=args.host, port=args.port)
    except SystemExit:
        raise
    except ImportError as exc:
        raise SystemExit(_INSTALL) from exc
    if args.http:
        server.run(transport="streamable-http")
        return
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
