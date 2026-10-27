"""Pinned starter UI fetch. Git is mocked; nothing here clones the network."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aifluxx_sdk.cli import app
from aifluxx_sdk.exceptions import AifluxxError
from aifluxx_sdk.ui_starter import (
    UI_STARTER_DIR_NAME,
    UI_STARTER_OPT_OUT_ENV,
    UI_STARTER_REF,
    UI_STARTER_REPO,
    ensure_ui_starter,
    fetch_ui_starter,
    manual_fallback_commands,
    ui_starter_destination,
    ui_starter_opt_out,
)
from tests.test_cli import _HELP_ENV, _text

runner = CliRunner(env=_HELP_ENV)


def _work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    return work


def _git_ok(calls: list[list[str]]):
    def run(args, **kwargs):
        calls.append(list(args))
        if args[1] == "clone":
            Path(args[-1]).mkdir(parents=True)
            (Path(args[-1]) / "README.md").write_text("pinned\n", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, "", "")

    return run


def test_destination_is_beside_the_working_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _work(tmp_path, monkeypatch)
    assert ui_starter_destination() == (tmp_path / UI_STARTER_DIR_NAME).resolve()


def test_opt_out_flag_and_env_skip_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _work(tmp_path, monkeypatch)
    monkeypatch.delenv(UI_STARTER_OPT_OUT_ENV, raising=False)

    def explode(*_args, **_kwargs):
        raise AssertionError("git should not run")

    monkeypatch.setattr("aifluxx_sdk.ui_starter.subprocess.run", explode)
    assert ui_starter_opt_out(True) is True
    assert ensure_ui_starter(skip=True) is None
    for value in ("1", "true", "YES", "on"):
        monkeypatch.setenv(UI_STARTER_OPT_OUT_ENV, value)
        assert ui_starter_opt_out() is True
        assert ensure_ui_starter() is None
    assert not (tmp_path / UI_STARTER_DIR_NAME).exists()


def test_env_zero_does_not_opt_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _work(tmp_path, monkeypatch)
    monkeypatch.setenv(UI_STARTER_OPT_OUT_ENV, "0")
    calls: list[list[str]] = []
    monkeypatch.setattr("aifluxx_sdk.ui_starter.subprocess.run", _git_ok(calls))
    note = ensure_ui_starter()
    assert note is not None
    assert UI_STARTER_REF in note
    assert calls


def test_existing_folder_is_not_overwritten(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(UI_STARTER_OPT_OUT_ENV, raising=False)
    dest = tmp_path / UI_STARTER_DIR_NAME
    dest.mkdir()
    (dest / "keep.txt").write_text("mine\n", encoding="utf-8")

    def explode(*_args, **_kwargs):
        raise AssertionError("git should not run")

    monkeypatch.setattr("aifluxx_sdk.ui_starter.subprocess.run", explode)
    assert fetch_ui_starter(dest) == "skipped"
    assert (dest / "keep.txt").read_text(encoding="utf-8") == "mine\n"

    empty = tmp_path / "empty-starter"
    empty.mkdir()
    assert fetch_ui_starter(empty) == "skipped"
    assert list(empty.iterdir()) == []

    link_target = tmp_path / "elsewhere"
    link_target.mkdir()
    link = tmp_path / "linked-starter"
    link.symlink_to(link_target)
    assert fetch_ui_starter(link) == "skipped"
    assert list(link_target.iterdir()) == []


def test_missing_git_includes_manual_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dest = tmp_path / UI_STARTER_DIR_NAME
    monkeypatch.setattr("aifluxx_sdk.ui_starter.shutil.which", lambda _name: None)
    with pytest.raises(AifluxxError) as caught:
        fetch_ui_starter(dest)
    message = str(caught.value)
    assert "not on PATH" in message
    assert manual_fallback_commands(dest) in message
    assert UI_STARTER_REPO in message
    assert UI_STARTER_REF in message
    assert "checkout --detach" in message
    assert "--no-ui-starter" in message
    assert not dest.exists()
    assert not list(tmp_path.glob(".aifluxx-ui-starter-*"))


def test_git_failure_cleans_up_and_names_the_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dest = tmp_path / UI_STARTER_DIR_NAME

    def fail(args, **kwargs):
        if args[1] == "clone":
            Path(args[-1]).mkdir(parents=True)
            (Path(args[-1]) / "partial.txt").write_text("nope\n", encoding="utf-8")
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(
            args,
            128,
            "",
            "fatal: unable to access 'https://github.com/aifluxx/aifluxx-starter-ui.git/': Could not resolve host",
        )

    monkeypatch.setattr("aifluxx_sdk.ui_starter.subprocess.run", fail)
    with pytest.raises(AifluxxError) as caught:
        fetch_ui_starter(dest)
    message = str(caught.value)
    assert "Could not resolve host" in message
    assert "network may be unavailable" in message
    assert manual_fallback_commands(dest) in message
    assert "Nothing was written" in message
    assert not dest.exists()
    assert not list(tmp_path.glob(".aifluxx-ui-starter-*"))


def test_git_timeout_is_a_clear_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dest = tmp_path / UI_STARTER_DIR_NAME

    def slow(args, **kwargs):
        raise subprocess.TimeoutExpired(args, 180)

    monkeypatch.setattr("aifluxx_sdk.ui_starter.subprocess.run", slow)
    with pytest.raises(AifluxxError) as caught:
        fetch_ui_starter(dest)
    assert "timed out" in str(caught.value)
    assert UI_STARTER_REF in str(caught.value)
    assert not list(tmp_path.glob(".aifluxx-ui-starter-*"))


def test_fetch_clones_then_checks_out_the_pinned_ref(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dest = tmp_path / UI_STARTER_DIR_NAME
    calls: list[list[str]] = []
    monkeypatch.setattr("aifluxx_sdk.ui_starter.subprocess.run", _git_ok(calls))
    assert fetch_ui_starter(dest) == "fetched"
    assert calls[0][:3] == ["git", "clone", UI_STARTER_REPO]
    assert calls[1][0] == "git"
    assert calls[1][1] == "-C"
    assert calls[1][3:] == ["checkout", "--detach", UI_STARTER_REF]
    assert (dest / "README.md").read_text(encoding="utf-8") == "pinned\n"
    assert not list(tmp_path.glob(".aifluxx-ui-starter-*"))
    assert len(UI_STARTER_REF) == 40
    assert int(UI_STARTER_REF, 16)


def test_fetch_does_not_replace_a_folder_created_during_clone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dest = tmp_path / UI_STARTER_DIR_NAME

    def race(args, **kwargs):
        if args[1] == "clone":
            Path(args[-1]).mkdir(parents=True)
            return subprocess.CompletedProcess(args, 0, "", "")
        dest.mkdir()
        (dest / "keep.txt").write_text("already\n", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr("aifluxx_sdk.ui_starter.subprocess.run", race)
    assert fetch_ui_starter(dest) == "skipped"
    assert (dest / "keep.txt").read_text(encoding="utf-8") == "already\n"
    assert not list(tmp_path.glob(".aifluxx-ui-starter-*"))


def test_init_fetches_beside_the_working_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _work(tmp_path, monkeypatch)
    monkeypatch.delenv(UI_STARTER_OPT_OUT_ENV, raising=False)
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(tmp_path / "missing-credentials"))
    calls: list[list[str]] = []
    monkeypatch.setattr("aifluxx_sdk.ui_starter.subprocess.run", _git_ok(calls))
    result = runner.invoke(app, ["init", "my-agent"])
    text = _text(result)
    assert result.exit_code == 0, text
    assert (tmp_path / "work" / "my-agent" / "spec.yaml").is_file()
    assert (tmp_path / UI_STARTER_DIR_NAME / "README.md").is_file()
    assert UI_STARTER_REF in text
    assert "Fetched starter UI" in text
    assert calls[1][-1] == UI_STARTER_REF


def test_init_flag_and_env_skip_the_fetch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _work(tmp_path, monkeypatch)
    monkeypatch.delenv(UI_STARTER_OPT_OUT_ENV, raising=False)
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(tmp_path / "missing-credentials"))

    def explode(*_args, **_kwargs):
        raise AssertionError("git should not run")

    monkeypatch.setattr("aifluxx_sdk.ui_starter.subprocess.run", explode)
    flagged = runner.invoke(app, ["init", "flagged", "--no-ui-starter"])
    assert flagged.exit_code == 0, _text(flagged)
    assert "Fetched starter UI" not in _text(flagged)
    assert (tmp_path / "work" / "flagged" / "spec.yaml").is_file()

    monkeypatch.setenv(UI_STARTER_OPT_OUT_ENV, "1")
    from_env = runner.invoke(app, ["init", "from-env"])
    assert from_env.exit_code == 0, _text(from_env)
    assert not (tmp_path / UI_STARTER_DIR_NAME).exists()


def test_init_git_failure_writes_no_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _work(tmp_path, monkeypatch)
    monkeypatch.delenv(UI_STARTER_OPT_OUT_ENV, raising=False)

    def fail(args, **kwargs):
        return subprocess.CompletedProcess(args, 128, "", "fatal: unable to access: Network is unreachable")

    monkeypatch.setattr("aifluxx_sdk.ui_starter.subprocess.run", fail)
    result = runner.invoke(app, ["init", "offline-agent"])
    text = _text(result)
    assert result.exit_code == 1, text
    assert "Network is unreachable" in text
    assert "Nothing was written" in text
    assert UI_STARTER_REF in text
    assert "git clone" in text
    assert not (tmp_path / "work" / "offline-agent").exists()
    assert not (tmp_path / UI_STARTER_DIR_NAME).exists()


def test_list_and_missing_slug_do_not_fetch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _work(tmp_path, monkeypatch)
    monkeypatch.delenv(UI_STARTER_OPT_OUT_ENV, raising=False)

    def explode(*_args, **_kwargs):
        raise AssertionError("git should not run")

    monkeypatch.setattr("aifluxx_sdk.ui_starter.subprocess.run", explode)
    listed = runner.invoke(app, ["init", "--list"])
    assert listed.exit_code == 0, _text(listed)
    missing = runner.invoke(app, ["init", "--template", "finance"])
    assert missing.exit_code == 1
    assert "Usage:" in _text(missing)
    assert not (tmp_path / UI_STARTER_DIR_NAME).exists()


def test_second_init_leaves_an_existing_starter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _work(tmp_path, monkeypatch)
    monkeypatch.delenv(UI_STARTER_OPT_OUT_ENV, raising=False)
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(tmp_path / "missing-credentials"))
    calls: list[list[str]] = []
    monkeypatch.setattr("aifluxx_sdk.ui_starter.subprocess.run", _git_ok(calls))
    first = runner.invoke(app, ["init", "one"])
    assert first.exit_code == 0, _text(first)
    (tmp_path / UI_STARTER_DIR_NAME / "keep.txt").write_text("local\n", encoding="utf-8")

    def explode(*_args, **_kwargs):
        raise AssertionError("git should not run")

    monkeypatch.setattr("aifluxx_sdk.ui_starter.subprocess.run", explode)
    second = runner.invoke(app, ["init", "two"])
    text = _text(second)
    assert second.exit_code == 0, text
    assert "Left it unchanged" in text
    assert (tmp_path / UI_STARTER_DIR_NAME / "keep.txt").read_text(encoding="utf-8") == "local\n"
    assert (tmp_path / "work" / "two" / "spec.yaml").is_file()


def test_init_help_offers_opt_out_without_truest() -> None:
    text = _text(runner.invoke(app, ["init", "--help"]))
    assert "--no-ui-starter" in text
    assert "AIFLUXX_NO_UI_STARTER" in text
    assert "truest" not in text.lower()


def test_docs_name_the_pinned_ref_and_opt_out() -> None:
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    project = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert UI_STARTER_REF in readme
    assert "--no-ui-starter" in readme
    assert "AIFLUXX_NO_UI_STARTER" in readme
    assert "does not clone" in readme
    assert "beside the working directory" in readme
    assert "AIfluxx" not in readme
    assert UI_STARTER_REF in changelog
    assert "cmdclass" not in project
    assert project.count("aifluxx = ") == 1
    for name in ("ui-starter.md", "local-setup.md"):
        for path in root.rglob(name):
            text = path.read_text(encoding="utf-8")
            assert UI_STARTER_REF in text
            assert "AIFLUXX_NO_UI_STARTER" in text
