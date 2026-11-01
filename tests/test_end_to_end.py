"""`aifluxx init` writes the dev container, Compose, and the GitHub Action."""
from pathlib import Path

from typer.testing import CliRunner

from aifluxx_sdk.cli import app
from aifluxx_sdk.end_to_end import END_TO_END_FILES
from aifluxx_sdk.package import validate_package

runner = CliRunner()


def test_init_writes_the_dev_container_and_action(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(tmp_path / "missing-credentials"))
    result = runner.invoke(app, ["init", "cto"])
    text = result.output + (result.stderr or "")
    assert result.exit_code == 0, text
    root = tmp_path / "cto"
    for relative, body in END_TO_END_FILES.items():
        assert (root / relative).read_text(encoding="utf-8") == body
    assert "GitHub Action" in text
    report = validate_package(root)
    assert report.ok, [(row.code, row.note, row.path) for row in report.errors]


def test_scaffold_does_not_push_an_image(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(tmp_path / "missing-credentials"))
    result = runner.invoke(app, ["init", "site-agent"])
    assert result.exit_code == 0, result.output
    root = tmp_path / "site-agent"
    blob = "\n".join((root / relative).read_text(encoding="utf-8") for relative in END_TO_END_FILES)
    lowered = blob.lower()
    for banned in ("azurecr.io", "ghcr.io", "docker push", "docker login", "az acr"):
        assert banned not in lowered
    script = (root / "devcontainer" / "submit.sh").read_text(encoding="utf-8")
    assert "aifluxx validate" in script
    assert "aifluxx push" in script
    assert "aifluxx submit" in script
    assert "--slug" not in script
    workflow = (root / ".github" / "workflows" / "submit.yml").read_text(encoding="utf-8")
    assert "branches: [main]" in workflow
    assert "docker compose run --rm -e AIFLUXX_API_KEY dev sh /opt/aifluxx/submit.sh" in workflow
    assert "contents: read" in workflow
