"""Pinned checkout of the starter UI.

``aifluxx init`` is the hook that fetches it. Importing this package does not,
and there is no pip install hook: a clone needs git and a network, and it
writes outside the install location.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from aifluxx_sdk.exceptions import AifluxxError

# No tag is published on the starter repository. This is the commit
# "AIFluxx Starter Console v0.1" (main, 2026-10-26).
UI_STARTER_REPO = "https://github.com/aifluxx/aifluxx-starter-ui.git"
UI_STARTER_REF = "cd86e3468875968a6e63b1d2e4835368777fdf3b"
UI_STARTER_DIR_NAME = "aifluxx-starter-ui"
UI_STARTER_OPT_OUT_ENV = "AIFLUXX_NO_UI_STARTER"

_OPT_OUT_VALUES = frozenset({"1", "true", "yes", "on"})


def ui_starter_opt_out(skip: bool = False) -> bool:
    """True when the flag is set or ``AIFLUXX_NO_UI_STARTER`` is truthy.

    ``1``, ``true``, ``yes``, and ``on`` opt out. ``0`` and an empty value do not.
    """
    if skip:
        return True
    value = os.environ.get(UI_STARTER_OPT_OUT_ENV, "").strip().lower()
    return value in _OPT_OUT_VALUES


def ui_starter_destination(cwd: Path | None = None) -> Path:
    """``aifluxx-starter-ui`` beside the working directory (its parent)."""
    root = Path.cwd() if cwd is None else Path(cwd)
    return root.resolve().parent / UI_STARTER_DIR_NAME


def _exists(dest: Path) -> bool:
    """True for a file, directory, or symlink. Does not follow a broken link."""
    return os.path.lexists(dest)


def manual_fallback_commands(dest: Path) -> str:
    """Commands that check out the same pinned commit."""
    folder = shlex.quote(os.fspath(dest))
    repo = shlex.quote(UI_STARTER_REPO)
    ref = shlex.quote(UI_STARTER_REF)
    return f"git clone {repo} {folder}\ngit -C {folder} checkout --detach {ref}"


def _unavailable(dest: Path, detail: str) -> AifluxxError:
    return AifluxxError(
        f"Could not fetch the starter UI into {dest}. {detail}\n"
        "Nothing was written. Install it yourself, then run init again:\n"
        f"{manual_fallback_commands(dest)}\n"
        f"To skip the starter, pass --no-ui-starter or set {UI_STARTER_OPT_OUT_ENV}=1."
    )


def _run_git(args: list[str], dest: Path) -> None:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        completed = subprocess.run(
            ["git", *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
            env=env,
        )
    except FileNotFoundError:
        raise _unavailable(dest, "git is not installed or not on PATH.") from None
    except subprocess.TimeoutExpired:
        raise _unavailable(dest, "git timed out. The network may be unavailable.") from None
    if completed.returncode == 0:
        return
    detail = (completed.stderr or completed.stdout or "git failed").strip()
    if len(detail) > 400:
        detail = detail[-400:]
    raise _unavailable(dest, f"git failed ({detail}). The network may be unavailable.")


def fetch_ui_starter(dest: Path) -> str:
    """Clone the pinned starter into ``dest``.

    Returns ``skipped`` when ``dest`` already exists. An existing file,
    directory, or symlink is left unchanged. Returns ``fetched`` after a
    checkout of ``UI_STARTER_REF``.
    """
    if _exists(dest):
        return "skipped"
    if shutil.which("git") is None:
        raise _unavailable(dest, "git is not installed or not on PATH.")
    parent = dest.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        staging_root = Path(tempfile.mkdtemp(prefix=".aifluxx-ui-starter-", dir=parent))
    except OSError as exc:
        raise _unavailable(dest, f"Could not prepare a temporary directory ({exc}).") from None
    staging = staging_root / UI_STARTER_DIR_NAME
    try:
        _run_git(["clone", UI_STARTER_REPO, os.fspath(staging)], dest)
        if not staging.is_dir():
            raise _unavailable(dest, "git clone did not create the starter directory.")
        _run_git(["-C", os.fspath(staging), "checkout", "--detach", UI_STARTER_REF], dest)
        if _exists(dest):
            return "skipped"
        try:
            staging.rename(dest)
        except OSError as exc:
            raise _unavailable(dest, f"Could not move the checkout into place ({exc}).") from None
    finally:
        if staging_root.exists():
            shutil.rmtree(staging_root, ignore_errors=True)
    return "fetched"


def ensure_ui_starter(*, skip: bool = False, cwd: Path | None = None) -> str | None:
    """Fetch the pinned starter beside ``cwd`` unless opted out.

    Returns a note for the CLI, or None when the flag or env var skips the fetch.
    """
    if ui_starter_opt_out(skip):
        return None
    dest = ui_starter_destination(cwd)
    status = fetch_ui_starter(dest)
    if status == "skipped":
        return f"Starter UI already at {dest}. Left it unchanged."
    return f"Fetched starter UI at {dest} pinned to {UI_STARTER_REF}."
