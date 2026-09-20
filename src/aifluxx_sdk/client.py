"""Truest / Enterprise HTTP client."""
from __future__ import annotations

import httpx

from aifluxx_sdk.exceptions import AuthError
from aifluxx_sdk.mail import MailClient


class TruestClient:
    """Acts as the Connected-apps key holder.

    Mail send is REST (DEV-165). Skill chat (`send`) is A2A (DEV-162) and
    raises until the host mounts /a2a.
    """

    def __init__(self, url: str, *, api_key: str, timeout: float = 60.0) -> None:
        if not (api_key or "").strip():
            raise AuthError("api_key is required.")
        self.url = url.rstrip("/")
        self._http = httpx.Client(
            base_url=self.url,
            headers={"Authorization": f"Bearer {api_key.strip()}"},
            timeout=timeout,
        )
        self.mail = MailClient(self._http, self.url)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> TruestClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def send(
        self,
        skill_id: str,
        prompt: str,
        *,
        business_id: str | None = None,
        stream: bool = False,
    ):
        raise NotImplementedError(
            "client.send() talks A2A at /a2a (DEV-162 phases 1–2). "
            "Use client.mail.send() for connected-mailbox mail."
        )
