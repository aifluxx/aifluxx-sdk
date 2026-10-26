import json
import sys
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from aifluxx_sdk.cli import _client, app, main
from aifluxx_sdk.credentials import load_credentials

runner = CliRunner()


def _text(result) -> str:
    return result.output + (getattr(result, "stderr", None) or "")


@pytest.fixture
def allow_login(monkeypatch):
    monkeypatch.setattr("aifluxx_sdk.cli._verify_credentials", lambda url, api_key: {"org": {"name": "Acme"}})


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


def test_login_defaults_to_aifluxx(tmp_path: Path, monkeypatch, allow_login):
    store = tmp_path / "credentials"
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(store))
    monkeypatch.delenv("AIFLUXX_API_URL", raising=False)
    result = runner.invoke(app, ["login", "--api-key", "afx_dev_test_key"])
    assert result.exit_code == 0, result.output
    assert load_credentials(store).url == "https://api.aifluxx.co.za"
    assert "WARNING" in _text(result)
    assert "production" in _text(result)


def test_login_platform_truest(tmp_path: Path, monkeypatch, allow_login):
    store = tmp_path / "credentials"
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(store))
    result = runner.invoke(app, ["login", "--api-key", "afx_dev_test_key", "--platform", "truest"])
    assert result.exit_code == 0, result.output
    assert load_credentials(store).url == "https://api.truest.ae"
    assert "truest.biz" not in result.output
    assert "WARNING" in _text(result)


def test_login_rewrites_retired_host(tmp_path: Path, monkeypatch, allow_login):
    store = tmp_path / "credentials"
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(store))
    result = runner.invoke(app, ["login", "--api-key", "afx_dev_test_key", "--url", "https://api.truest.biz"])
    assert result.exit_code == 0, result.output
    assert "retired" in result.output
    assert load_credentials(store).url == "https://api.aifluxx.co.za"


def test_login_uses_env_url(tmp_path: Path, monkeypatch, allow_login):
    store = tmp_path / "credentials"
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(store))
    monkeypatch.setenv("AIFLUXX_API_URL", "https://api.example")
    result = runner.invoke(app, ["login", "--api-key", "afx_dev_test_key"])
    assert result.exit_code == 0, result.output
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


def test_truest_entrypoint_warns(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["truest", "validate"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    assert "deprecated" in capsys.readouterr().err


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
    assert result.exit_code == 0, result.output
    assert "login" in result.output
    assert "--json" in result.output


def test_login_help_lists_dev_platform_and_stdin():
    result = runner.invoke(app, ["login", "--help"])
    text = _text(result)
    assert result.exit_code == 0, text
    assert "--platform" in text
    assert "--api-key-stdin" in text
    assert "dev.developer.aifluxx.co.za" in text
    assert "dev.developer.truest.ae" in text


def test_login_platform_dev_and_truest_dev(tmp_path: Path, monkeypatch, allow_login):
    store = tmp_path / "credentials"
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(store))
    dev = runner.invoke(app, ["login", "--api-key", "afx_dev_test_key", "--platform", "dev"])
    assert dev.exit_code == 0, dev.output
    assert load_credentials(store).url == "https://dev.developer.aifluxx.co.za"
    assert "WARNING" not in _text(dev)
    truest_dev = runner.invoke(app, ["login", "--api-key", "afx_dev_test_key", "--platform", "truest-dev"])
    assert truest_dev.exit_code == 0, truest_dev.output
    assert load_credentials(store).url == "https://dev.developer.truest.ae"
    assert "WARNING" not in _text(truest_dev)


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
    assert "compliance" in text
    assert "finance" in text
    assert "search_documents" in text
    assert "list_compliance_obligations" not in text
    assert "get_compliance_status" not in text
    assert list(tmp_path.iterdir()) == []
    raw = runner.invoke(app, ["init", "--list", "--json"])
    payload = json.loads(raw.output)
    assert {row["template"] for row in payload} >= {"compliance", "standup"}
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
    assert "search_documents" in spec


def test_validate_uses_host_catalogue(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(tmp_path / "missing-credentials"))
    created = runner.invoke(app, ["init", "my-agent"])
    assert created.exit_code == 0, created.output
    monkeypatch.setattr("aifluxx_sdk.cli._host_read_tools", lambda: frozenset({"get_document"}))
    result = runner.invoke(app, ["validate", str(tmp_path / "my-agent")])
    text = _text(result)
    assert result.exit_code == 1
    assert "search_documents" in text
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


def test_client_warns_when_saved_dev_key_targets_prod(tmp_path: Path, monkeypatch, capsys):
    store = tmp_path / "credentials"
    store.write_text(
        '{"url": "https://api.aifluxx.co.za", "api_key": "afx_dev_k"}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(store))
    monkeypatch.delenv("AIFLUXX_API_URL", raising=False)
    client = _client()
    client.close()
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "production" in err


def test_help_lists_login_commands_still_present():
    result = runner.invoke(app, ["init", "--help"])
    text = _text(result)
    assert result.exit_code == 0, text
    assert "--list" in text
    assert "[slug]" in text.lower()
