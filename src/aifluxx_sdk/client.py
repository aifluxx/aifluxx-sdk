"""AIFluxx HTTP client."""
from __future__ import annotations

import json
import re
from typing import Any

import httpx

from aifluxx_sdk.credentials import mcp_url, resolve_api_url
from aifluxx_sdk.dev import DevClient
from aifluxx_sdk.exceptions import AifluxxError, AuthError
from aifluxx_sdk.mail import MailClient

# Home and subscriber keys. Companion errors must not echo these.
_SECRET_TEXT = re.compile(r"afx_(?:dev|live)_[A-Za-z0-9_-]+|mcpat_[A-Za-z0-9_-]+|Bearer\s+\S+", re.I)


class AifluxxClient:
    """Acts as the Connected-apps key holder.

    Mail send is REST. Skill chat (`send`) is A2A and raises until the host mounts /a2a.

    ``url`` is optional. An omitted URL uses ``AIFLUXX_API_URL``, then the URL
    saved by ``aifluxx login``, then production (``https://api.aifluxx.co.za``).
    """

    def __init__(self, url: str | None = None, *, api_key: str, timeout: float = 60.0) -> None:
        if not (api_key or "").strip():
            raise AuthError("api_key is required.")
        self.url = resolve_api_url(url=url)
        self._http = httpx.Client(
            base_url=self.url,
            headers={"Authorization": f"Bearer {api_key.strip()}"},
            timeout=timeout,
            follow_redirects=False,
        )
        self.mail = MailClient(self._http, self.url)
        self.dev = DevClient(self._http, self.url)
        self.companion = CompanionClient(self._http, self.url)

    @property
    def mcp_url(self) -> str:
        """HTTPS MCP endpoint for this client's API root, with a trailing slash."""
        return mcp_url(self.url)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> AifluxxClient:
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
            "A2A chat is not available yet; use runs via `aifluxx run` (developer runs API) "
            "to run an agent. Use client.mail.send() for connected-mailbox mail."
        )


class CompanionClient:
    """Developer companion (``/api/dev/companion``).

    Uses the same HTTP client as the other developer calls, so the bearer
    header and the resolved API root stay aligned with ``aifluxx login``.
    """

    def __init__(self, http: httpx.Client, api_root: str) -> None:
        self._http = http
        self._api_root = api_root.rstrip("/")

    def status(self) -> dict[str, Any]:
        """``GET /api/dev/companion``."""
        res = self._http.get(f"{self._api_root}/api/dev/companion")
        self._raise(res)
        return _object(res)

    def send(self, message: str, *, project_slug: str, mode: str) -> dict[str, Any]:
        """``POST /api/dev/companion/messages``.

        ``message`` is the focused text. ``mode`` is ``build`` or ``config``.
        A 200 body with ``servable: false`` is the same failure as HTTP 503.
        """
        body = {"message": message, "project_slug": project_slug, "mode": mode}
        res = self._http.post(f"{self._api_root}/api/dev/companion/messages", json=body)
        self._raise(res)
        payload = _object(res)
        if payload.get("servable") is False:
            raise AifluxxError(_not_servable(payload))
        return payload

    def _raise(self, res: httpx.Response) -> None:
        if res.status_code < 400:
            return
        detail, body = _error_body(res)
        if res.status_code == 401:
            raise AuthError("Not logged in, or this key was rejected. Run `aifluxx login`.")
        if res.status_code == 429:
            raise AifluxxError(_limit_message(detail, body))
        if res.status_code == 503 or body.get("servable") is False:
            raise AifluxxError(_not_servable(body))
        if res.status_code == 404:
            raise AifluxxError(
                "This host has no companion endpoint. Check the API URL from `aifluxx login`."
            )
        extra = f" {detail}" if detail else ""
        raise AifluxxError(f"Companion request failed (HTTP {res.status_code}).{extra}")


def scrub_secret(text: str) -> str:
    """Replace key-shaped text. Companion output must not contain a key."""
    return _SECRET_TEXT.sub("[redacted]", text or "")


def _object(res: httpx.Response) -> dict[str, Any]:
    if not res.content:
        return {}
    try:
        payload = res.json()
    except Exception as exc:
        raise AifluxxError("Companion returned a body that is not JSON.") from exc
    if not isinstance(payload, dict):
        raise AifluxxError("Companion returned an unexpected payload.")
    return payload


def _error_body(res: httpx.Response) -> tuple[str, dict[str, Any]]:
    try:
        body = res.json()
    except Exception:
        try:
            text = res.text or ""
        except Exception:
            text = ""
        return scrub_secret(text)[:300], {}
    if not isinstance(body, dict):
        return scrub_secret(str(body))[:300], {}
    detail = body.get("detail")
    if detail in (None, ""):
        detail = body.get("error") or body.get("message") or ""
    if isinstance(detail, (dict, list)):
        detail = json.dumps(detail)
    return scrub_secret(str(detail))[:300], body


def _limit_message(detail: str, body: dict[str, Any]) -> str:
    message = "Companion rate limit reached. Wait and try again."
    limits = body.get("limits")
    if limits is None:
        limits = body.get("limit")
    if isinstance(limits, dict) and limits:
        bits = [f"{key}={scrub_secret(str(value))}" for key, value in limits.items()]
        message += " Limits: " + ", ".join(bits) + "."
    elif limits not in (None, "", {}, []):
        message += f" Limits: {scrub_secret(str(limits))}."
    if detail and detail not in message:
        message += f" {detail}"
    return message


def _not_servable(body: dict[str, Any]) -> str:
    message = "Companion is not servable right now. Try again later."
    detail = body.get("detail") or body.get("message") or ""
    if isinstance(detail, str) and detail.strip():
        cleaned = scrub_secret(detail.strip())
        if cleaned and cleaned not in message:
            message = f"{message} {cleaned}"
    return message
