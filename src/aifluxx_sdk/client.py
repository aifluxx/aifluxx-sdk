"""AIFluxx HTTP client."""
from __future__ import annotations

import httpx

from aifluxx_sdk.credentials import mcp_url, resolve_api_url
from aifluxx_sdk.dev import DevClient
from aifluxx_sdk.exceptions import AuthError
from aifluxx_sdk.mail import MailClient


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
