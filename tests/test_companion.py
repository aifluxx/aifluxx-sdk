"""Companion chat, status, and layout handoff. HTTP is mocked."""
import json
import re
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from aifluxx_sdk.cli import app
from aifluxx_sdk.layout import default_layout, serialize_layout

# GitHub Actions forces a colour terminal. Rich then styles each hyphen, so
# the literal "--mode" is split by ANSI and a narrow wrap. Pin a wide dumb
# terminal, and strip any codes that still leak into help text.
_HELP_ENV = {
    "NO_COLOR": "1",
    "TERM": "dumb",
    "COLUMNS": "160",
    "LINES": "40",
}
runner = CliRunner(env=_HELP_ENV)
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
KEY = "afx_dev_supersecretkey9999"


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def _login(tmp_path: Path, monkeypatch, url: str = "https://api.example") -> None:
    store = tmp_path / "credentials"
    store.write_text(json.dumps({"url": url, "api_key": KEY}) + "\n", encoding="utf-8")
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(store))
    monkeypatch.delenv("AIFLUXX_API_URL", raising=False)


def _package(tmp_path: Path, monkeypatch, slug: str = "board-pack") -> Path:
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "spec.yaml").write_text(f"schema: aifluxx/agent/v1\nslug: {slug}\nname: Board\n", encoding="utf-8")
    monkeypatch.chdir(package)
    return package


def _transport(monkeypatch, handler):
    real = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr("aifluxx_sdk.client.httpx.Client", factory)


def _body(request: httpx.Request) -> dict:
    return json.loads(request.content.decode())


def test_one_shot_posts_focus_mode_and_slug(tmp_path: Path, monkeypatch):
    _login(tmp_path, monkeypatch)
    _package(tmp_path, monkeypatch)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "reply": "Open knowledge.connectors in spec.yaml.",
                "refusal": None,
                "approval": "approved",
                "version": "9",
                "region_endpoint": "https://region.example",
                "tools": ["list_obligations"],
            },
        )

    _transport(monkeypatch, handler)
    result = runner.invoke(app, ["chat", "how do I add a connector"])
    text = result.output
    assert result.exit_code == 0, text
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert request.url.path == "/api/dev/companion/messages"
    assert str(request.url).startswith("https://api.example/")
    assert request.headers["authorization"] == f"Bearer {KEY}"
    body = _body(request)
    assert body["project_slug"] == "board-pack"
    assert body["mode"] == "build"
    assert body["message"].startswith("Focus: build.")
    assert "how do I add a connector" in body["message"]
    assert "Open knowledge.connectors" in text
    assert "Tools: list_obligations" in text
    assert KEY not in text


def test_mode_flag_and_project_override(tmp_path: Path, monkeypatch):
    _login(tmp_path, monkeypatch)
    _package(tmp_path, monkeypatch, slug="from-spec")
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(_body(request))
        return httpx.Response(200, json={"reply": "Use the instructions file.", "refusal": None})

    _transport(monkeypatch, handler)
    result = runner.invoke(
        app,
        ["companion", "--mode", "config", "--project", "other-agent", "how do I add a connector"],
    )
    assert result.exit_code == 0, result.output
    assert seen[0]["mode"] == "config"
    assert seen[0]["project_slug"] == "other-agent"
    assert seen[0]["message"].startswith("Focus: config.")
    assert "from-spec" not in seen[0]["message"]


def test_env_url_and_saved_dev_url(tmp_path: Path, monkeypatch):
    _login(tmp_path, monkeypatch, url="https://dev.aifluxx.co.za")
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"reply": "ok", "refusal": None})
        return httpx.Response(
            200,
            json={
                "version": "1.4.0",
                "approval": "approved",
                "servable": True,
                "region_endpoint": "https://region.example/companion",
                "limits": {"per_minute": 20, "remaining": 18},
            },
        )

    _transport(monkeypatch, handler)
    saved = runner.invoke(app, ["chat", "--project", "demo", "hello"])
    assert saved.exit_code == 0, saved.output
    assert seen[0] == "https://dev.aifluxx.co.za/api/dev/companion/messages"
    monkeypatch.setenv("AIFLUXX_API_URL", "https://env.example")
    overridden = runner.invoke(app, ["companion", "status"])
    status_text = overridden.output
    assert overridden.exit_code == 0, status_text
    assert seen[1] == "https://env.example/api/dev/companion"
    assert "version: 1.4.0" in status_text
    assert "approval: Approved" in status_text
    assert "servable: yes" in status_text
    assert "region endpoint: https://region.example/companion" in status_text
    assert "per_minute: 20" in status_text
    assert KEY not in status_text


def test_missing_project_and_bad_mode(tmp_path: Path, monkeypatch):
    _login(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)
    missing = runner.invoke(app, ["chat", "hello"])
    assert missing.exit_code == 1
    assert "spec.yaml" in missing.output
    bad = runner.invoke(app, ["chat", "--project", "demo", "--mode", "ship", "hello"])
    assert bad.exit_code == 1
    assert "build or config" in bad.output


def test_not_logged_in(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(tmp_path / "missing"))
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["chat", "--project", "demo", "hello"])
    assert result.exit_code == 1
    assert "aifluxx login" in result.output
    assert KEY not in result.output


def test_refusal_401_429_and_not_servable(tmp_path: Path, monkeypatch):
    _login(tmp_path, monkeypatch)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json={"reply": f"do not paste {KEY}", "refusal": f"blocked {KEY}"})
        if calls["n"] == 2:
            return httpx.Response(401, json={"detail": f"rejected {KEY}"})
        if calls["n"] == 3:
            return httpx.Response(429, json={"detail": "slow down", "limits": {"per_minute": 5, "remaining": 0}})
        if calls["n"] == 4:
            return httpx.Response(503, json={"detail": "down", "servable": False})
        return httpx.Response(200, json={"reply": "no", "servable": False})

    _transport(monkeypatch, handler)
    refused = runner.invoke(app, ["chat", "--project", "demo", "build a screen"])
    refused_text = refused.output + (refused.stderr or "")
    assert refused.exit_code == 1
    assert "Refused:" in refused_text
    assert "[redacted]" in refused_text
    assert KEY not in refused_text
    for args, needle in (
        (["chat", "--project", "demo", "again"], "aifluxx login"),
        (["chat", "--project", "demo", "again"], "rate limit"),
        (["companion", "--project", "demo", "again"], "not servable"),
        (["chat", "--project", "demo", "again"], "not servable"),
    ):
        result = runner.invoke(app, args)
        text = result.output + (getattr(result, "stderr", None) or "")
        assert result.exit_code == 1, text
        assert needle in text
        assert KEY not in text


def test_repl_switches_mode_and_exits(tmp_path: Path, monkeypatch):
    _login(tmp_path, monkeypatch)
    _package(tmp_path, monkeypatch)
    monkeypatch.setattr("aifluxx_sdk.cli._interactive", lambda: True)
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(_body(request))
        return httpx.Response(200, json={"reply": "Noted.", "refusal": None})

    _transport(monkeypatch, handler)
    result = runner.invoke(app, ["chat"], input="/mode\n/config\nwhere is the system prompt\n/build\n/exit\n")
    text = result.output
    assert result.exit_code == 0, text
    assert "Mode is build." in text
    assert "Mode is config." in text
    assert "config>" in text
    assert "build>" in text
    assert seen[0]["mode"] == "config"
    assert seen[0]["message"].startswith("Focus: config.")
    assert "where is the system prompt" in seen[0]["message"]
    assert KEY not in text


def test_repl_ctrl_d_exits(tmp_path: Path, monkeypatch):
    _login(tmp_path, monkeypatch)
    monkeypatch.setattr("aifluxx_sdk.cli._interactive", lambda: True)

    def raise_eof(prompt: str = "") -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)
    result = runner.invoke(app, ["companion", "--project", "demo"])
    assert result.exit_code == 0, result.output
    assert "Companion chat (build)." in result.output


def test_layout_save_asks_then_writes_inside_the_project(tmp_path: Path, monkeypatch):
    _login(tmp_path, monkeypatch)
    package = _package(tmp_path, monkeypatch)
    monkeypatch.setattr("aifluxx_sdk.cli._interactive", lambda: True)
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url) or True)
    layout = default_layout()
    rows = layout["screens"]["Run"]
    history = next(item for item in rows if item["id"] == "history")
    layout["screens"]["Run"] = [history, *[item for item in rows if item["id"] != "history"]]
    saved = serialize_layout(layout)
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(_body(request))
        reply = (
            "Move the history block and keep the run binding.\n"
            "```aifluxx-files\n"
            '{"files":['
            '{"path":"../secrets.txt","content":"nope"},'
            '{"path":"instructions.md","content":"Be brief.\\n"},'
            '{"path":"run.sh","content":"echo hi\\n"}'
            "]}\n"
            "```\n"
        )
        return httpx.Response(200, json={"reply": reply, "refusal": None, "tools": []})

    _transport(monkeypatch, handler)
    lines = iter(["/layout", "__write__", "y", "/exit"])

    def fake_input(prompt: str = "") -> str:
        line = next(lines)
        if line == "__write__":
            (package / "aifluxx.layout.json").write_text(saved, encoding="utf-8")
            return ""
        return line

    monkeypatch.setattr("builtins.input", fake_input)
    result = runner.invoke(app, ["chat"])
    text = result.output + (getattr(result, "stderr", None) or "")
    assert result.exit_code == 0, text
    assert opened == ["http://127.0.0.1:5173/?layout=1"]
    assert "does not run a shell" in text
    assert "Layout saved." in text
    assert "history" in text
    assert seen[0]["mode"] == "build"
    assert "layout change" in seen[0]["message"]
    assert seen[0]["message"].startswith("Focus: build.")
    assert (package / "aifluxx.wiring.json").is_file()
    assert (package / "instructions.md").read_text(encoding="utf-8") == "Be brief.\n"
    assert not (package.parent / "secrets.txt").exists()
    assert not (package / "run.sh").exists()
    assert "Refusing to write" in text
    assert KEY not in text


def test_layout_save_is_not_applied_on_no(tmp_path: Path, monkeypatch):
    _login(tmp_path, monkeypatch)
    package = _package(tmp_path, monkeypatch)
    monkeypatch.setattr("aifluxx_sdk.cli._interactive", lambda: True)
    monkeypatch.setattr("webbrowser.open", lambda url: True)
    layout = default_layout()
    for item in layout["screens"]["Run"]:
        if item["id"] == "output":
            item["w"] = 8
    saved = serialize_layout(layout)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"reply": "I would widen the stream.", "refusal": None})

    _transport(monkeypatch, handler)
    lines = iter(["/config", "/layout", "/build", "/layout", "__write__", "n", "/exit"])

    def fake_input(prompt: str = "") -> str:
        line = next(lines)
        if line == "__write__":
            (package / "aifluxx.layout.json").write_text(saved, encoding="utf-8")
            return ""
        return line

    monkeypatch.setattr("builtins.input", fake_input)
    result = runner.invoke(app, ["chat", "--mode", "build"])
    text = result.output
    assert result.exit_code == 0, text
    assert "Switch with /build." in text
    assert "Not applied." in text
    assert not (package / "aifluxx.wiring.json").exists()


def test_help_and_readme_mention_companion(tmp_path: Path):
    help_text = _plain(runner.invoke(app, ["--help"]).output)
    assert "companion" in help_text
    assert "chat" in help_text
    chat_help = _plain(runner.invoke(app, ["chat", "--help"]).output)
    assert "--mode" in chat_help
    assert "--project" in chat_help
    status_help = _plain(runner.invoke(app, ["companion", "status", "--help"]).output)
    assert "region endpoint" in status_help.lower()
    readme = Path(__file__).resolve().parents[1].joinpath("README.md").read_text(encoding="utf-8")
    assert "aifluxx companion status" in readme
    assert "aifluxx.layout.json" in readme
    assert "/layout" in readme
    assert "AIFLUXX_LAYOUT_EDIT" in readme
    assert "--mode" in readme


def test_noninteractive_without_message_prints_usage(tmp_path: Path, monkeypatch):
    _login(tmp_path, monkeypatch)
    result = runner.invoke(app, ["chat", "--project", "demo"])
    assert result.exit_code == 1
    assert "Usage:" in result.output
