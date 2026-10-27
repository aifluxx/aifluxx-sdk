import json
from pathlib import Path

import pytest

from aifluxx_sdk.credentials import (
    DEFAULT_URL,
    DEV_URL,
    DEVELOPER_HOSTS,
    Credentials,
    credentials_path,
    dev_key_on_prod_host,
    load_credentials,
    resolve_api_target,
    resolve_api_url,
    save_credentials,
)
from aifluxx_sdk.exceptions import AuthError
from aifluxx_sdk.lockfile import AgentLock, load_lock, save_lock


def _clear_host_env(monkeypatch, tmp_path: Path | None = None) -> None:
    monkeypatch.delenv("AIFLUXX_API_URL", raising=False)
    monkeypatch.delenv("AIFLUXX_PLATFORM", raising=False)
    monkeypatch.delenv("AIFLUXX_ENV", raising=False)
    if tmp_path is None:
        monkeypatch.delenv("AIFLUXX_CONFIG", raising=False)
    else:
        monkeypatch.setenv("AIFLUXX_CONFIG", str(tmp_path / "missing-config.json"))


def test_default_url_is_za_prod(tmp_path: Path, monkeypatch):
    _clear_host_env(monkeypatch, tmp_path)
    assert DEFAULT_URL == "https://developer.aifluxx.co.za"
    assert DEV_URL == "https://dev.developer.aifluxx.co.za"
    assert resolve_api_url() == DEFAULT_URL
    assert DEVELOPER_HOSTS[("za", "prod")] == DEFAULT_URL
    assert DEVELOPER_HOSTS[("za", "dev")] == DEV_URL
    assert DEVELOPER_HOSTS[("truest", "prod")] == "https://developer.truest.ae"
    assert DEVELOPER_HOSTS[("truest", "dev")] == "https://dev.developer.truest.ae"


def test_platform_and_env_map(tmp_path: Path, monkeypatch):
    _clear_host_env(monkeypatch, tmp_path)
    assert resolve_api_url(platform="za") == DEFAULT_URL
    assert resolve_api_url(platform="aifluxx") == DEFAULT_URL
    assert resolve_api_url(platform="ZA", env="dev") == DEV_URL
    assert resolve_api_url(platform="aifluxx", env="dev") == DEV_URL
    assert resolve_api_url(platform="truest") == "https://developer.truest.ae"
    assert resolve_api_url(platform="truest", env="dev") == "https://dev.developer.truest.ae"
    assert resolve_api_url(platform="truest", env="prod") == "https://developer.truest.ae"
    assert resolve_api_url(env="dev") == DEV_URL
    target = resolve_api_target(platform="dev")
    assert target.url == DEV_URL
    assert target.deprecated_dev
    assert resolve_api_url(platform="dev", env="dev") == DEV_URL
    with pytest.raises(AuthError, match="deprecated"):
        resolve_api_url(platform="dev", env="prod")
    with pytest.raises(AuthError, match="Unknown platform"):
        resolve_api_url(platform="nope")
    with pytest.raises(AuthError, match="Unknown env"):
        resolve_api_url(env="stage")


def test_platform_and_url_precedence(tmp_path: Path, monkeypatch):
    _clear_host_env(monkeypatch, tmp_path)
    monkeypatch.setenv("AIFLUXX_API_URL", "https://api.example/from-env/")
    assert resolve_api_url() == "https://api.example/from-env"
    assert resolve_api_url(platform="aifluxx") == DEFAULT_URL
    assert resolve_api_url(platform="dev") == DEV_URL
    assert resolve_api_url(url="https://api.example/root/", platform="dev") == "https://api.example/root"
    monkeypatch.setenv("AIFLUXX_PLATFORM", "truest")
    monkeypatch.setenv("AIFLUXX_ENV", "dev")
    assert resolve_api_url() == "https://dev.developer.truest.ae"
    assert resolve_api_url(url="https://api.example/root/") == "https://api.example/root"
    assert resolve_api_url(platform="za") == DEV_URL
    assert resolve_api_url(platform="za", env="prod") == DEFAULT_URL
    assert dev_key_on_prod_host("afx_dev_k", DEFAULT_URL)
    assert dev_key_on_prod_host("afx_dev_k", "https://api.aifluxx.co.za.")
    assert dev_key_on_prod_host("afx_dev_k", "https://API.AIFLUXX.CO.ZA./api")
    assert dev_key_on_prod_host("afx_dev_k", "https://developer.aifluxx.co.za./api")
    assert dev_key_on_prod_host("afx_dev_k", "https://developer.truest.ae")
    assert dev_key_on_prod_host("afx_dev_k", "https://developer.truest.ae.")
    assert not dev_key_on_prod_host("afx_dev_k", DEV_URL)
    assert not dev_key_on_prod_host("afx_dev_k", "https://dev.developer.aifluxx.co.za.")
    assert not dev_key_on_prod_host("afx_dev_k", "https://dev.developer.truest.ae")
    assert not dev_key_on_prod_host("afx_dev_k", "https://dev.aifluxx.co.za")
    assert not dev_key_on_prod_host("afx_dev_k", "https://api.example")
    assert not dev_key_on_prod_host("afx_live_k", DEFAULT_URL)


def test_config_file_is_the_default_under_env_and_flags(tmp_path: Path, monkeypatch):
    _clear_host_env(monkeypatch, tmp_path)
    config = tmp_path / "config.json"
    config.write_text('{"platform": "truest", "env": "dev"}\n', encoding="utf-8")
    monkeypatch.setenv("AIFLUXX_CONFIG", str(config))
    assert resolve_api_url() == "https://dev.developer.truest.ae"
    monkeypatch.setenv("AIFLUXX_ENV", "prod")
    assert resolve_api_url() == "https://developer.truest.ae"
    assert resolve_api_url(platform="za") == DEFAULT_URL
    monkeypatch.setenv("AIFLUXX_API_URL", "https://api.example/from-env")
    assert resolve_api_url() == "https://developer.truest.ae"
    monkeypatch.delenv("AIFLUXX_ENV", raising=False)
    monkeypatch.delenv("AIFLUXX_PLATFORM", raising=False)
    assert resolve_api_url() == "https://api.example/from-env"


def test_default_store_is_aifluxx_home(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.delenv("AIFLUXX_CREDENTIALS", raising=False)
    monkeypatch.setattr("aifluxx_sdk.credentials.Path.home", lambda: home)
    assert credentials_path() == home / ".aifluxx" / "credentials"


def test_aifluxx_credentials_override_wins(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(tmp_path / "new"))
    assert credentials_path() == tmp_path / "new"


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
    monkeypatch.delenv("AIFLUXX_PLATFORM", raising=False)
    monkeypatch.delenv("AIFLUXX_ENV", raising=False)
    monkeypatch.delenv("AIFLUXX_API_URL", raising=False)
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(tmp_path / "missing" / "credentials"))
    with pytest.raises(AuthError, match=r"Not logged in.*developer\.aifluxx\.co\.za/signup \(accounts need approval\)"):
        load_credentials()
    text = ""
    try:
        load_credentials()
    except AuthError as exc:
        text = str(exc)
    assert "truest.ae" not in text


def test_not_logged_in_on_truest_points_at_truest(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("AIFLUXX_PLATFORM", "truest")
    monkeypatch.delenv("AIFLUXX_ENV", raising=False)
    monkeypatch.delenv("AIFLUXX_API_URL", raising=False)
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(tmp_path / "missing" / "credentials"))
    with pytest.raises(AuthError, match=r"developer\.truest\.ae/signup \(accounts need approval\)") as caught:
        load_credentials()
    assert "aifluxx.co.za" not in str(caught.value)
