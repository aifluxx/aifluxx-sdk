import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aifluxx_sdk.cli import _client, app, main
from aifluxx_sdk.credentials import load_credentials

runner = CliRunner()


def test_init_and_validate(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
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


def test_login_writes_credentials(tmp_path: Path, monkeypatch):
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


def test_login_defaults_to_aifluxx(tmp_path: Path, monkeypatch):
    store = tmp_path / "credentials"
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(store))
    monkeypatch.delenv("AIFLUXX_API_URL", raising=False)
    result = runner.invoke(app, ["login", "--api-key", "afx_dev_test_key"])
    assert result.exit_code == 0, result.output
    assert load_credentials(store).url == "https://api.aifluxx.co.za"


def test_login_platform_truest(tmp_path: Path, monkeypatch):
    store = tmp_path / "credentials"
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(store))
    result = runner.invoke(app, ["login", "--api-key", "afx_dev_test_key", "--platform", "truest"])
    assert result.exit_code == 0, result.output
    assert load_credentials(store).url == "https://api.truest.ae"
    assert "truest.biz" not in result.output


def test_login_rewrites_retired_host(tmp_path: Path, monkeypatch):
    store = tmp_path / "credentials"
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(store))
    result = runner.invoke(app, ["login", "--api-key", "afx_dev_test_key", "--url", "https://api.truest.biz"])
    assert result.exit_code == 0, result.output
    assert "retired" in result.output
    assert load_credentials(store).url == "https://api.truest.ae"


def test_login_uses_env_url(tmp_path: Path, monkeypatch):
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
    assert "revoked" in revoked.output


def test_validate_without_package(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["validate"])
    assert result.exit_code == 1
    assert "spec.yaml" in result.output
