import json
from pathlib import Path

import pytest

from aifluxx_sdk.credentials import (
    DEFAULT_URL,
    DEV_URL,
    PLATFORMS,
    TRUEST_DEV_URL,
    Credentials,
    credentials_path,
    dev_key_on_prod_host,
    load_credentials,
    resolve_api_url,
    save_credentials,
)
from aifluxx_sdk.exceptions import AuthError
from aifluxx_sdk.lockfile import AgentLock, load_lock, save_lock


def test_default_url_is_aifluxx(monkeypatch):
    monkeypatch.delenv("AIFLUXX_API_URL", raising=False)
    assert DEFAULT_URL == "https://api.aifluxx.co.za"
    assert resolve_api_url() == DEFAULT_URL
    assert "truest.biz" not in DEFAULT_URL
    for url in PLATFORMS.values():
        assert "truest.biz" not in url


def test_platform_and_url_precedence(monkeypatch):
    monkeypatch.setenv("AIFLUXX_API_URL", "https://api.truest.biz")
    assert resolve_api_url() == "https://api.aifluxx.co.za"
    assert resolve_api_url(platform="truest") == "https://api.truest.ae"
    assert resolve_api_url(platform="dev") == DEV_URL
    assert resolve_api_url(platform="truest-dev") == TRUEST_DEV_URL
    assert resolve_api_url(url="https://api.example/root/", platform="truest") == "https://api.example/root"
    with pytest.raises(AuthError, match="Unknown platform"):
        resolve_api_url(platform="nope")
    assert dev_key_on_prod_host("afx_dev_k", DEFAULT_URL)
    assert dev_key_on_prod_host("afx_dev_k", "https://api.truest.ae")
    assert dev_key_on_prod_host("afx_dev_k", "https://developer.aifluxx.co.za/api")
    assert not dev_key_on_prod_host("afx_dev_k", DEV_URL)
    assert not dev_key_on_prod_host("afx_dev_k", TRUEST_DEV_URL)
    assert not dev_key_on_prod_host("afx_dev_k", "https://dev.aifluxx.co.za")
    assert not dev_key_on_prod_host("afx_live_k", DEFAULT_URL)


def test_default_store_is_aifluxx_home(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.delenv("AIFLUXX_CREDENTIALS", raising=False)
    monkeypatch.delenv("TRUEST_CREDENTIALS", raising=False)
    monkeypatch.setattr("aifluxx_sdk.credentials.Path.home", lambda: home)
    assert credentials_path() == home / ".aifluxx" / "credentials"


def test_aifluxx_credentials_override_wins(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(tmp_path / "new"))
    monkeypatch.setenv("TRUEST_CREDENTIALS", str(tmp_path / "old"))
    assert credentials_path() == tmp_path / "new"


def test_legacy_credentials_env(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("AIFLUXX_CREDENTIALS", raising=False)
    monkeypatch.setenv("TRUEST_CREDENTIALS", str(tmp_path / "legacy"))
    with pytest.warns(DeprecationWarning, match="AIFLUXX_CREDENTIALS"):
        assert credentials_path() == tmp_path / "legacy"


def test_migrates_legacy_home(tmp_path: Path, monkeypatch, capsys):
    home = tmp_path / "home"
    legacy = home / ".truest"
    legacy.mkdir(parents=True)
    (legacy / "credentials").write_text(
        json.dumps({"url": "https://api.truest.biz", "api_key": "afx_dev_legacy"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("AIFLUXX_CREDENTIALS", raising=False)
    monkeypatch.delenv("TRUEST_CREDENTIALS", raising=False)
    monkeypatch.setattr("aifluxx_sdk.credentials.Path.home", lambda: home)
    creds = load_credentials()
    assert creds.url == "https://api.aifluxx.co.za"
    assert creds.api_key == "afx_dev_legacy"
    stored = json.loads((home / ".aifluxx" / "credentials").read_text(encoding="utf-8"))
    assert stored["url"] == "https://api.aifluxx.co.za"
    assert "Moved credentials" in capsys.readouterr().err
    assert not (legacy / "credentials").exists()
    mode = (home / ".aifluxx" / "credentials").stat().st_mode & 0o777
    assert mode == 0o600


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


def test_load_rewrites_retired_host(tmp_path: Path):
    store = tmp_path / "credentials"
    store.write_text(
        json.dumps({"url": "https://api.truest.biz/", "api_key": "afx_dev_x"}) + "\n",
        encoding="utf-8",
    )
    creds = load_credentials(store)
    assert creds.url == "https://api.aifluxx.co.za"
    assert json.loads(store.read_text(encoding="utf-8"))["url"] == "https://api.aifluxx.co.za"


def test_lock_reads_legacy_and_writes_aifluxx(tmp_path: Path):
    legacy = tmp_path / ".truest"
    legacy.mkdir()
    (legacy / "agent.lock").write_text(
        json.dumps({"id": "1", "slug": "board-pack", "last_pushed_version": "0.1.0"}) + "\n",
        encoding="utf-8",
    )
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
    monkeypatch.delenv("TRUEST_CREDENTIALS", raising=False)
    with pytest.raises(AuthError, match=r"Not logged in.*developer\.aifluxx\.co\.za/signup \(accounts need approval\)"):
        load_credentials()
