import io
import json
import tarfile
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from aifluxx_sdk.dev import DevClient, _tarball, version_uuid_from_push
from aifluxx_sdk.package import LOCAL_META_DIRS
from aifluxx_sdk.exceptions import AifluxxError, AuthError, HostUnavailable
from aifluxx_sdk.lockfile import load_lock
from aifluxx_sdk.templates import get_template, render_spec

_VERSION = "11111111-1111-1111-1111-111111111111"


class _Res:
    def __init__(self, status_code=200, payload=None, text="", headers=None, method="GET", url="https://api.example/x"):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.content = b"{}" if payload is not None else b""
        self.text = text
        self.headers = headers or {}
        self.is_stream_consumed = True
        self.request = type("Req", (), {"method": method, "url": url})()

    def json(self):
        return self._payload


def test_tools_catalogue_and_push_uses_it(tmp_path: Path):
    http = MagicMock()
    http.get.return_value = _Res(
        200,
        {"tools": [{"name": "search_company_knowledge", "kind": "read"}, {"name": "get_document"}]},
    )
    client = DevClient(http, "https://api.example")
    assert client.read_tool_names() == frozenset({"search_company_knowledge", "get_document"})
    http.get.assert_called_with("https://api.example/api/dev/tools")

    package = tmp_path / "agent"
    package.mkdir()
    template = get_template("compliance")
    spec = render_spec("agent", template).replace("tools:\n", "tools:\n  - list_compliance_obligations\n", 1)
    (package / "spec.yaml").write_text(spec, encoding="utf-8")
    (package / "instructions.md").write_text(template.instructions, encoding="utf-8")
    http.post.return_value = _Res(200, {"id": _VERSION, "version": "0.1.0", "state": "draft"})
    with pytest.raises(AifluxxError, match="unknown_tool"):
        client.push(package)
    http.post.assert_not_called()


def test_push_accepts_host_tool_absent_from_bundle(tmp_path: Path):
    package = tmp_path / "agent"
    package.mkdir()
    template = get_template("standup")
    spec = render_spec("agent", template).replace("search_company_knowledge", "list_open_filings")
    (package / "spec.yaml").write_text(spec, encoding="utf-8")
    (package / "instructions.md").write_text(template.instructions, encoding="utf-8")
    http = MagicMock()
    http.get.return_value = _Res(200, ["list_open_filings", "list_mandate_tasks"])
    http.post.return_value = _Res(200, {"id": _VERSION, "version": "0.1.0", "state": "draft"})
    client = DevClient(http, "https://api.example")
    client.push(package)
    http.post.assert_called_once()


def test_missing_tools_route_falls_back(tmp_path: Path):
    http = MagicMock()
    http.get.return_value = _Res(404, {"detail": "Not Found"})
    client = DevClient(http, "https://api.example")
    assert client.read_tool_names() is None


def test_missing_host_is_host_unavailable():
    http = MagicMock()
    http.get.return_value = _Res(404, {"detail": "Not Found"})
    client = DevClient(http, "https://api.example")
    with pytest.raises(HostUnavailable, match="Not Found"):
        client.me()


def test_keys_call_dev_paths():
    http = MagicMock()
    http.get.return_value = _Res(200, {"keys": []})
    http.post.return_value = _Res(200, {"id": "k1"})
    client = DevClient(http, "https://api.example")
    client.list_keys()
    http.get.assert_called_with("https://api.example/api/dev/keys")
    client.rotate_key("k1")
    http.post.assert_called_with("https://api.example/api/dev/keys/k1/rotate")
    client.revoke_key("k1")
    http.post.assert_called_with("https://api.example/api/dev/keys/k1/revoke")


def test_key_id_rejects_slash():
    client = DevClient(MagicMock(), "https://api.example")
    with pytest.raises(AifluxxError, match="invalid"):
        client.rotate_key("a/b")


def test_submit_resolves_uuid_and_never_sends_latest():
    http = MagicMock()
    http.get.return_value = _Res(
        200,
        {
            "agents": [
                {
                    "slug": "board",
                    "versions": [
                        {"id": _VERSION, "version": "0.1.0", "state": "draft", "created_at": "2026-10-25T00:00:00Z"}
                    ],
                }
            ]
        },
    )
    http.post.return_value = _Res(200, {"ok": True})
    client = DevClient(http, "https://api.example")
    client.submit("board", "latest")
    sent = http.post.call_args[0][0]
    assert sent.endswith(f"/versions/{_VERSION}/submit")
    assert "latest" not in sent


def test_submit_without_uuid_raises_before_post():
    http = MagicMock()
    http.get.return_value = _Res(200, {"agents": []})
    client = DevClient(http, "https://api.example")
    with pytest.raises(AifluxxError, match="version UUID"):
        client.submit("missing", None)
    http.post.assert_not_called()


def test_push_stores_version_uuid(tmp_path: Path):
    package = tmp_path / "agent"
    package.mkdir()
    template = get_template("compliance")
    (package / "spec.yaml").write_text(render_spec("agent", template), encoding="utf-8")
    (package / "instructions.md").write_text(template.instructions, encoding="utf-8")
    http = MagicMock()
    http.post.return_value = _Res(200, {"id": _VERSION, "version": "0.1.0", "state": "draft"})
    client = DevClient(http, "https://api.example")
    client.push(package)
    lock = load_lock(package)
    assert lock is not None
    assert lock.version_id == _VERSION
    assert (package / ".aifluxx" / "agent.lock").is_file()
    _assert_push_upload(http.post.call_args_list[0], "agent")
    client.submit("agent", lock=lock)
    assert http.post.call_args[0][0].endswith(f"/versions/{_VERSION}/submit")


def test_push_fills_version_id_when_response_includes_slug(tmp_path: Path):
    package = tmp_path / "agent"
    package.mkdir()
    template = get_template("compliance")
    (package / "spec.yaml").write_text(render_spec("agent", template), encoding="utf-8")
    (package / "instructions.md").write_text(template.instructions, encoding="utf-8")
    http = MagicMock()
    http.post.return_value = _Res(200, {"id": _VERSION, "slug": "agent", "version": "0.1.0"})
    client = DevClient(http, "https://api.example")
    client.push(package)
    lock = load_lock(package)
    assert lock is not None
    assert lock.version_id == _VERSION
    assert lock.slug == "agent"
    client.submit("agent", lock=lock)
    assert http.post.call_args[0][0].endswith(f"/versions/{_VERSION}/submit")


def test_version_uuid_from_push_reads_response_shapes():
    other = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert version_uuid_from_push({"id": _VERSION, "slug": "agent", "version": "0.1.0"}, "0.1.0") == _VERSION
    assert version_uuid_from_push({"id": "agent-1", "slug": "agent", "version": "0.1.0"}, "0.1.0") is None
    assert (
        version_uuid_from_push(
            {"id": other, "slug": "agent", "version_id": _VERSION, "version": "0.1.0"},
            "0.1.0",
        )
        == _VERSION
    )
    assert (
        version_uuid_from_push(
            {"slug": "agent", "version": {"id": _VERSION, "version": "0.1.0", "state": "draft"}},
            "0.1.0",
        )
        == _VERSION
    )
    assert (
        version_uuid_from_push(
            {"agent": {"slug": "agent", "versions": [{"id": _VERSION, "version": "0.1.0", "status": "draft"}]}},
            "0.1.0",
        )
        == _VERSION
    )
    assert (
        version_uuid_from_push(
            {"id": other, "slug": "agent", "version": "9.9.9"},
            "0.1.0",
        )
        is None
    )


def test_push_version_id_stays_empty_without_a_version_uuid(tmp_path: Path):
    package = tmp_path / "agent"
    package.mkdir()
    template = get_template("compliance")
    (package / "spec.yaml").write_text(render_spec("agent", template), encoding="utf-8")
    (package / "instructions.md").write_text(template.instructions, encoding="utf-8")
    http = MagicMock()
    http.post.return_value = _Res(200, {"id": "agent-1", "slug": "agent", "version": "0.1.0"})
    client = DevClient(http, "https://api.example")
    client.push(package)
    lock = load_lock(package)
    assert lock is not None
    assert lock.last_pushed_version == "0.1.0"
    assert lock.version_id is None


def _assert_push_upload(call, slug: str) -> None:
    assert call.args[0] == f"https://api.example/api/dev/agents/{slug}/versions"
    assert set(call.kwargs) == {"files"}
    files = call.kwargs["files"]
    assert set(files) == {"package", "metadata"}

    filename, archive, package_type = files["package"]
    assert filename == "package.tar.gz"
    assert package_type == "application/gzip"
    assert archive[:2] == b"\x1f\x8b"
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        names = tar.getnames()
    assert "spec.yaml" in names
    assert all(".aifluxx" not in Path(name).parts for name in names)

    meta_filename, meta_bytes, meta_type = files["metadata"]
    assert meta_filename is None
    assert meta_type == "application/json"
    meta = json.loads(meta_bytes)
    assert set(meta) == {"slug", "version", "schema", "spec"}
    assert meta["slug"] == slug
    assert meta["version"] == "0.1.0"
    assert meta["schema"] == "aifluxx/agent/v1"
    assert meta["spec"]["slug"] == slug
    assert meta["spec"]["version"] == "0.1.0"

    request = httpx.Request("POST", call.args[0], files=files)
    request.read()
    content_type = request.headers["content-type"]
    assert content_type.startswith("multipart/form-data; boundary=")
    assert not request.content.startswith(b"\x1f\x8b")
    assert b'name="package"; filename="package.tar.gz"' in request.content
    assert b"Content-Type: application/gzip" in request.content
    assert b'name="metadata"' in request.content
    assert b'filename="metadata' not in request.content
    assert b"Content-Type: application/json" in request.content


def test_401_includes_host_body():
    http = MagicMock()
    http.get.return_value = _Res(
        401,
        {"detail": "Sign in again to create a key."},
        method="GET",
        url="https://api.aifluxx.co.za/api/dev/agents",
    )
    client = DevClient(http, "https://api.aifluxx.co.za")
    with pytest.raises(AuthError, match="Sign in again to create a key") as caught:
        client.me()
    text = str(caught.value)
    assert "401" in text
    assert "host" in text.lower()


def test_500_includes_host_body():
    http = MagicMock()
    http.get.return_value = _Res(
        500,
        {"detail": "boom"},
        method="POST",
        url="https://api.aifluxx.co.za/api/dev/agents/board/versions",
    )
    client = DevClient(http, "https://api.aifluxx.co.za")
    with pytest.raises(AifluxxError, match="boom") as caught:
        client.status()
    text = str(caught.value)
    assert "500" in text
    assert "API error" in text


def test_307_to_http_is_not_followed(monkeypatch):
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.scheme != "https":
            return httpx.Response(200, json={"followed": True})
        return httpx.Response(307, headers={"location": "http://api.aifluxx.co.za/mcp/"})

    real_client = httpx.Client

    def client_factory(*args, **kwargs):
        assert kwargs.get("follow_redirects") is False
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("aifluxx_sdk.client.httpx.Client", client_factory)
    from aifluxx_sdk.client import AifluxxClient
    from aifluxx_sdk.mail import SendFailed

    client = AifluxxClient("https://api.aifluxx.co.za", api_key="afx_dev_secret")
    try:
        assert client._http.follow_redirects is False
        with pytest.raises(AifluxxError, match="http://api.aifluxx.co.za/mcp/") as caught:
            client.dev.me()
        assert "downgrad" in str(caught.value)
        with pytest.raises(SendFailed, match="http://api.aifluxx.co.za/mcp/"):
            client.mail.mailboxes(business_id="co")
    finally:
        client.close()
    assert requested == [
        "https://api.aifluxx.co.za/api/dev/me",
        "https://api.aifluxx.co.za/api/companies/co/mail/mailboxes",
    ]
    assert all(url.startswith("https://") for url in requested)


def test_307_to_http_is_reported():
    http = MagicMock()
    http.get.return_value = _Res(
        307,
        headers={"location": "http://api.aifluxx.co.za/mcp/"},
        method="GET",
        url="https://api.aifluxx.co.za/mcp",
    )
    client = DevClient(http, "https://api.aifluxx.co.za")
    with pytest.raises(AifluxxError, match="http://api.aifluxx.co.za/mcp/") as caught:
        client.me()
    text = str(caught.value)
    assert "307" in text
    assert "downgrad" in text
    assert "https://api.aifluxx.co.za/mcp/" in text


def test_307_mcp_hint_follows_the_api_host():
    http = MagicMock()
    http.get.return_value = _Res(
        307,
        headers={"location": "http://dev.aifluxx.co.za/mcp/"},
        method="GET",
        url="https://dev.aifluxx.co.za/mcp",
    )
    client = DevClient(http, "https://dev.aifluxx.co.za")
    with pytest.raises(AifluxxError, match="https://dev.aifluxx.co.za/mcp/") as caught:
        client.me()
    text = str(caught.value)
    assert "downgrad" in text
    assert "https://api.aifluxx.co.za/mcp/" not in text


class _Unread:
    def __init__(self):
        self.status_code = 500
        self.headers = {}
        self.is_stream_consumed = False
        self.read_called = False
        self.request = type(
            "Req",
            (),
            {"method": "POST", "url": f"https://api.example/api/dev/agents/board/versions/{_VERSION}/runs"},
        )()

    def read(self):
        self.read_called = True
        self.is_stream_consumed = True
        return b'{"detail":"Internal Server Error"}'

    def json(self):
        if not self.read_called:
            raise httpx.ResponseNotRead("Attempted to access streaming response content")
        return {"detail": "Internal Server Error"}

    @property
    def text(self):
        if not self.read_called:
            raise httpx.ResponseNotRead("Attempted to access streaming response content")
        return "Internal Server Error"

    @property
    def content(self):
        if not self.read_called:
            raise httpx.ResponseNotRead("Attempted to access streaming response content")
        return b"{}"

    def iter_lines(self):
        if not self.read_called:
            raise httpx.ResponseNotRead("Attempted to access streaming response content")
        yield "should-not-stream"


def test_run_reads_streamed_error_body():
    http = MagicMock()
    res = _Unread()
    http.stream.return_value.__enter__.return_value = res
    client = DevClient(http, "https://api.example")
    with pytest.raises(AifluxxError, match="Internal Server Error") as caught:
        list(client.run("board", "hello", version=_VERSION))
    assert res.read_called
    assert "ResponseNotRead" not in str(caught.value)


def test_tarball_skips_local_meta(tmp_path: Path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "spec.yaml").write_text("schema: aifluxx/agent/v1\n", encoding="utf-8")
    assert len(LOCAL_META_DIRS) >= 2
    for name in LOCAL_META_DIRS:
        folder = package / name
        folder.mkdir()
        (folder / "agent.lock").write_text("{}\n", encoding="utf-8")
    with tarfile.open(fileobj=io.BytesIO(_tarball(package)), mode="r:gz") as archive:
        names = archive.getnames()
    assert names == ["spec.yaml"]
