"""Connected-mailbox send (DEV-165). Same rules as the in-app agent tool."""
from __future__ import annotations

from typing import Any

import httpx

from aifluxx_sdk.exceptions import Forbidden, MailboxNotConnected, SendFailed


class MailClient:
    def __init__(self, http: httpx.Client, api_root: str) -> None:
        self._http = http
        self._api_root = api_root.rstrip("/")

    def mailboxes(self, *, business_id: str) -> list[dict[str, Any]]:
        """Connected mailbox identities that may be used as from_."""
        res = self._http.get(f"{self._api_root}/api/companies/{business_id}/mail/mailboxes")
        _raise_mail(res)
        payload = res.json()
        rows = payload.get("mailboxes") if isinstance(payload, dict) else payload
        return list(rows or [])

    def send(
        self,
        *,
        from_: str,
        to: str,
        subject: str,
        body: str,
        business_id: str,
    ) -> dict[str, Any]:
        """Send immediately from a connected mailbox. from_ is required."""
        if not (from_ or "").strip():
            raise MailboxNotConnected("from_ is required and must match a connected mailbox.")
        res = self._http.post(
            f"{self._api_root}/api/companies/{business_id}/mail/send",
            json={
                "from": from_.strip(),
                "to": to,
                "subject": subject,
                "body": body,
            },
        )
        _raise_mail(res)
        return res.json() if res.content else {"ok": True}


def _raise_mail(res: httpx.Response) -> None:
    if res.status_code < 400:
        return
    detail = ""
    try:
        body = res.json()
        detail = str(body.get("detail") or body.get("error") or "")
    except Exception:
        detail = res.text[:300]
    if res.status_code in (401, 403):
        raise Forbidden(detail or "Not allowed to send from this mailbox.")
    if res.status_code == 404:
        raise MailboxNotConnected(detail or "Mailbox is not connected.")
    raise SendFailed(detail or f"Send failed ({res.status_code}).")
