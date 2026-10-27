"""Machine-local key store. Same file from every IDE."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from aifluxx_sdk.exceptions import AuthError

# Developer API hosts. The portal calls /api/dev on its own origin.
# Mail and MCP stay on the public API host; that host is not a developer default.
PUBLIC_API_URL = "https://api.aifluxx.co.za"
DEFAULT_PLATFORM = "za"
DEFAULT_ENV = "prod"
# `aifluxx` is an alias of `za`. `dev` is the deprecated platform alias of ZA dev.
PLATFORM_ALIASES = {"aifluxx": "za"}
DEPRECATED_PLATFORM = "dev"
ENVS = ("dev", "prod")
DEVELOPER_HOSTS = {
    ("truest", "dev"): "https://dev.developer.truest.ae",
    ("truest", "prod"): "https://developer.truest.ae",
    ("za", "dev"): "https://dev.developer.aifluxx.co.za",
    ("za", "prod"): "https://developer.aifluxx.co.za",
}
DEFAULT_URL = DEVELOPER_HOSTS[(DEFAULT_PLATFORM, DEFAULT_ENV)]
DEV_URL = DEVELOPER_HOSTS[("za", "dev")]
SIGNUP_URLS = {
    "za": "https://developer.aifluxx.co.za/signup",
    "truest": "https://developer.truest.ae/signup",
}

# Production API and developer-portal hosts. afx_dev_ keys issued on a dev
# portal do not belong on these.
PROD_HOSTS = frozenset(
    {
        "api.aifluxx.co.za",
        "developer.aifluxx.co.za",
        "developer.truest.ae",
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


def _present(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def api_hostname(url: str) -> str:
    """Hostname of ``url``, lowercased, with a trailing DNS-root dot removed."""
    return _api_hostname(url)


def brand_of_url(url: str) -> str:
    """``truest`` or ``za`` for help and errors. Custom hosts use ``za``."""
    named = named_developer_env(url)
    if named is not None:
        return named[0]
    host = _api_hostname(url)
    if host == "truest.ae" or host.endswith(".truest.ae"):
        return "truest"
    return "za"


def named_developer_env(url: str) -> tuple[str, str] | None:
    """``(platform, env)`` when ``url`` is one of the four developer API roots."""
    normalized = normalize_api_url(url)
    for key, candidate in DEVELOPER_HOSTS.items():
        if candidate == normalized:
            return key
    return None


def dev_key_hint(url: str) -> tuple[str, str]:
    """How to aim an ``afx_dev_`` key at the dev host for this URL's brand.

    The other brand's host is not included.
    """
    if brand_of_url(url) == "truest":
        return ("--platform truest --env dev", DEVELOPER_HOSTS[("truest", "dev")])
    return ("--platform za --env dev", DEVELOPER_HOSTS[("za", "dev")])


def config_path() -> Path:
    override = os.environ.get("AIFLUXX_CONFIG", "").strip()
    if override:
        return Path(override)
    return Path.home() / _CONFIG_DIR / "config.json"


def load_host_config() -> tuple[str | None, str | None]:
    """Platform and env from the config file. ``(None, None)`` when it is absent."""
    path = config_path()
    if not path.is_file():
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthError(f"Could not read {path}.") from exc
    if not isinstance(data, dict):
        raise AuthError(f"Could not read {path}.")
    platform = data.get("platform")
    env = data.get("env")
    if platform is not None and not isinstance(platform, str):
        raise AuthError(f"Config {path} platform must be a string.")
    if env is not None and not isinstance(env, str):
        raise AuthError(f"Config {path} env must be a string.")
    return _present(platform if isinstance(platform, str) else None), _present(env if isinstance(env, str) else None)


def _parse_env(value: str) -> str:
    key = value.strip().lower()
    if key not in ENVS:
        raise AuthError(f"Unknown env {value!r}. Use: dev, prod.")
    return key


def _parse_platform(value: str) -> tuple[str, bool]:
    """Return ``(canonical platform, deprecated_dev)``."""
    key = value.strip().lower()
    if key == DEPRECATED_PLATFORM:
        return "za", True
    if key in PLATFORM_ALIASES:
        key = PLATFORM_ALIASES[key]
    if key not in {"truest", "za"}:
        raise AuthError(
            f"Unknown platform {value!r}. Use: truest, za. "
            "aifluxx is an alias of za. dev is a deprecated alias of za dev."
        )
    return key, False


def _host_from_tokens(platform: str | None, env: str | None) -> ApiTarget:
    if platform is None and env is None:
        return ApiTarget(DEFAULT_URL, False)
    deprecated = False
    if platform is not None:
        canonical, deprecated = _parse_platform(platform)
    else:
        canonical = DEFAULT_PLATFORM
    if deprecated:
        if env is not None and _parse_env(env) != "dev":
            raise AuthError(
                "Platform dev is a deprecated alias for platform za and env dev. "
                "Use --platform za --env prod, or pass env dev."
            )
        return ApiTarget(DEV_URL, True)
    env_name = _parse_env(env) if env is not None else DEFAULT_ENV
    return ApiTarget(DEVELOPER_HOSTS[(canonical, env_name)], False)


@dataclass(frozen=True)
class ApiTarget:
    url: str
    deprecated_dev: bool = False


def resolve_api_target(
    *,
    url: str | None = None,
    platform: str | None = None,
    env: str | None = None,
) -> ApiTarget:
    """Pick a developer API root.

    Precedence is ``--url``, then ``--platform`` / ``--env``, then
    ``AIFLUXX_PLATFORM`` / ``AIFLUXX_ENV``, then the config file, then
    platform ``za`` and env ``prod``. An omitted flag or env var falls
    through to the next source. ``AIFLUXX_API_URL`` is the env URL when
    neither platform nor env is set by a flag, an env var, or the config file.
    """
    if _present(url):
        return ApiTarget(normalize_api_url(url or ""), False)

    flag_platform = _present(platform)
    flag_env = _present(env)
    env_platform = _present(os.environ.get("AIFLUXX_PLATFORM"))
    env_env = _present(os.environ.get("AIFLUXX_ENV"))
    api_url = _present(os.environ.get("AIFLUXX_API_URL"))
    cfg_platform, cfg_env = load_host_config()

    if flag_platform or flag_env:
        return _host_from_tokens(flag_platform or env_platform or cfg_platform, flag_env or env_env or cfg_env)
    if env_platform or env_env:
        return _host_from_tokens(env_platform or cfg_platform, env_env or cfg_env)
    if api_url:
        return ApiTarget(normalize_api_url(api_url), False)
    if cfg_platform or cfg_env:
        return _host_from_tokens(cfg_platform, cfg_env)
    return ApiTarget(DEFAULT_URL, False)


def resolve_api_url(*, url: str | None = None, platform: str | None = None, env: str | None = None) -> str:
    """API root from :func:`resolve_api_target`."""
    return resolve_api_target(url=url, platform=platform, env=env).url


def signup_message() -> str:
    """Not-logged-in text. The signup host matches the selected platform."""
    brand = brand_of_url(resolve_api_target().url)
    return (
        "Not logged in. Run `aifluxx login` and paste the afx_dev_ key from Home. "
        f"Sign up at {SIGNUP_URLS[brand]} (accounts need approval)."
    )


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
        raise AuthError(signup_message())
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
