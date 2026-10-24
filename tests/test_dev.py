from unittest.mock import MagicMock

import pytest

from aifluxx_sdk.dev import DevClient
from aifluxx_sdk.exceptions import HostUnavailable


class _Res:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.content = b"{}" if payload is not None else b""
        self.text = text

    def json(self):
        return self._payload


def test_missing_host_is_host_unavailable():
    http = MagicMock()
    http.get.return_value = _Res(404, {"detail": "Not Found"})
    client = DevClient(http, "https://api.example")
    with pytest.raises(HostUnavailable, match="Not Found"):
        client.me()
