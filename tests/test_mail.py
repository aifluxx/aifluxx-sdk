from unittest.mock import MagicMock

import pytest

from aifluxx_sdk import AifluxxClient, MailboxNotConnected, TruestClient
from aifluxx_sdk.mail import MailClient


class _Res:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"ok": True}
        self.content = b"{}" if payload is not None or status_code < 400 else b""
        self.text = text

    def json(self):
        return self._payload


def test_send_requires_from():
    http = MagicMock()
    mail = MailClient(http, "https://api.example")
    with pytest.raises(MailboxNotConnected):
        mail.send(from_="  ", to="a@b.c", subject="s", body="b", business_id="co")
    http.post.assert_not_called()


def test_send_posts_json():
    http = MagicMock()
    http.post.return_value = _Res(200, {"ok": True})
    mail = MailClient(http, "https://api.example")
    mail.send(
        from_="pinnacle@palmerclan.us",
        to="x@y.z",
        subject="Hi",
        body="Body",
        business_id="co-1",
    )
    args, kwargs = http.post.call_args
    assert args[0].endswith("/api/companies/co-1/mail/send")
    assert kwargs["json"]["from"] == "pinnacle@palmerclan.us"


def test_client_send_not_implemented_until_a2a():
    client = AifluxxClient("https://api.example", api_key="afx_live_test")
    with pytest.raises(NotImplementedError, match="A2A"):
        client.send("chief_of_staff", "hello", business_id="co")
    client.close()


def test_truest_client_is_deprecated_alias():
    with pytest.warns(DeprecationWarning, match="AifluxxClient"):
        client = TruestClient("https://api.example", api_key="afx_live_test")
    assert isinstance(client, AifluxxClient)
    client.close()
