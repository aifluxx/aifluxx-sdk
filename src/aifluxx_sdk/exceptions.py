"""Exceptions for aifluxx-sdk."""


class AifluxxError(Exception):
    """Base error."""


class AuthError(AifluxxError):
    """Missing or invalid API key."""


class BusinessRequired(AifluxxError):
    def __init__(self, businesses: list[dict] | None = None) -> None:
        super().__init__("business_id is required")
        self.businesses = businesses or []


class Forbidden(AifluxxError):
    """Caller is not a company admin or delegate (mail send)."""


class MailboxNotConnected(AifluxxError):
    """from_ does not match a connected mailbox on that company."""


class SendFailed(AifluxxError):
    """Provider (SMTP / Gmail / Graph) rejected the send."""


class HostUnavailable(AifluxxError):
    """Developer API is not mounted on this host yet."""
