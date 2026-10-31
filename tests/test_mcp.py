"""MCP server: tool listing, happy paths, and auth. HTTP is mocked."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from aifluxx_sdk.cli import app
from aifluxx_sdk.mcp_server import build_server, cursor_mcp_document, generic_mcp_document
from aifluxx_sdk.templates import get_template, render_spec
from mcp.server.fastmcp.exceptions import ToolError

KEY = "afx_dev_supersecretkey9999"
FILE_KEY = "afx_dev_filekeyvalue0001"
VERSION = "11111111-1111-1111-1111-111111111111"
API = "https://api.example"

TOOLS = [
    "projects_list",
    "projects_get",
    "projects_create",
    "agents_list",
    "agents_get",
    "agents_create",
    "agents_update",
    "connectors_list_catalog",
    "connectors_list_connections",
    "connectors_read_schema",
    "validate_manifest",
    "push_package",
    "submit_for_review",
    "review_status",
    "companion_send_message",
    "companion_get_reply",
    "handoffs_create",
    "handoffs_list",
    "handoffs_get",
    "portfolios_me",
    "portfolios_overview",
    "portfolios_org",
    "portfolios_hide",
]

V11 = {
    "handoffs_create",
    "handoffs_list",
    "handoffs_get",
    "portfolios_me",
    "portfolios_overview",
    "portfolios_org",
    "portfolios_hide",
}

runner = CliRunner()


def _agents() -> dict[str, Any]:
    return {
        "agents": [
            {
                "slug": "board",
                "name": "Board pack",
                "description": "Weekly board pack for the finance team and the audit committee.",
                "external_connections": [
                    {
                        "id": "c1",
                        "url": "https://hooks.example/in",
                        "secret": KEY,
                        "password": "pw",
                    }
                ],
                "connectors_blueprint": [{"connector": "gmail_mail", "schema_version": "1"}],
                "api_key": KEY,
                "note": f"echo {KEY}",
            }
        ]
    }


def _catalog() -> dict[str, Any]:
    return {
        "connectors": [
            {
                "slug": "gmail_mail",
                "name": "Gmail",
                "schema_version": "1",
                "access": "read",
                "entities": [
                    {
                        "name": "messages",
                        "access": "read",
                        "fields": [{"name": "subject", "type": "string"}],
                    }
                ],
                "tools": ["gmail.users.messages.list"],
            }
        ]
    }


def _package(tmp_path: Path) -> Path:
    package = tmp_path / "board"
    package.mkdir()
    template = get_template("compliance")
    (package / "spec.yaml").write_text(render_spec("board", template), encoding="utf-8")
    (package / "instructions.md").write_text(template.instructions, encoding="utf-8")
    return package


def _transport(monkeypatch, handler):
    real = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr("aifluxx_sdk.client.httpx.Client", factory)


def _login(tmp_path: Path, monkeypatch, *, api_key: str = KEY, url: str = API) -> None:
    store = tmp_path / "credentials"
    store.write_text(json.dumps({"url": url, "api_key": api_key}) + "\n", encoding="utf-8")
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(store))
    monkeypatch.delenv("AIFLUXX_API_KEY", raising=False)
    monkeypatch.delenv("AIFLUXX_API_URL", raising=False)


def _no_login(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(tmp_path / "missing-credentials"))
    monkeypatch.delenv("AIFLUXX_API_KEY", raising=False)
    monkeypatch.delenv("AIFLUXX_API_URL", raising=False)


def _data(result: Any) -> dict[str, Any]:
    if isinstance(result, tuple):
        structured = result[1]
        if isinstance(structured, dict):
            if set(structured) == {"root"} and isinstance(structured["root"], dict):
                return structured["root"]
            return structured
        result = result[0]
    if isinstance(result, list) and result:
        text = getattr(result[0], "text", None)
        if isinstance(text, str):
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
    if isinstance(result, dict):
        return result
    raise AssertionError(f"unexpected tool result {type(result)!r}: {result!r}")


def _call(server, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    result = asyncio.run(server.call_tool(name, arguments or {}))
    return _data(result)


def _text_of(blob: Any) -> str:
    return json.dumps(blob)


class _Router:
    def __init__(self) -> None:
        self.seen: list[httpx.Request] = []
        self.json_calls: list[tuple[str, str, dict[str, Any]]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        path = request.url.path
        method = request.method
        if "discover" in path:
            raise AssertionError(f"discover must not be called: {method} {path}")
        content_type = request.headers.get("content-type", "")
        if content_type.startswith("application/json") and request.content:
            self.json_calls.append((method, path, json.loads(request.content.decode())))
        if path == "/api/dev/tools":
            return httpx.Response(404, json={"detail": "Not Found"})
        if path == "/api/dev/agents" and method == "GET":
            return httpx.Response(200, json=_agents())
        if path == "/api/dev/agents" and method == "POST":
            body = json.loads(request.content.decode())
            return httpx.Response(200, json={"slug": body.get("slug") or "board", "saved": body})
        if path == "/api/dev/connectors" and method == "GET":
            return httpx.Response(200, json=_catalog())
        if path == f"/api/dev/agents/board/versions/{VERSION}" and method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": VERSION,
                    "version": "0.1.0",
                    "state": "in_review",
                    "validator_report": {"ok": True},
                    "scan_report": {"ok": True},
                    "badges": [],
                },
            )
        if path == "/api/dev/agents/board/versions" and method == "POST":
            return httpx.Response(200, json={"id": VERSION, "version": "0.1.0", "state": "draft"})
        if path == f"/api/dev/agents/board/versions/{VERSION}/submit" and method == "POST":
            return httpx.Response(200, json={"ok": True, "state": "in_review"})
        if path == "/api/dev/companion/messages" and method == "POST":
            return httpx.Response(
                200,
                json={
                    "reply": "Open the platform connector schema.",
                    "refusal": None,
                    "conversation_id": "conv-1",
                    "tools": ["connectors_read_schema"],
                    "servable": True,
                },
            )
        if path == "/api/dev/agents/board/handoffs" and method == "POST":
            body = json.loads(request.content.decode())
            return httpx.Response(200, json={"id": "h1", "summary": body["summary"], "title": body.get("title")})
        if path == "/api/dev/agents/board/handoffs" and method == "GET":
            return httpx.Response(200, json={"handoffs": [{"id": "h1", "summary": "Pick up the board pack."}]})
        if path == "/api/dev/agents/board/handoffs/h1" and method == "GET":
            return httpx.Response(200, json={"id": "h1", "summary": "Pick up the board pack."})
        if path == "/api/dev/portfolios/me" and method == "GET":
            return httpx.Response(200, json={"developer": "ada"})
        if path == "/api/dev/portfolios/overview" and method == "GET":
            return httpx.Response(200, json={"orgs": [{"id": "org-1", "name": "Acme"}]})
        if path == "/api/dev/portfolios/orgs/org-1" and method == "GET":
            return httpx.Response(200, json={"id": "org-1", "name": "Acme"})
        if path == "/api/dev/portfolios/orgs/org-1/hide" and method == "POST":
            return httpx.Response(200, json={"hidden": True, "org_id": "org-1"})
        return httpx.Response(500, json={"detail": f"unexpected {method} {path}"})


def _server(tmp_path: Path, monkeypatch):
    _login(tmp_path, monkeypatch)
    router = _Router()
    _transport(monkeypatch, router)
    from aifluxx_sdk.client import AifluxxClient

    def factory() -> AifluxxClient:
        return AifluxxClient(API, api_key=KEY)

    return build_server(client_factory=factory), router


def _paths(router: _Router, method: str) -> list[str]:
    return [request.url.path for request in router.seen if request.method == method]


def test_lists_tools_resources_and_prompts():
    server = build_server(client_factory=lambda: None)  # type: ignore[arg-type, return-value]
    tools = asyncio.run(server.list_tools())
    by_name = {tool.name: tool for tool in tools}
    assert set(by_name) == set(TOOLS)
    for name, tool in by_name.items():
        assert tool.description
        assert tool.inputSchema.get("type") == "object"
        assert "properties" in tool.inputSchema
        if name in V11:
            assert "requires platform v1.1" in tool.description
    assert "name" in by_name["projects_create"].inputSchema["required"]
    assert "slug" in by_name["agents_get"].inputSchema["required"]
    assert "message" in by_name["companion_send_message"].inputSchema["required"]

    resources = asyncio.run(server.list_resources())
    resource_uris = {str(item.uri) for item in resources}
    assert "aifluxx://schemas/agent" in resource_uris
    assert "aifluxx://schemas/connectors" in resource_uris
    templates = asyncio.run(server.list_resource_templates())
    assert any("aifluxx://agents/{slug}/manifest" in str(item.uriTemplate) for item in templates)

    prompts = asyncio.run(server.list_prompts())
    prompt_names = {item.name for item in prompts}
    assert prompt_names == {"start_new_agent", "resume_from_handoff"}
    resume = next(item for item in prompts if item.name == "resume_from_handoff")
    assert resume.description and "requires platform v1.1" in resume.description


def test_schema_resources_and_prompts_need_no_http():
    server = build_server(client_factory=lambda: (_ for _ in ()).throw(AssertionError("no client")))
    agent = asyncio.run(server.read_resource("aifluxx://schemas/agent"))
    connectors = asyncio.run(server.read_resource("aifluxx://schemas/connectors"))
    agent_text = agent[0].content if isinstance(agent, list) else agent
    connector_text = connectors[0].content if isinstance(connectors, list) else connectors
    if isinstance(agent_text, bytes):
        agent_text = agent_text.decode()
    if isinstance(connector_text, bytes):
        connector_text = connector_text.decode()
    assert "aifluxx/agent/v1" in agent_text
    assert "provider" in connector_text.lower()

    start = asyncio.run(server.get_prompt("start_new_agent", {"slug": "board", "template": "compliance"}))
    resume = asyncio.run(server.get_prompt("resume_from_handoff", {"agent": "board", "handoff_id": "h1"}))
    start_text = json.dumps(start.model_dump() if hasattr(start, "model_dump") else start)
    resume_text = json.dumps(resume.model_dump() if hasattr(resume, "model_dump") else resume)
    assert "board" in start_text
    assert "validate_manifest" in start_text
    assert "h1" in resume_text
    assert "requires platform v1.1" in resume_text


def test_each_tool_happy_path(tmp_path: Path, monkeypatch):
    server, router = _server(tmp_path, monkeypatch)
    package = _package(tmp_path)

    projects = _call(server, "projects_list")
    assert projects["projects"][0]["slug"] == "board"
    assert KEY not in _text_of(projects)
    assert projects["projects"][0]["api_key"] == "[redacted]"
    assert _paths(router, "GET") == ["/api/dev/agents"]

    project = _call(server, "projects_get", {"slug": "board"})
    assert project["project"]["slug"] == "board"

    created = _call(server, "projects_create", {"name": "Board pack", "slug": "board"})
    assert created["slug"] == "board"
    create_body = next(body for method, path, body in router.json_calls if method == "POST" and path == "/api/dev/agents")
    assert create_body["name"] == "Board pack"
    assert create_body["slug"] == "board"
    assert "description" not in create_body

    agents = _call(server, "agents_list")
    assert agents["agents"][0]["slug"] == "board"
    agent = _call(server, "agents_get", {"slug": "board"})
    assert agent["agent"]["name"] == "Board pack"
    assert KEY not in _text_of(agent)

    blueprint = [{"connector": "gmail_mail", "schema_version": "1", "entities": []}]
    made = _call(
        server,
        "agents_create",
        {"name": "Board pack", "slug": "board", "connectors_blueprint": blueprint},
    )
    assert "gmail.users" not in _text_of(made)
    saved = [body for method, path, body in router.json_calls if method == "POST" and path == "/api/dev/agents"][-1]
    assert saved["connectors_blueprint"] == blueprint
    assert "instructions" not in saved

    updated = _call(server, "agents_update", {"slug": "board", "description": "Updated board pack description for review."})
    assert updated["saved"]["slug"] == "board"
    assert "name" not in updated["saved"]
    assert updated["saved"]["description"].startswith("Updated")

    catalog = _call(server, "connectors_list_catalog")
    assert catalog["connectors"][0]["slug"] == "gmail_mail"
    schema = _call(server, "connectors_read_schema", {"connector": "gmail_mail"})
    assert schema["schema"]["schema_version"] == "1"
    assert schema["schema"]["entities"][0]["name"] == "messages"
    assert "tools" not in schema["schema"]
    assert "gmail.users" not in _text_of(schema)

    connections = _call(server, "connectors_list_connections", {"agent": "board"})
    row = connections["connections"][0]
    assert row["url"] == "https://hooks.example/in"
    assert row["secret"] == "[redacted]"
    assert row["password"] == "[redacted]"
    assert KEY not in _text_of(connections)
    assert not any("discover" in request.url.path for request in router.seen)

    validated = _call(server, "validate_manifest", {"path": str(package)})
    assert validated["ok"] is True
    assert validated["slug"] == "board"

    pushed = _call(server, "push_package", {"path": str(package)})
    assert pushed["id"] == VERSION
    assert f"/api/dev/agents/board/versions" in _paths(router, "POST")

    submitted = _call(server, "submit_for_review", {"slug": "board", "version": VERSION})
    assert submitted["ok"] is True
    assert f"/api/dev/agents/board/versions/{VERSION}/submit" in _paths(router, "POST")

    status = _call(server, "review_status", {"slug": "board", "version": VERSION})
    assert status["state"] == "in_review"
    assert status["validator_report"]["ok"] is True
    assert f"/api/dev/agents/board/versions/{VERSION}" in _paths(router, "GET")

    sent = _call(
        server,
        "companion_send_message",
        {"message": "How do I add a connector?", "project_slug": "board", "mode": "build"},
    )
    assert sent["reply"].startswith("Open the platform")
    reply = _call(
        server,
        "companion_get_reply",
        {"message": "How do I add a connector?", "project_slug": "board", "mode": "config"},
    )
    assert reply["reply"].startswith("Open the platform")
    assert reply["conversation_id"] == "conv-1"
    assert reply["refusal"] is None
    companion = [body for method, path, body in router.json_calls if path == "/api/dev/companion/messages"]
    assert [row["mode"] for row in companion] == ["build", "config"]
    assert all(row["project_slug"] == "board" for row in companion)

    handoff = _call(
        server,
        "handoffs_create",
        {"agent": "board", "summary": "Pick up the board pack.", "title": "Monday"},
    )
    assert handoff["id"] == "h1"
    assert handoff["title"] == "Monday"
    listed = _call(server, "handoffs_list", {"agent": "board"})
    assert listed["handoffs"][0]["id"] == "h1"
    one = _call(server, "handoffs_get", {"agent": "board", "handoff_id": "h1"})
    assert one["summary"] == "Pick up the board pack."

    me = _call(server, "portfolios_me")
    assert me["developer"] == "ada"
    overview = _call(server, "portfolios_overview")
    assert overview["orgs"][0]["id"] == "org-1"
    org = _call(server, "portfolios_org", {"org_id": "org-1"})
    assert org["name"] == "Acme"
    hidden = _call(server, "portfolios_hide", {"org_id": "org-1"})
    assert hidden["hidden"] is True

    for request in router.seen:
        assert request.headers["authorization"] == f"Bearer {KEY}"
        assert str(request.url).startswith(API)
    assert KEY not in _text_of(
        {
            "projects": projects,
            "connections": connections,
            "schema": schema,
        }
    )


def test_agent_manifest_resource_redacts_secrets(tmp_path: Path, monkeypatch):
    server, _router = _server(tmp_path, monkeypatch)
    payload = asyncio.run(server.read_resource("aifluxx://agents/board/manifest"))
    content = payload[0].content
    if isinstance(content, bytes):
        content = content.decode()
    parsed = json.loads(content)
    assert parsed["slug"] == "board"
    assert parsed["api_key"] == "[redacted]"
    assert KEY not in content


def test_missing_credentials_is_an_auth_error(tmp_path: Path, monkeypatch):
    _no_login(tmp_path, monkeypatch)
    server = build_server()
    with pytest.raises(ToolError) as exc:
        _call(server, "projects_list")
    text = str(exc.value)
    assert "Not logged in" in text
    assert "aifluxx login" in text
    assert KEY not in text


def test_rejected_key_is_scrubbed(tmp_path: Path, monkeypatch):
    _login(tmp_path, monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {KEY}"
        return httpx.Response(401, json={"detail": f"rejected {KEY}"})

    _transport(monkeypatch, handler)
    from aifluxx_sdk.client import AifluxxClient

    server = build_server(client_factory=lambda: AifluxxClient(API, api_key=KEY))
    with pytest.raises(ToolError) as exc:
        _call(server, "agents_list")
    text = str(exc.value)
    assert "401" in text
    assert KEY not in text
    assert "[redacted]" in text


def test_env_api_key_beats_saved_credentials(tmp_path: Path, monkeypatch):
    _login(tmp_path, monkeypatch, api_key=FILE_KEY, url="https://saved.example")
    monkeypatch.setenv("AIFLUXX_API_KEY", KEY)
    monkeypatch.setenv("AIFLUXX_API_URL", API)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_agents())

    _transport(monkeypatch, handler)
    server = build_server()
    payload = _call(server, "projects_list")
    assert seen[0].headers["authorization"] == f"Bearer {KEY}"
    assert FILE_KEY not in seen[0].headers["authorization"]
    assert str(seen[0].url).startswith(API)
    assert KEY not in _text_of(payload)
    assert FILE_KEY not in _text_of(payload)


def test_logs_do_not_keep_the_key(tmp_path: Path, monkeypatch):
    _no_login(tmp_path, monkeypatch)
    build_server(client_factory=lambda: None)  # type: ignore[arg-type, return-value]
    logger = logging.getLogger("httpx")
    logger.setLevel(logging.INFO)
    captured: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record.getMessage())

    handler = _Capture()
    logger.addHandler(handler)
    try:
        logger.info("Authorization: Bearer %s", KEY)
    finally:
        logger.removeHandler(handler)
    assert captured
    assert KEY not in captured[-1]
    assert "[redacted]" in captured[-1]


def test_cursor_config_has_no_secret():
    raw = cursor_mcp_document()
    parsed = json.loads(raw)
    assert parsed["mcpServers"]["aifluxx"] == {"command": "aifluxx", "args": ["mcp"]}
    assert "afx_" not in raw
    generic = generic_mcp_document()
    assert generic["mcpServers"]["aifluxx"]["command"] == "aifluxx-mcp"
    assert "api_key" not in json.dumps(generic)


def test_init_writes_cursor_mcp_json(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _no_login(tmp_path, monkeypatch)
    result = runner.invoke(app, ["init", "board-pack", "--template", "compliance", "--cursor-mcp"])
    assert result.exit_code == 0, result.output
    mcp_file = tmp_path / "board-pack" / ".cursor" / "mcp.json"
    text = mcp_file.read_text(encoding="utf-8")
    parsed = json.loads(text)
    assert parsed["mcpServers"]["aifluxx"]["command"] == "aifluxx"
    assert parsed["mcpServers"]["aifluxx"]["args"] == ["mcp"]
    assert "afx_" not in text
    assert "API key" in result.output
    listed = runner.invoke(app, ["init", "--list", "--cursor-mcp"])
    assert listed.exit_code == 0, listed.output
    assert not (tmp_path / ".cursor" / "mcp.json").exists()


def test_mcp_help_lists_http_transport():
    result = runner.invoke(app, ["mcp", "--help"])
    text = result.output
    assert result.exit_code == 0, text
    assert "--http" in text
    assert "stdio" in text.lower()
