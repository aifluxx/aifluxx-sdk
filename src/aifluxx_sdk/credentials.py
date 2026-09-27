"""Machine-local key store. Same file from every IDE."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from aifluxx_sdk.exceptions import AuthError

DEFAULT_URL = "https://api.truest.biz"


def credentials_path() -> Path:
    override = os.environ.get("TRUEST_CREDENTIALS")
    if override:
        return Path(override)
    return Path.home() / ".truest" / "credentials"


@dataclass(frozen=True)
class Credentials:
    url: str
    api_key: str


def load_credentials(path: Path | None = None) -> Credentials:
    store = path or credentials_path()
    if not store.is_file():
        raise AuthError("Not logged in. Run `truest login` and paste the afx_dev_ key from Home.")
    try:
        data = json.loads(store.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AuthError(f"Could not read {store}.") from exc
    url = str(data.get("url") or "").strip().rstrip("/")
    api_key = str(data.get("api_key") or "").strip()
    if not url or not api_key:
        raise AuthError("Credentials file is missing url or api_key. Run `truest login`.")
    return Credentials(url=url, api_key=api_key)


def save_credentials(creds: Credentials, path: Path | None = None) -> Path:
    store = path or credentials_path()
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(
        json.dumps({"url": creds.url.rstrip("/"), "api_key": creds.api_key}, indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        store.chmod(0o600)
    except OSError:
        pass
    return store
