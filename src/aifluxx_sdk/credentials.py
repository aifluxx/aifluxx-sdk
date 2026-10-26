"""Machine-local key store. Same file from every IDE."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from aifluxx_sdk.exceptions import AuthError

DEFAULT_URL = "https://api.aifluxx.co.za"
# ZA dev developer API. The dev portal calls /api/dev on its own origin.
DEV_URL = "https://dev.developer.aifluxx.co.za"

PLATFORMS = {
    "aifluxx": DEFAULT_URL,
    "dev": DEV_URL,
}

# Production API and developer-portal hosts. afx_dev_ keys issued on the dev
# portal do not belong on these.
PROD_HOSTS = frozenset(
    {
        "api.aifluxx.co.za",
        "developer.aifluxx.co.za",
    }
)

_CONFIG_DIR = ".aifluxx"


def normalize_api_url(url: str) -> str:
    """Return a canonical API root with no trailing slash."""
    return (url or "").strip().rstrip("/")


def _api_hostname(url: str) -> str:
    """Hostname of ``url``, lowercased, with a trailing DNS-root dot removed."""
    return (urlparse(url or "").hostname or "").lower().rstrip(".")


def is_prod_api_url(url: str) -> bool:
    """True when ``url`` is a production API or developer-portal host."""
    return _api_hostname(url) in PROD_HOSTS


def dev_key_on_prod_host(api_key: str, url: str) -> bool:
    """True when an ``afx_dev_`` key is aimed at a production host.

    ``api.aifluxx.co.za.`` is the same host as ``api.aifluxx.co.za``.
    """
    return (api_key or "").startswith("afx_dev_") and _api_hostname(url) in PROD_HOSTS


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
    return _default_store()


def _default_store() -> Path:
    return Path.home() / _CONFIG_DIR / "credentials"


@dataclass(frozen=True)
class Credentials:
    url: str
    api_key: str


def load_credentials(path: Path | None = None) -> Credentials:
    store = path or credentials_path()
    if not store.is_file():
        raise AuthError(
            "Not logged in. Run `aifluxx login` and paste the afx_dev_ key from Home. "
            "Sign up at https://developer.aifluxx.co.za/signup (accounts need approval)."
        )
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
