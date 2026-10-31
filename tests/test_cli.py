import json
import re
import subprocess
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from aifluxx_sdk.cli import _client, _verify_credentials, app, currency_for_account
from aifluxx_sdk.credentials import DEV_URL, load_credentials
from aifluxx_sdk.exceptions import AuthError

# GitHub Actions sets GITHUB_ACTIONS, and Typer then forces a colour terminal.
# Pin a wide dumb terminal so help text does not wrap or embed ANSI codes.
# LINES is set with COLUMNS so a dumb terminal keeps this width.
_HELP_ENV = {
    "NO_COLOR": "1",
    "TERM": "dumb",
    "COLUMNS": "160",
    "LINES": "40",
}
runner = CliRunner(env=_HELP_ENV)

# CSI / SGR sequences Rich inserts when a terminal is forced on.
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def _text(result) -> str:
    raw = result.output + (getattr(result, "stderr", None) or "")
    return _strip_ansi(raw)


def _flat(text: str) -> str:
    cleaned = _strip_ansi(text)
    for mark in ("│", "╭", "╮", "╰", "╯", "─"):
        cleaned = cleaned.replace(mark, " ")
    return " ".join(cleaned.split())


@pytest.fixture
def allow_login(monkeypatch):
    monkeypatch.setattr("aifluxx_sdk.cli._verify_credentials", lambda url, api_key: {"org": {"name": "Acme"}})


def test_currency_for_account_prefers_org_then_za_region():
    assert currency_for_account(None) == "USD"
    assert currency_for_account({"org": {"name": "Acme"}}) == "USD"
    assert currency_for_account({"org": {"currency": "gbp", "region": "ZA"}}) == "GBP"
    assert currency_for_account({"org": {"region": "za"}}) == "ZAR"
    assert currency_for_account({"organisation": {"country": "South Africa"}}) == "ZAR"
    assert currency_for_account({"organization": {"country_code": "ZAF"}}) == "ZAR"
    assert currency_for_account({"org": {"region": "en-ZA"}}) == "ZAR"
    assert currency_for_account({"region": "ZA"}) == "ZAR"
    assert currency_for_account({"org": {"billing": {"currency": "eur"}}}) == "EUR"
    assert currency_for_account({"org": {"currency": "R", "region": "ZA"}}) == "ZAR"
    assert currency_for_account({"org": {"region": "US"}}) == "USD"
    assert currency_for_account({"org": {"region": "Zambia"}}) == "USD"


def test_init_currency_from_org_or_za_region(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(tmp_path / "missing-credentials"))

    logged_out = runner.invoke(app, ["init", "offline-agent"])
    assert logged_out.exit_code == 0, logged_out.output
    offline = (tmp_path / "offline-agent" / "spec.yaml").read_text(encoding="utf-8")
    assert "currency: USD" in offline

    monkeypatch.setattr(
        "aifluxx_sdk.cli._account_for_scaffold",
        lambda: {"org": {"currency": "gbp", "region": "ZA"}},
    )
    priced = runner.invoke(app, ["init", "priced-agent"])
    assert priced.exit_code == 0, priced.output
    assert "currency: GBP" in (tmp_path / "priced-agent" / "spec.yaml").read_text(encoding="utf-8")

    monkeypatch.setattr("aifluxx_sdk.cli._account_for_scaffold", lambda: {"org": {"region": "ZA"}})
    za = runner.invoke(app, ["init", "za-agent"])
    assert za.exit_code == 0, za.output
    assert "currency: ZAR" in (tmp_path / "za-agent" / "spec.yaml").read_text(encoding="utf-8")


def test_init_reads_currency_from_me(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = tmp_path / "credentials"
    store.write_text('{"url": "https://api.example", "api_key": "afx_dev_k"}\n', encoding="utf-8")
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(store))
    monkeypatch.delenv("AIFLUXX_API_URL", raising=False)
    seen: dict[str, str] = {}

    def verify(url, api_key):
        seen["url"] = url
        seen["api_key"] = api_key
        return {"organisation": {"country": "ZA"}}

    monkeypatch.setattr("aifluxx_sdk.cli._verify_credentials", verify)
    result = runner.invoke(app, ["init", "from-me"])
    assert result.exit_code == 0, result.output
    assert seen == {"url": "https://api.example", "api_key": "afx_dev_k"}
    assert "currency: ZAR" in (tmp_path / "from-me" / "spec.yaml").read_text(encoding="utf-8")


def test_init_uses_usd_when_org_lookup_fails(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = tmp_path / "credentials"
    store.write_text('{"url": "https://api.example", "api_key": "afx_dev_k"}\n', encoding="utf-8")
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(store))
    monkeypatch.delenv("AIFLUXX_API_URL", raising=False)

    def explode(url, api_key):
        raise AuthError("host down")

    monkeypatch.setattr("aifluxx_sdk.cli._verify_credentials", explode)
    result = runner.invoke(app, ["init", "fallback-agent"])
    text = _text(result)
    assert result.exit_code == 0, text
    assert "Using USD" in text
    assert "currency: USD" in (tmp_path / "fallback-agent" / "spec.yaml").read_text(encoding="utf-8")


def test_init_and_validate(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(tmp_path / "missing-credentials"))
    result = runner.invoke(app, ["init", "finance-summariser", "--template", "finance"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "finance-summariser" / "spec.yaml").is_file()
    result = runner.invoke(app, ["validate", str(tmp_path / "finance-summariser")])
    assert result.exit_code == 0, result.output
    assert "OK" in result.output


def test_init_unknown_template(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", "x", "--template", "nope"])
    assert result.exit_code == 1
    assert "Unknown template" in result.output


def test_login_writes_credentials(tmp_path: Path, monkeypatch, allow_login):
    store = tmp_path / "credentials"
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(store))
    result = runner.invoke(
        app,
        ["login", "--api-key", "afx_dev_test_key", "--url", "https://api.example"],
    )
    assert result.exit_code == 0, result.output
    creds = load_credentials(store)
    assert creds.api_key == "afx_dev_test_key"
    assert creds.url == "https://api.example"


def _http_factory(seen: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"org": {"name": "Acme"}})

    real = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    return factory


def test_login_dev_key_on_production_calls_me(tmp_path: Path, monkeypatch):
    store = tmp_path / "credentials"
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(store))
    monkeypatch.delenv("AIFLUXX_API_URL", raising=False)
    seen: list[str] = []
    monkeypatch.setattr("aifluxx_sdk.client.httpx.Client", _http_factory(seen))
    result = runner.invoke(app, ["login", "--api-key", "afx_dev_test_key", "--url", "https://api.aifluxx.co.za"])
    text = _text(result)
    assert result.exit_code == 0, text
    assert seen == ["https://api.aifluxx.co.za/api/dev/me"]
    assert "No request was sent" not in text
    assert "Saved" in text
    assert load_credentials(store).url == "https://api.aifluxx.co.za"
    assert load_credentials(store).api_key == "afx_dev_test_key"
    explicit = runner.invoke(app, ["login", "--api-key", "afx_dev_test_key", "--platform", "aifluxx"])
    assert explicit.exit_code == 0, explicit.output
    assert seen == [
        "https://api.aifluxx.co.za/api/dev/me",
        "https://api.aifluxx.co.za/api/dev/me",
    ]


def test_verify_and_client_send_dev_key_to_production(tmp_path: Path, monkeypatch):
    store = tmp_path / "credentials"
    store.write_text(
        '{"url": "https://api.aifluxx.co.za", "api_key": "afx_dev_k"}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(store))
    monkeypatch.delenv("AIFLUXX_API_URL", raising=False)
    seen: list[str] = []
    monkeypatch.setattr("aifluxx_sdk.client.httpx.Client", _http_factory(seen))
    payload = _verify_credentials("https://api.aifluxx.co.za", "afx_dev_k")
    assert payload["org"]["name"] == "Acme"
    client = _client()
    try:
        assert client.url == "https://api.aifluxx.co.za"
        assert client.dev.me()["org"]["name"] == "Acme"
    finally:
        client.close()
    assert seen == [
        "https://api.aifluxx.co.za/api/dev/me",
        "https://api.aifluxx.co.za/api/dev/me",
    ]


def test_login_uses_env_url(tmp_path: Path, monkeypatch, allow_login):
    store = tmp_path / "credentials"
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(store))
    monkeypatch.setenv("AIFLUXX_API_URL", "https://api.example")
    result = runner.invoke(app, ["login", "--api-key", "afx_dev_test_key"])
    assert result.exit_code == 0, result.output
    assert load_credentials(store).url == "https://api.example"


def test_saved_dev_login_url_is_reused(tmp_path: Path, monkeypatch, allow_login):
    store = tmp_path / "credentials"
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(store))
    monkeypatch.delenv("AIFLUXX_API_URL", raising=False)
    logged_in = runner.invoke(app, ["login", "--api-key", "afx_dev_test_key", "--url", DEV_URL])
    assert logged_in.exit_code == 0, logged_in.output
    assert load_credentials(store).url == DEV_URL
    client = _client()
    try:
        assert client.url == DEV_URL
        assert client.mcp_url == f"{DEV_URL}/mcp/"
    finally:
        client.close()
    monkeypatch.setenv("AIFLUXX_API_URL", "https://api.override")
    overridden = _client()
    try:
        assert overridden.url == "https://api.override"
        assert overridden.mcp_url == "https://api.override/mcp/"
    finally:
        overridden.close()
    explicit = runner.invoke(
        app,
        ["login", "--api-key", "afx_dev_test_key", "--url", "https://api.example"],
    )
    assert explicit.exit_code == 0, explicit.output
    assert load_credentials(store).url == "https://api.example"


def test_env_url_overrides_saved_credentials(tmp_path: Path, monkeypatch):
    store = tmp_path / "credentials"
    store.write_text('{"url": "https://api.saved", "api_key": "afx_dev_k"}\n', encoding="utf-8")
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(store))
    monkeypatch.setenv("AIFLUXX_API_URL", "https://api.override")
    client = _client()
    try:
        assert client.url == "https://api.override"
    finally:
        client.close()


def test_keys_list_shows_name(tmp_path: Path, monkeypatch):
    store = tmp_path / "credentials"
    store.write_text('{"url": "https://api.example", "api_key": "afx_dev_k"}\n', encoding="utf-8")
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(store))
    monkeypatch.delenv("AIFLUXX_API_URL", raising=False)

    class _Dev:
        def list_keys(self):
            return {
                "keys": [
                    {"id": "k1", "name": "laptop", "prefix": "afx_dev_", "status": "active"},
                    {"id": "k2", "prefix": "afx_live_"},
                ]
            }

    class _Fake:
        dev = _Dev()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    monkeypatch.setattr("aifluxx_sdk.cli._client", lambda: _Fake())
    listed = runner.invoke(app, ["keys", "list"])
    text = _text(listed)
    assert listed.exit_code == 0, text
    assert "laptop" in text
    assert "k1" in text
    assert "Active" in text
    named = next(line for line in text.splitlines() if "k1" in line)
    assert named.index("laptop") < named.index("k1")
    unnamed = next(line for line in text.splitlines() if "k2" in line)
    assert "laptop" not in unnamed
    raw = runner.invoke(app, ["keys", "list", "--json"])
    assert '"name": "laptop"' in raw.output


def test_keys_list_rotate_revoke(tmp_path: Path, monkeypatch):
    store = tmp_path / "credentials"
    store.write_text('{"url": "https://api.example", "api_key": "afx_dev_k"}\n', encoding="utf-8")
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(store))
    monkeypatch.delenv("AIFLUXX_API_URL", raising=False)

    class _Dev:
        def list_keys(self):
            return {"keys": [{"id": "k1", "prefix": "afx_dev_"}]}

        def rotate_key(self, key_id):
            assert key_id == "k1"
            return {"id": "k1", "api_key": "afx_dev_rotated_secret"}

        def revoke_key(self, key_id):
            assert key_id == "k1"
            return {"id": "k1", "revoked": True}

    class _Fake:
        dev = _Dev()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    monkeypatch.setattr("aifluxx_sdk.cli._client", lambda: _Fake())
    listed = runner.invoke(app, ["keys", "list"])
    assert listed.exit_code == 0, listed.output
    assert "k1" in listed.output
    rotated = runner.invoke(app, ["keys", "rotate", "k1", "--save"])
    assert rotated.exit_code == 0, rotated.output
    assert "afx_dev_rotated_secret" in rotated.output
    assert "shown once" in rotated.output
    assert load_credentials(store).api_key == "afx_dev_rotated_secret"
    declined = runner.invoke(app, ["keys", "revoke", "k1"], input="n\n")
    assert declined.exit_code == 1
    revoked = runner.invoke(app, ["keys", "revoke", "k1", "--yes"])
    assert revoked.exit_code == 0, revoked.output
    assert "revoked" in _text(revoked).lower()


def test_keys_create_shows_the_secret_once(tmp_path: Path, monkeypatch):
    store = tmp_path / "credentials"
    store.write_text('{"url": "https://api.example", "api_key": "afx_dev_k"}\n', encoding="utf-8")
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(store))
    monkeypatch.delenv("AIFLUXX_API_URL", raising=False)
    seen: dict[str, str | None] = {}

    class _Dev:
        def create_key(self, name=None):
            seen["name"] = name
            return {
                "id": "k9",
                "name": name or "Sandbox key",
                "prefix": "afx_dev_",
                "key_once": "afx_dev_created_secret",
                "key_hash": "not-the-secret",
            }

    class _Fake:
        dev = _Dev()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    monkeypatch.setattr("aifluxx_sdk.cli._client", lambda: _Fake())
    created = runner.invoke(app, ["keys", "create", "--name", "laptop", "--save"])
    text = _text(created)
    assert created.exit_code == 0, text
    assert seen["name"] == "laptop"
    assert text.count("afx_dev_created_secret") == 1
    assert "shown once" in text
    assert "not-the-secret" not in text
    assert "key_once" not in text
    assert load_credentials(store).api_key == "afx_dev_created_secret"
    raw = runner.invoke(app, ["keys", "create", "--json"])
    assert raw.exit_code == 0, raw.output
    assert seen["name"] is None
    assert raw.output.count("afx_dev_created_secret") == 1
    assert "key_once" not in raw.output
    assert "key_hash" not in raw.output
    assert '"id": "k9"' in raw.output


def test_run_reads_slug_from_package_or_argument(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    created = runner.invoke(app, ["init", "my-agent", "--template", "compliance"])
    assert created.exit_code == 0, created.output
    monkeypatch.chdir(tmp_path / "my-agent")
    seen: dict[str, str] = {}

    class _Dev:
        def run(self, slug, prompt, *, version=None, lock=None):
            seen["slug"] = slug
            seen["prompt"] = prompt
            yield "ok"

    class _Fake:
        dev = _Dev()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    monkeypatch.setattr("aifluxx_sdk.cli._client", lambda: _Fake())
    inside = runner.invoke(app, ["run", "Summarise open tasks"])
    assert inside.exit_code == 0, inside.output
    assert seen == {"slug": "my-agent", "prompt": "Summarise open tasks"}
    explicit = runner.invoke(app, ["run", "other-agent", "Hello there"])
    assert explicit.exit_code == 0, explicit.output
    assert seen == {"slug": "other-agent", "prompt": "Hello there"}


def _fake_run(lines: list[str]):
    class _Dev:
        def run(self, slug, prompt, *, version=None, lock=None):
            yield from lines

    class _Fake:
        dev = _Dev()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    return _Fake()


def test_run_exits_nonzero_when_final_state_failed_or_errored(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "aifluxx_sdk.cli._client",
        lambda: _fake_run(
            [
                '{"type":"text","delta":"partial"}',
                '{"type":"done","state":"failed","error":"tool timed out"}',
            ]
        ),
    )
    failed = runner.invoke(app, ["run", "my-agent", "hello"])
    failed_text = _text(failed)
    assert failed.exit_code == 1, failed_text
    assert "partial" in failed_text
    assert "Failed: tool timed out" in failed_text

    monkeypatch.setattr(
        "aifluxx_sdk.cli._client",
        lambda: _fake_run(['data: {"status":"errored","error":{"message":"sandbox crashed"}}']),
    )
    errored = runner.invoke(app, ["run", "my-agent", "hello"])
    errored_text = _text(errored)
    assert errored.exit_code == 1, errored_text
    assert "Errored: sandbox crashed" in errored_text

    monkeypatch.setattr(
        "aifluxx_sdk.cli._client",
        lambda: _fake_run(['{"state":"failed","error":"ignored"}', '{"type":"done","status":"completed"}']),
    )
    completed = runner.invoke(app, ["run", "my-agent", "hello"])
    assert completed.exit_code == 0, completed.output
    assert "Failed:" not in _text(completed)

    monkeypatch.setattr("aifluxx_sdk.cli._client", lambda: _fake_run(['{"state":"FAILED"}']))
    bare = runner.invoke(app, ["run", "my-agent", "hello"])
    assert bare.exit_code == 1
    assert "Run failed." in _text(bare)


def test_run_without_prompt_prints_usage_or_reads_stdin(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    missing = runner.invoke(app, ["run"])
    text = _text(missing)
    assert missing.exit_code == 1
    assert "Usage:" in text
    assert "PROMPT" in text
    assert "stdin" in text
    created = runner.invoke(app, ["init", "my-agent", "--template", "compliance"])
    assert created.exit_code == 0, created.output
    monkeypatch.chdir(tmp_path / "my-agent")
    seen: dict[str, str] = {}

    class _Dev:
        def run(self, slug, prompt, *, version=None, lock=None):
            seen["slug"] = slug
            seen["prompt"] = prompt
            yield "ok"

    class _Fake:
        dev = _Dev()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    monkeypatch.setattr("aifluxx_sdk.cli._client", lambda: _Fake())
    piped = runner.invoke(app, ["run"], input="piped prompt\n")
    assert piped.exit_code == 0, piped.output
    assert seen == {"slug": "my-agent", "prompt": "piped prompt"}


def test_run_outside_package_requires_slug(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["run", "just a prompt"])
    assert result.exit_code == 1
    assert "slug" in result.output.lower()


def test_validate_without_package(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["validate"])
    assert result.exit_code == 1
    assert "spec.yaml" in result.output


def test_help_lists_login():
    result = runner.invoke(app, ["--help"])
    text = _text(result)
    assert result.exit_code == 0, text
    assert "login" in text
    assert "--json" in text
    assert "AIFluxx" in text
    assert "AIfluxx" not in text


def test_version_flag_prints_sdk_version():
    import tomllib

    from aifluxx_sdk import __version__

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    declared = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    assert declared == "1.3.0"
    assert __version__ == "1.3.0"
    init_text = (pyproject.parent / "src" / "aifluxx_sdk" / "__init__.py").read_text(encoding="utf-8")
    assert '__version__ = "1.3.0"' in init_text
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0, _text(result)
    assert _text(result).strip() == "1.3.0"


def test_readme_install_dev_login_and_brand():
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    assert "pip install git+https://github.com/aifluxx/aifluxx-sdk\n" in readme
    assert "aifluxx-sdk @ git+" not in readme
    assert "aifluxx login --platform dev" in readme
    assert "dev.aifluxx.co.za/mcp/" in readme
    assert "AIFLUXX_API_URL" in readme
    assert "AIFluxx" in readme
    assert "AIfluxx" not in readme


def test_login_help_lists_dev_platform_and_stdin():
    result = runner.invoke(app, ["login", "--help"])
    text = _text(result)
    assert result.exit_code == 0, text
    assert "--platform" in text
    assert "--api-key-stdin" in text
    flat = _flat(text)
    assert "dev.aifluxx.co.za" in flat
    assert "aifluxx (https://api.aifluxx.co.za)" in flat
    assert "aifluxx login --platform dev" in flat
    assert "production" in flat.lower()


def test_login_prints_platform(tmp_path: Path, monkeypatch, allow_login):
    store = tmp_path / "credentials"
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(store))
    prod = runner.invoke(app, ["login", "--api-key", "afx_live_test_key"])
    prod_text = _text(prod)
    assert prod.exit_code == 0, prod_text
    assert "Logging in to aifluxx (production, https://api.aifluxx.co.za)." in prod_text
    dev = runner.invoke(app, ["login", "--api-key", "afx_dev_test_key", "--platform", "dev"])
    dev_text = _text(dev)
    assert dev.exit_code == 0, dev_text
    assert "Logging in to dev (https://dev.aifluxx.co.za)." in dev_text
    assert "production" not in dev_text
    custom = runner.invoke(app, ["login", "--api-key", "afx_dev_test_key", "--url", "https://api.example"])
    custom_text = _text(custom)
    assert custom.exit_code == 0, custom_text
    assert "Logging in to https://api.example." in custom_text
    assert "Verified https://api.example (Acme)." in custom_text


def test_login_platform_dev(tmp_path: Path, monkeypatch, allow_login):
    store = tmp_path / "credentials"
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(store))
    dev = runner.invoke(app, ["login", "--api-key", "afx_dev_test_key", "--platform", "dev"])
    assert dev.exit_code == 0, dev.output
    assert load_credentials(store).url == "https://dev.aifluxx.co.za"
    assert "production" not in _text(dev)
    assert "Saved" in _text(dev)


def test_login_live_key_on_prod_does_not_warn(tmp_path: Path, monkeypatch, allow_login):
    store = tmp_path / "credentials"
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(store))
    result = runner.invoke(app, ["login", "--api-key", "afx_live_test_key"])
    assert result.exit_code == 0, result.output
    assert "WARNING" not in _text(result)
    assert load_credentials(store).url == "https://api.aifluxx.co.za"


def test_login_verifies_me_before_saving(tmp_path: Path, monkeypatch):
    store = tmp_path / "credentials"
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(store))
    seen: list[tuple[str, str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.headers.get("authorization")))
        return httpx.Response(200, json={"org": {"name": "Acme"}})

    real = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr("aifluxx_sdk.client.httpx.Client", factory)
    result = runner.invoke(app, ["login", "--api-key", "afx_dev_test_key", "--url", "https://api.example"])
    text = _text(result)
    assert result.exit_code == 0, text
    assert seen == [("GET", "/api/dev/me", "Bearer afx_dev_test_key")]
    assert "Verified https://api.example (Acme)." in text
    assert "Saved" in text
    saved_at = text.index("Saved")
    verified_at = text.index("Verified")
    assert verified_at < saved_at
    assert load_credentials(store).api_key == "afx_dev_test_key"


def test_login_does_not_save_when_me_rejects(tmp_path: Path, monkeypatch):
    store = tmp_path / "credentials"
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(store))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Sign in again to create a key."})

    real = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr("aifluxx_sdk.client.httpx.Client", factory)
    result = runner.invoke(app, ["login", "--api-key", "afx_dev_test_key", "--url", "https://api.example"])
    text = _text(result)
    assert result.exit_code == 1
    assert "Saved" not in text
    assert "nothing was saved" in text
    assert "401" in text
    assert not store.exists()


def test_login_api_key_stdin_skips_prompt(tmp_path: Path, monkeypatch, allow_login):
    store = tmp_path / "credentials"
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(store))

    def explode(*args, **kwargs):
        raise AssertionError("prompt should not run")

    monkeypatch.setattr("aifluxx_sdk.cli.typer.prompt", explode)
    result = runner.invoke(
        app,
        ["login", "--api-key-stdin", "--url", "https://api.example"],
        input="  afx_dev_piped_key  \n",
    )
    assert result.exit_code == 0, result.output
    assert load_credentials(store).api_key == "afx_dev_piped_key"
    assert "GetPassWarning" not in _text(result)


def test_login_refuses_both_key_sources(tmp_path: Path, monkeypatch, allow_login):
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(tmp_path / "credentials"))
    result = runner.invoke(
        app,
        ["login", "--api-key", "afx_dev_x", "--api-key-stdin", "--url", "https://api.example"],
        input="afx_dev_other\n",
    )
    assert result.exit_code == 1
    assert "not both" in _text(result)


def test_login_pipe_without_stdin_flag_shows_usage(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(tmp_path / "credentials"))

    def explode(*args, **kwargs):
        raise AssertionError("prompt should not run")

    monkeypatch.setattr("aifluxx_sdk.cli.typer.prompt", explode)
    result = runner.invoke(app, ["login", "--url", "https://api.example"], input="afx_dev_x\n")
    text = _text(result)
    assert result.exit_code == 1
    assert "--api-key-stdin" in text
    assert "Usage:" in text


def test_init_list_and_missing_slug(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    listed = runner.invoke(app, ["init", "--list"])
    text = _text(listed)
    assert listed.exit_code == 0, text
    assert "compliance [default]" in text
    assert "finance" in text
    assert "search_company_knowledge" in text
    assert "tools: list_obligations" in text
    assert "ask_assistant" in text
    assert "get_document" not in text
    assert "truest" not in text.lower()
    assert "search_documents" not in text
    assert "list_compliance_obligations" not in text
    assert "get_compliance_status" not in text
    assert "alias: compliance-checklist" in text
    assert "alias: finance-summariser" in text
    assert "alias: qa-documents" in text
    assert list(tmp_path.iterdir()) == []
    raw = runner.invoke(app, ["init", "--list", "--json"])
    payload = json.loads(raw.output)
    assert {row["template"] for row in payload} >= {"compliance", "standup"}
    default = next(row for row in payload if row["default"])
    assert default["template"] == "compliance"
    assert default["aliases"] == ["compliance-checklist"]
    missing = runner.invoke(app, ["init", "--template", "finance"])
    usage = _text(missing)
    assert missing.exit_code == 1
    assert "Usage:" in usage
    assert "SLUG" in usage
    assert not (tmp_path / "finance").exists()


def test_init_prompts_for_slug(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("aifluxx_sdk.cli._interactive", lambda: True)
    result = runner.invoke(app, ["init", "--template", "qa-over-documents"], input="prompted-agent\n")
    assert result.exit_code == 0, result.output
    spec = (tmp_path / "prompted-agent" / "spec.yaml").read_text(encoding="utf-8")
    assert "slug: prompted-agent" in spec
    assert "search_company_knowledge" in spec
    assert "ask_assistant" in spec
    assert "get_document" not in spec


def test_validate_uses_host_catalogue(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(tmp_path / "missing-credentials"))
    created = runner.invoke(app, ["init", "my-agent"])
    assert created.exit_code == 0, created.output
    monkeypatch.setattr("aifluxx_sdk.cli._host_read_tools", lambda: frozenset({"get_document"}))
    result = runner.invoke(app, ["validate", str(tmp_path / "my-agent")])
    text = _text(result)
    assert result.exit_code == 1
    assert "list_obligations" in text
    assert "host tool catalogue" in text


def test_status_is_human_by_default_and_json_is_raw(tmp_path: Path, monkeypatch):
    store = tmp_path / "credentials"
    store.write_text('{"url": "https://api.example", "api_key": "afx_dev_k"}\n', encoding="utf-8")
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(store))
    monkeypatch.delenv("AIFLUXX_API_URL", raising=False)
    version = "11111111-1111-1111-1111-111111111111"

    class _Dev:
        def status(self):
            return {
                "agents": [
                    {
                        "slug": "board",
                        "name": "Board pack",
                        "versions": [
                            {"version": "0.1.0", "state": "draft", "id": version},
                            {"version": "0.2.0", "state": "SUBMITTED"},
                        ],
                    }
                ]
            }

    class _Fake:
        dev = _Dev()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    monkeypatch.setattr("aifluxx_sdk.cli._client", lambda: _Fake())
    human = runner.invoke(app, ["status"])
    assert human.exit_code == 0, human.output
    assert "board" in human.output
    assert "Draft" in human.output
    assert "Submitted" in human.output
    assert "SUBMITTED" not in human.output
    assert '"draft"' not in human.output
    raw = runner.invoke(app, ["status", "--json"])
    assert raw.exit_code == 0, raw.output
    assert '"draft"' in raw.output
    assert "SUBMITTED" in raw.output
    rooted = runner.invoke(app, ["--json", "status"])
    assert rooted.exit_code == 0, rooted.output
    assert '"draft"' in rooted.output


def test_init_help_default_is_the_listed_template():
    help_text = _flat(_text(runner.invoke(app, ["init", "--help"])))
    listed = _text(runner.invoke(app, ["init", "--list"]))
    assert "[default: compliance]" in help_text
    assert "compliance-checklist is an alias for compliance" in help_text
    assert "finance-summariser is an alias for finance" in help_text
    assert "qa-documents is an alias for qa-over-documents" in help_text
    assert "truest" not in help_text.lower()
    template_ids = []
    alias_names = []
    for line in listed.splitlines():
        if line.startswith("  alias:"):
            alias_names.append(line.split(":", 1)[1].strip())
        elif line and not line.startswith(" "):
            template_ids.append(line.split()[0])
    assert "compliance" in template_ids
    assert "compliance" not in alias_names
    assert "compliance-checklist" in alias_names


def test_help_lists_login_commands_still_present():
    result = runner.invoke(app, ["init", "--help"])
    text = _text(result)
    assert result.exit_code == 0, text
    assert "--list" in text
    assert "[slug]" in text.lower()


def test_init_help_lists_venv_flags():
    text = _flat(_text(runner.invoke(app, ["init", "--help"])))
    assert "--venv" in text
    assert "--no-venv" in text
    assert ".venv" in text


def test_init_default_and_no_venv_skip_the_virtualenv(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(tmp_path / "missing-credentials"))
    default = runner.invoke(app, ["init", "plain-agent"])
    assert default.exit_code == 0, _text(default)
    assert (tmp_path / "plain-agent" / "spec.yaml").is_file()
    assert not (tmp_path / "plain-agent" / ".venv").exists()
    explicit = runner.invoke(app, ["init", "explicit-agent", "--no-venv"])
    assert explicit.exit_code == 0, _text(explicit)
    assert (tmp_path / "explicit-agent" / "spec.yaml").is_file()
    assert (tmp_path / "explicit-agent" / "instructions.md").is_file()
    assert (tmp_path / "explicit-agent" / "README.md").is_file()
    assert (tmp_path / "explicit-agent" / "samples.yaml").is_file()
    assert not (tmp_path / "explicit-agent" / ".venv").exists()


def test_init_venv_creates_package_venv_and_validate_ignores_it(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(tmp_path / "missing-credentials"))
    result = runner.invoke(app, ["init", "venv-agent", "--venv"])
    text = _text(result)
    assert result.exit_code == 0, text
    root = tmp_path / "venv-agent"
    venv = root / ".venv"
    assert (venv / "pyvenv.cfg").is_file()
    assert "Do not commit it" in text
    (venv / "leak.txt").write_text("token = 'supersecretvalue'\n", encoding="utf-8")
    checked = runner.invoke(app, ["validate", str(root)])
    checked_text = _text(checked)
    assert checked.exit_code == 0, checked_text
    assert "OK" in checked_text
    assert "secret_in_package" not in checked_text


def test_init_list_with_venv_writes_nothing(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", "--list", "--venv"])
    assert result.exit_code == 0, _text(result)
    assert list(tmp_path.iterdir()) == []


def test_init_venv_failure_does_not_leave_a_partial_venv(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(tmp_path / "missing-credentials"))

    def fail(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd, stderr="No module named venv")

    monkeypatch.setattr("aifluxx_sdk.cli.subprocess.run", fail)
    result = runner.invoke(app, ["init", "broken-agent", "--venv"])
    text = _text(result)
    assert result.exit_code == 1
    assert "Could not create" in text
    assert ".venv" in text
    assert (tmp_path / "broken-agent" / "spec.yaml").is_file()
    assert not (tmp_path / "broken-agent" / ".venv").exists()


def test_readme_install_with_cursor_prompt():
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    start = readme.index("## Install with Cursor\n")
    end = readme.index("\n## Install\n", start)
    section = readme[start:end]
    assert section.count("```") == 2
    assert "```text\n" in section
    assert "Open Cursor, copy the prompt below, and paste it into Cursor's chat." in section
    assert "python3 --version" in section
    assert "3.11" in section
    assert "source .venv/bin/activate" in section
    assert "Activate.ps1" in section
    assert "pip install git+https://github.com/aifluxx/aifluxx-sdk@v1.3.0" in section
    assert "aifluxx login" in section
    assert "Never echo the key" in section
    assert "aifluxx init <project> --venv" in section
    assert "aifluxx init <project> --no-venv" in section
    assert "aifluxx validate <project>" in section
    assert "Report what you did" in section
    assert "aifluxx-sdk @ git+" not in section
