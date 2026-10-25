"""Machine-local key store. Same file from every IDE."""
from __future__ import annotations

import json
import os
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path

from aifluxx_sdk.exceptions import AuthError

DEFAULT_URL = "https://api.aifluxx.co.za"
TRUEST_URL = "https://api.truest.ae"
RETIRED_HOST = "api.truest.biz"

PLATFORMS = {
    "aifluxx": DEFAULT_URL,
    "truest": TRUEST_URL,
}

_LEGACY_DIR = ".truest"
_CONFIG_DIR = ".aifluxx"


def normalize_api_url(url: str) -> str:
    """Return a canonical API root. `api.truest.biz` is rewritten to the AIfluxx default."""
    cleaned = (url or "").strip().rstrip("/")
    if not cleaned:
        return cleaned
    if "://" not in cleaned:
        return cleaned
    scheme, rest = cleaned.split("://", 1)
    host, sep, tail = rest.partition("/")
    hostname, colon, port = host.partition(":")
    if hostname.lower() == RETIRED_HOST:
        host = "api.aifluxx.co.za" + (colon + port if colon else "")
        rest = host + (sep + tail if sep else "")
        cleaned = f"{scheme}://{rest}"
    return cleaned.rstrip("/")


def resolve_api_url(*, url: str | None = None, platform: str | None = None) -> str:
    """Pick an API root: `--url`, then `--platform`, then `AIFLUXX_API_URL`, then the default."""
    if url is not None and url.strip():
        return normalize_api_url(url)
    if platform is not None and platform.strip():
        key = platform.strip().lower()
        if key not in PLATFORMS:
            known = ", ".join(sorted(PLATFORMS))
            raise AuthError(f"Unknown platform {platform!r}. Use: {known}.")
        return PLATFORMS[key]
    env = os.environ.get("AIFLUXX_API_URL", "").strip()
    if env:
        return normalize_api_url(env)
    return DEFAULT_URL


def credentials_path() -> Path:
    override = os.environ.get("AIFLUXX_CREDENTIALS", "").strip()
    if override:
        return Path(override)
    legacy = os.environ.get("TRUEST_CREDENTIALS", "").strip()
    if legacy:
        warnings.warn(
            "TRUEST_CREDENTIALS is deprecated and will be removed. Set AIFLUXX_CREDENTIALS.",
            DeprecationWarning,
            stacklevel=2,
        )
        return Path(legacy)
    return _default_store()


def _default_store() -> Path:
    return Path.home() / _CONFIG_DIR / "credentials"


def _legacy_store() -> Path:
    return Path.home() / _LEGACY_DIR / "credentials"


@dataclass(frozen=True)
class Credentials:
    url: str
    api_key: str


def load_credentials(path: Path | None = None) -> Credentials:
    store = path or credentials_path()
    if path is None and store == _default_store() and not store.is_file():
        legacy = _legacy_store()
        if legacy.is_file():
            _migrate(legacy, store)
    if not store.is_file():
        raise AuthError("Not logged in. Run `aifluxx login` and paste the afx_dev_ key from Home.")
    try:
        data = json.loads(store.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AuthError(f"Could not read {store}.") from exc
    raw_url = str(data.get("url") or "").strip()
    api_key = str(data.get("api_key") or "").strip()
    if not raw_url or not api_key:
        raise AuthError("Credentials file is missing url or api_key. Run `aifluxx login`.")
    url = normalize_api_url(raw_url)
    creds = Credentials(url=url, api_key=api_key)
    if url != raw_url.rstrip("/"):
        try:
            save_credentials(creds, store)
        except OSError:
            pass
    return creds


def save_credentials(creds: Credentials, path: Path | None = None) -> Path:
    store = path or credentials_path()
    store.parent.mkdir(parents=True, exist_ok=True)
    _harden(store.parent, directory=True)
    store.write_text(
        json.dumps({"url": normalize_api_url(creds.url), "api_key": creds.api_key}, indent=2) + "\n",
        encoding="utf-8",
    )
    _harden(store, directory=False)
    return store


def _migrate(legacy: Path, dest: Path) -> None:
    try:
        data = json.loads(legacy.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthError(f"Could not migrate {legacy} to {dest}.") from exc
    if not isinstance(data, dict):
        raise AuthError(f"Could not migrate {legacy} to {dest}.")
    url = normalize_api_url(str(data.get("url") or ""))
    api_key = str(data.get("api_key") or "").strip()
    if not url or not api_key:
        raise AuthError(f"Could not migrate {legacy}: missing url or api_key.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    _harden(dest.parent, directory=True)
    dest.write_text(json.dumps({"url": url, "api_key": api_key}, indent=2) + "\n", encoding="utf-8")
    _harden(dest, directory=False)
    try:
        legacy.unlink()
    except OSError as exc:
        raise AuthError(f"Moved credentials to {dest} but could not remove {legacy}: {exc}.") from exc
    print(f"Moved credentials from {legacy} to {dest}.", file=sys.stderr)


def _harden(path: Path, *, directory: bool) -> None:
    mode = 0o700 if directory else 0o600
    try:
        path.chmod(mode)
        actual = path.stat().st_mode & 0o777
    except OSError as exc:
        _drop_unlocked_secret(path, directory)
        raise AuthError(
            f"Could not set mode {mode:04o} on {path}: {exc}. "
            "Refusing to keep an API key this process cannot lock down."
        ) from exc
    if actual != mode:
        _drop_unlocked_secret(path, directory)
        raise AuthError(
            f"chmod {mode:04o} on {path} did not stick (mode is {actual:04o}). "
            "Refusing to keep an API key this process cannot lock down."
        )


def _drop_unlocked_secret(path: Path, directory: bool) -> None:
    if directory:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
