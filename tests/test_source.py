"""`aifluxx source` copies the installed SDK into a repo-style folder."""
from __future__ import annotations

import ast
from pathlib import Path

from aifluxx_sdk.cli import app
from aifluxx_sdk.source import (
    BUNDLE_DIRNAME,
    EXAMPLE_FILES,
    EXAMPLES_DIRNAME,
    ROOT_FILENAMES,
    _ignore,
    copy_sdk_source,
    package_dir,
)
from tests.test_cli import _text, runner

REPO = Path(__file__).resolve().parents[1]
_PACKAGE_FILES = (
    "src/aifluxx_sdk/__init__.py",
    "src/aifluxx_sdk/cli.py",
    "src/aifluxx_sdk/templates.py",
    "src/aifluxx_sdk/py.typed",
    "src/aifluxx_sdk/starter_ui/package.json",
    "src/aifluxx_sdk/starter_ui/README.md",
    "src/aifluxx_sdk/starter_ui/.env.example",
    "src/aifluxx_sdk/starter_ui/.gitignore",
    "src/aifluxx_sdk/starter_ui/src/App.tsx",
)


def _assign(path: Path, name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} missing from {path}")


def test_bundle_file_list_matches_setup_py():
    assert _assign(REPO / "setup.py", "ROOT_FILENAMES") == ROOT_FILENAMES
    assert _assign(REPO / "setup.py", "EXAMPLES_DIRNAME") == EXAMPLES_DIRNAME
    assert _assign(REPO / "setup.py", "BUNDLE_DIRNAME") == BUNDLE_DIRNAME


def test_ignore_skips_caches_secrets_and_the_bundle():
    ignored = _ignore(
        "/x",
        [
            "__pycache__",
            "cli.py",
            BUNDLE_DIRNAME,
            "node_modules",
            ".git",
            ".env",
            ".env.local",
            ".env.example",
            "foo.pyc",
            "aifluxx_sdk.egg-info",
        ],
    )
    assert ignored == {
        "__pycache__",
        BUNDLE_DIRNAME,
        "node_modules",
        ".git",
        ".env",
        ".env.local",
        "foo.pyc",
        "aifluxx_sdk.egg-info",
    }


def _assert_tree(dest: Path) -> None:
    for name in ROOT_FILENAMES:
        assert (dest / name).is_file(), name
        assert (dest / name).read_bytes() == (REPO / name).read_bytes()
    for name in EXAMPLE_FILES:
        copied = dest / EXAMPLES_DIRNAME / name
        assert copied.is_file(), name
        assert copied.read_bytes() == (REPO / EXAMPLES_DIRNAME / name).read_bytes()
    pkg = package_dir()
    for rel in _PACKAGE_FILES:
        copied = dest / rel
        assert copied.is_file(), rel
        original = pkg / Path(rel).relative_to("src/aifluxx_sdk")
        assert copied.read_bytes() == original.read_bytes()
    assert "TEMPLATES" in (dest / "src/aifluxx_sdk/templates.py").read_text(encoding="utf-8")
    assert not (dest / "src" / "aifluxx_sdk" / BUNDLE_DIRNAME).exists()
    assert not (dest / "src" / "aifluxx_sdk" / "__pycache__").exists()
    assert not (dest / ".git").exists()
    pyproject = (dest / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "aifluxx-sdk"' in pyproject
    assert 'version = "1.3.1"' in pyproject


def test_source_command_writes_the_tree(tmp_path: Path):
    dest = tmp_path / "sdk"
    result = runner.invoke(app, ["source", str(dest)])
    assert result.exit_code == 0, _text(result)
    assert "Created" in _text(result)
    _assert_tree(dest)


def test_default_dest_is_aifluxx_sdk(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["source"])
    assert result.exit_code == 0, _text(result)
    _assert_tree(tmp_path / "aifluxx-sdk")


def test_empty_directory_is_replaced(tmp_path: Path):
    dest = tmp_path / "empty"
    dest.mkdir()
    result = runner.invoke(app, ["source", str(dest)])
    assert result.exit_code == 0, _text(result)
    assert (dest / "src" / "aifluxx_sdk" / "templates.py").is_file()


def test_refuses_non_empty_without_force(tmp_path: Path):
    dest = tmp_path / "sdk"
    dest.mkdir()
    (dest / "keep.txt").write_text("keep", encoding="utf-8")
    refused = runner.invoke(app, ["source", str(dest)])
    assert refused.exit_code == 1
    assert "not empty" in _text(refused)
    assert "--force" in _text(refused)
    assert (dest / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert not (dest / "pyproject.toml").exists()
    forced = runner.invoke(app, ["source", str(dest), "--force"])
    assert forced.exit_code == 0, _text(forced)
    assert (dest / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert (dest / "pyproject.toml").is_file()
    again = runner.invoke(app, ["source", str(dest)])
    assert again.exit_code == 1
    assert (dest / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_refuses_a_file_destination(tmp_path: Path):
    target = tmp_path / "file"
    target.write_text("x", encoding="utf-8")
    result = runner.invoke(app, ["source", str(target)])
    assert result.exit_code == 1
    assert "not a folder" in _text(result)
    assert target.read_text(encoding="utf-8") == "x"


def test_refuses_to_copy_onto_its_own_tree():
    pkg = package_dir()
    result = runner.invoke(app, ["source", str(pkg / "nested")])
    assert result.exit_code == 1
    assert "own files" in _text(result)
    assert not (pkg / "nested").exists()


def test_skips_local_env_files(tmp_path: Path):
    secret = package_dir() / "starter_ui" / ".env"
    secret.write_text("AIFLUXX_API_KEY=local-only\n", encoding="utf-8")
    try:
        dest = tmp_path / "sdk"
        copy_sdk_source(dest)
        starter = dest / "src" / "aifluxx_sdk" / "starter_ui"
        assert not (starter / ".env").exists()
        assert (starter / ".env.example").is_file()
    finally:
        secret.unlink(missing_ok=True)


def test_missing_source_tells_you_to_reinstall(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("aifluxx_sdk.source.checkout_root", lambda pkg=None: None)
    monkeypatch.setattr("aifluxx_sdk.source.bundled_root", lambda pkg=None: None)
    dest = tmp_path / "out"
    result = runner.invoke(app, ["source", str(dest)])
    assert result.exit_code == 1
    assert "Reinstall" in _text(result)
    assert not dest.exists()


def test_source_help_lists_dest_and_force():
    result = runner.invoke(app, ["source", "--help"])
    text = _text(result)
    assert result.exit_code == 0, text
    assert "--force" in text
    assert "aifluxx-sdk" in text
    root = runner.invoke(app, ["--help"])
    assert "source" in _text(root)


def test_readme_documents_both_installs():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "git clone https://github.com/aifluxx/aifluxx-sdk\n" in readme
    assert "pip install -e ./aifluxx-sdk\n" in readme
    assert "pip install -e .\\aifluxx-sdk\n" in readme
    assert "source .venv/bin/activate\n" in readme
    assert "Activate.ps1" in readme
    assert "pip install git+https://github.com/aifluxx/aifluxx-sdk@latest\n" in readme
    assert "aifluxx source\n" in readme
    assert "aifluxx source my-sdk" in readme
    assert "--force" in readme
    assert "templates.py" in readme
    assert "starter_ui/" in readme
    assert "examples/" in readme
    assert "aifluxx-sdk @ git+" not in readme
