from pathlib import Path

from typer.testing import CliRunner

from aifluxx_sdk.cli import app
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
    monkeypatch.setenv("TRUEST_CREDENTIALS", str(store))
    result = runner.invoke(
        app,
        ["login", "--api-key", "afx_dev_test_key", "--url", "https://api.example"],
    )
    assert result.exit_code == 0, result.output
    creds = load_credentials(store)
    assert creds.api_key == "afx_dev_test_key"
    assert creds.url == "https://api.example"


def test_validate_without_package(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["validate"])
    assert result.exit_code == 1
    assert "spec.yaml" in result.output
