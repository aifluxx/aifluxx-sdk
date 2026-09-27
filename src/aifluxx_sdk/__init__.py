"""Python client for Truest (mail send now; A2A skills when the server is up)."""

from aifluxx_sdk.client import TruestClient
from aifluxx_sdk.exceptions import (
    AifluxxError,
    AuthError,
    BusinessRequired,
    Forbidden,
    HostUnavailable,
    MailboxNotConnected,
    SendFailed,
)

__all__ = [
    "TruestClient",
    "AifluxxError",
    "AuthError",
    "BusinessRequired",
    "Forbidden",
    "HostUnavailable",
    "MailboxNotConnected",
    "SendFailed",
]
