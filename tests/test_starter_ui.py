"""`aifluxx starter-ui` copies the bundled Starter UI."""
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from aifluxx_sdk.cli import STARTER_UI_DIR, app

runner = CliRunner()
_EXPECTED = ("package.json", "LICENSE", "README.md", "index.html", "server/index.ts", "src/App.tsx", ".env.example", ".gitignore")


def test_package_data_present():
    for rel in _EXPECTED:
        assert (STARTER_UI_DIR / rel).is_file(), rel
    assert "commit:" in (STARTER_UI_DIR / "UPSTREAM").read_text()
    for junk in ("node_modules", ".git", "dist"):
        assert not (STARTER_UI_DIR / junk).exists()


def test_command_copies_files(tmp_path: Path):
    dest = tmp_path / "ui"
    result = runner.invoke(app, ["starter-ui", str(dest)])
    assert result.exit_code == 0, result.output
    for rel in _EXPECTED:
        assert (dest / rel).read_bytes() == (STARTER_UI_DIR / rel).read_bytes()
    assert not (dest / "UPSTREAM").exists()


def test_refuses_non_empty_without_force(tmp_path: Path):
    (tmp_path / "keep.txt").write_text("x")
    result = runner.invoke(app, ["starter-ui", str(tmp_path)])
    assert result.exit_code != 0
    assert not (tmp_path / "package.json").exists()
    result = runner.invoke(app, ["starter-ui", str(tmp_path), "--force"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "package.json").is_file() and (tmp_path / "keep.txt").exists()
