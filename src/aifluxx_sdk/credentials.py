"""Machine-local key store. Same file from every IDE."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from aifluxx_sdk.exceptions import AuthError

DEFAULT_URL = "https://api.aifluxx.co.za"
# ZA dev developer API. The dev portal calls /api/dev on its own origin.
DEV_URL = "https://dev.developer.aifluxx.co.za"

PLATFORMS = {
    "aifluxx": DEFAULT_URL,
    "dev": DEV_URL,
}

_CONFIG_DIR = ".aifluxx"


def normalize_api_url(url: str) -> str:
    """Return a canonical API root with no trailing slash."""
    return (url or "").strip().rstrip("/")


def resolve_api_url(*, url: str | None = None, platform: str | None = None) -> str:
    """Pick an API root.

    Precedence: explicit ``url``, then ``platform``, then ``AIFLUXX_API_URL``,
    then the URL saved by ``aifluxx login``, then production.
    """
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
    saved = _saved_api_url()
    if saved:
        return saved
    return DEFAULT_URL


def mcp_url(api_base: str | None = None) -> str:
    """MCP endpoint for an API root. The trailing slash is required.

    ``api_base`` is used as given. When it is omitted, the base is
    ``resolve_api_url()`` (env, saved login, then production).
    """
    if api_base is None:
        base = resolve_api_url()
    else:
        base = normalize_api_url(api_base) or resolve_api_url()
    return f"{base}/mcp/"


def _saved_api_url() -> str | None:
    """URL from the credentials file, or None when that file cannot be read."""
    try:
        return load_credentials().url
    except AuthError:
        return None


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
    if os.name == "nt":
        _harden_windows(path, directory=directory)
        return
    _harden_posix(path, directory=directory)


def _harden_posix(path: Path, *, directory: bool) -> None:
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


def _harden_windows(path: Path, *, directory: bool) -> None:
    """Leave a DACL that allows only the current user."""
    try:
        _restrict_to_current_user(path, directory=directory)
        if not _windows_dacl_is_current_user_only(path):
            raise OSError("the access list did not stick")
    except OSError as exc:
        _drop_unlocked_secret(path, directory)
        raise AuthError(
            f"Could not lock down {path} so only you can read it: {exc}. "
            "Refusing to keep an API key this process cannot lock down."
        ) from exc


def _restrict_to_current_user(path: Path, *, directory: bool) -> None:
    import ctypes
    from ctypes import wintypes

    advapi32, kernel32 = _win_security()
    with _current_user_sid(advapi32, kernel32) as sid:
        sid_len = advapi32.GetLengthSid(sid)
        # ACL (8) + ACCESS_ALLOWED_ACE header and mask (8) + SID.
        acl_size = 8 + 8 + sid_len
        acl = ctypes.create_string_buffer(acl_size)
        if not advapi32.InitializeAcl(acl, acl_size, 2):
            raise ctypes.WinError(ctypes.get_last_error())
        inherit = 0x1 | 0x2 if directory else 0  # object and container inherit
        if not advapi32.AddAccessAllowedAceEx(acl, 2, inherit, 0x001F01FF, sid):
            raise ctypes.WinError(ctypes.get_last_error())
        # Replace inherited entries. 0x4 is DACL, 0x80000000 protects it from the parent.
        status = advapi32.SetNamedSecurityInfoW(
            str(path),
            1,
            0x4 | 0x80000000,
            None,
            None,
            acl,
            None,
        )
        if status:
            raise ctypes.WinError(status)


def _windows_dacl_is_current_user_only(path: Path) -> bool:
    import ctypes

    advapi32, kernel32 = _win_security()
    owner = ctypes.c_void_p()
    group = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    sacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    status = advapi32.GetNamedSecurityInfoW(
        str(path),
        1,
        0x4,
        ctypes.byref(owner),
        ctypes.byref(group),
        ctypes.byref(dacl),
        ctypes.byref(sacl),
        ctypes.byref(descriptor),
    )
    if status:
        raise OSError(ctypes.WinError(status))
    try:
        if not dacl.value:
            return False
        count = _acl_ace_count(dacl)
        if count != 1:
            return False
        ace = ctypes.c_void_p()
        if not advapi32.GetAce(dacl, 0, ctypes.byref(ace)):
            raise OSError(ctypes.WinError(ctypes.get_last_error()))
        header = ctypes.cast(ace, ctypes.POINTER(ctypes.c_ubyte * 4)).contents
        if header[0] != 0:  # ACCESS_ALLOWED_ACE_TYPE
            return False
        ace_sid = ace.value + 8
        with _current_user_sid(advapi32, kernel32) as sid:
            return bool(advapi32.EqualSid(sid, ace_sid))
    finally:
        if descriptor.value:
            kernel32.LocalFree(descriptor)


def _acl_ace_count(dacl) -> int:
    import ctypes
    from ctypes import wintypes

    class _ACL(ctypes.Structure):
        _fields_ = [
            ("AclRevision", ctypes.c_ubyte),
            ("Sbz1", ctypes.c_ubyte),
            ("AclSize", wintypes.WORD),
            ("AceCount", wintypes.WORD),
            ("Sbz2", wintypes.WORD),
        ]

    return int(ctypes.cast(dacl, ctypes.POINTER(_ACL)).contents.AceCount)


def _win_security():
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.GetLengthSid.argtypes = [ctypes.c_void_p]
    advapi32.GetLengthSid.restype = wintypes.DWORD
    advapi32.InitializeAcl.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD]
    advapi32.InitializeAcl.restype = wintypes.BOOL
    advapi32.AddAccessAllowedAceEx.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    advapi32.AddAccessAllowedAceEx.restype = wintypes.BOOL
    advapi32.SetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.GetAce.restype = wintypes.BOOL
    advapi32.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    advapi32.EqualSid.restype = wintypes.BOOL
    return advapi32, kernel32


class _current_user_sid:
    """SID of the process user. The token buffer stays alive for the ``with`` block."""

    def __init__(self, advapi32, kernel32) -> None:
        import ctypes
        from ctypes import wintypes

        self._advapi32 = advapi32
        self._kernel32 = kernel32
        self._token = wintypes.HANDLE()
        self._buf = None
        if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(self._token)):
            raise ctypes.WinError(ctypes.get_last_error())
        length = wintypes.DWORD()
        advapi32.GetTokenInformation(self._token, 1, None, 0, ctypes.byref(length))
        self._buf = ctypes.create_string_buffer(length.value)
        if not advapi32.GetTokenInformation(self._token, 1, self._buf, length, ctypes.byref(length)):
            self._kernel32.CloseHandle(self._token)
            raise ctypes.WinError(ctypes.get_last_error())

        class _SidAndAttributes(ctypes.Structure):
            _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

        class _TokenUser(ctypes.Structure):
            _fields_ = [("User", _SidAndAttributes)]

        self._sid = ctypes.cast(self._buf, ctypes.POINTER(_TokenUser)).contents.User.Sid

    def __enter__(self):
        return self._sid

    def __exit__(self, *args: object) -> None:
        self._kernel32.CloseHandle(self._token)


def _drop_unlocked_secret(path: Path, directory: bool) -> None:
    if directory:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
