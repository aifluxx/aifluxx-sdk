"""Test defaults that keep the starter fetch off the network."""
from __future__ import annotations

import subprocess

import pytest


@pytest.fixture(autouse=True)
def _skip_ui_starter_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Opt out of the starter clone unless a test unsets the env and mocks git.

    ``AIFLUXX_NO_UI_STARTER`` is not part of the CliRunner env dict, so a test
    can ``delenv`` it and still see the change inside ``invoke``.
    """
    monkeypatch.setenv("AIFLUXX_NO_UI_STARTER", "1")
    real_run = subprocess.run

    def guarded(args, **kwargs):  # type: ignore[no-untyped-def]
        if args and args[0] == "git" and any("aifluxx-starter-ui" in str(part) for part in args):
            raise AssertionError("refusing a real starter clone in tests; mock git")
        return real_run(args, **kwargs)

    monkeypatch.setattr("aifluxx_sdk.ui_starter.subprocess.run", guarded)
