"""Python client for AIFluxx (mail send now; A2A skills when the server is up)."""

from importlib.metadata import PackageNotFoundError, version

from aifluxx_sdk.client import AifluxxClient
from aifluxx_sdk.exceptions import (
    AifluxxError,
    AuthError,
    BusinessRequired,
    Forbidden,
    HostUnavailable,
    MailboxNotConnected,
    SendFailed,
)

try:
    __version__ = version("aifluxx-sdk")
except PackageNotFoundError:
    __version__ = "1.3.1"

__all__ = [
    "AifluxxClient",
    "AifluxxError",
    "AuthError",
    "BusinessRequired",
    "Forbidden",
    "HostUnavailable",
    "MailboxNotConnected",
    "SendFailed",
    "__version__",
]
