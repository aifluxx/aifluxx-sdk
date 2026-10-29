import json
import os
from pathlib import Path

import pytest

from aifluxx_sdk.credentials import (
    DEFAULT_URL,
    DEV_URL,
    PLATFORMS,
    Credentials,
    credentials_path,
    load_credentials,
    resolve_api_url,
    save_credentials,
    _windows_dacl_is_current_user_only,
)
from aifluxx_sdk.exceptions import AuthError
from aifluxx_sdk.lockfile import AgentLock, load_lock, save_lock


def test_default_url_is_aifluxx(monkeypatch):
    monkeypatch.delenv("AIFLUXX_API_URL", raising=False)
    assert DEFAULT_URL == "https://api.aifluxx.co.za"
    assert resolve_api_url() == DEFAULT_URL
    assert set(PLATFORMS) == {"aifluxx", "dev"}
    assert PLATFORMS["aifluxx"] == DEFAULT_URL
    assert PLATFORMS["dev"] == DEV_URL


def test_platform_and_url_precedence(monkeypatch):
    monkeypatch.setenv("AIFLUXX_API_URL", "https://api.example/from-env/")
    assert resolve_api_url() == "https://api.example/from-env"
    assert resolve_api_url(platform="aifluxx") == DEFAULT_URL
    assert resolve_api_url(platform="dev") == DEV_URL
    assert resolve_api_url(url="https://api.example/root/", platform="dev") == "https://api.example/root"
    with pytest.raises(AuthError, match="Unknown platform"):
        resolve_api_url(platform="nope")


def test_default_store_is_aifluxx_home(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.delenv("AIFLUXX_CREDENTIALS", raising=False)
    monkeypatch.setattr("aifluxx_sdk.credentials.Path.home", lambda: home)
    assert credentials_path() == home / ".aifluxx" / "credentials"


def test_aifluxx_credentials_override_wins(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(tmp_path / "new"))
    assert credentials_path() == tmp_path / "new"


@pytest.mark.skipif(os.name == "nt", reason="Windows locks the key with an ACL, not chmod.")
def test_chmod_0600_failure_raises_and_removes_key(tmp_path: Path, monkeypatch):
    store = tmp_path / "locked" / "credentials"
    real_chmod = Path.chmod

    def chmod(self: Path, mode: int) -> None:
        if mode == 0o600:
            raise OSError("operation not permitted")
        real_chmod(self, mode)

    monkeypatch.setattr(Path, "chmod", chmod)
    with pytest.raises(AuthError, match="0600"):
        save_credentials(Credentials(url=DEFAULT_URL, api_key="afx_dev_secret"), store)
    assert not store.exists()


@pytest.mark.skipif(os.name == "nt", reason="Windows locks the key with an ACL, not chmod.")
def test_chmod_0600_that_does_not_stick_raises(tmp_path: Path, monkeypatch):
    store = tmp_path / "credentials"
    real_chmod = Path.chmod

    def chmod(self: Path, mode: int) -> None:
        if mode == 0o600:
            real_chmod(self, 0o644)
            return
        real_chmod(self, mode)

    monkeypatch.setattr(Path, "chmod", chmod)
    with pytest.raises(AuthError, match="did not stick"):
        save_credentials(Credentials(url=DEFAULT_URL, api_key="afx_dev_secret"), store)
    assert not store.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL lockdown.")
def test_windows_save_limits_the_key_to_the_current_user(tmp_path: Path):
    store = tmp_path / "locked" / "credentials"
    save_credentials(Credentials(url=DEFAULT_URL, api_key="afx_dev_secret"), store)
    assert store.is_file()
    assert _windows_dacl_is_current_user_only(store)
    assert _windows_dacl_is_current_user_only(store.parent)
    assert "afx_dev_secret" in store.read_text(encoding="utf-8")


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL lockdown.")
def test_windows_acl_failure_removes_the_key(tmp_path: Path, monkeypatch):
    def denied(path: Path, *, directory: bool) -> None:
        raise OSError("access denied")

    monkeypatch.setattr("aifluxx_sdk.credentials._restrict_to_current_user", denied)
    store = tmp_path / "locked" / "credentials"
    with pytest.raises(AuthError, match="lock down"):
        save_credentials(Credentials(url=DEFAULT_URL, api_key="afx_dev_secret"), store)
    assert not store.exists()


def test_load_strips_trailing_slash(tmp_path: Path):
    store = tmp_path / "credentials"
    store.write_text(
        json.dumps({"url": "https://api.example/root/", "api_key": "afx_dev_x"}) + "\n",
        encoding="utf-8",
    )
    creds = load_credentials(store)
    assert creds.url == "https://api.example/root"


def test_lock_round_trip(tmp_path: Path):
    save_lock(tmp_path, AgentLock(id="1", slug="board-pack", last_pushed_version="0.1.0", version_id=None))
    loaded = load_lock(tmp_path)
    assert loaded is not None
    assert loaded.slug == "board-pack"
    assert (tmp_path / ".aifluxx" / "agent.lock").is_file()
    save_lock(tmp_path, AgentLock(id="1", slug="board-pack", last_pushed_version="0.2.0"))
    assert json.loads((tmp_path / ".aifluxx" / "agent.lock").read_text(encoding="utf-8"))["last_pushed_version"] == "0.2.0"
    assert load_lock(tmp_path).last_pushed_version == "0.2.0"


def test_not_logged_in_points_to_signup(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(tmp_path / "missing" / "credentials"))
    with pytest.raises(AuthError, match=r"Not logged in.*developer\.aifluxx\.co\.za/signup \(accounts need approval\)"):
        load_credentials()
