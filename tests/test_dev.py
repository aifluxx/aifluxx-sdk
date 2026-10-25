import io
import tarfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aifluxx_sdk.dev import DevClient, _tarball
from aifluxx_sdk.exceptions import AifluxxError, HostUnavailable


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


def test_keys_call_dev_paths():
    http = MagicMock()
    http.get.return_value = _Res(200, {"keys": []})
    http.post.return_value = _Res(200, {"id": "k1"})
    client = DevClient(http, "https://api.example")
    client.list_keys()
    http.get.assert_called_with("https://api.example/api/dev/keys")
    client.rotate_key("k1")
    http.post.assert_called_with("https://api.example/api/dev/keys/k1/rotate")
    client.revoke_key("k1")
    http.post.assert_called_with("https://api.example/api/dev/keys/k1/revoke")


def test_key_id_rejects_slash():
    client = DevClient(MagicMock(), "https://api.example")
    with pytest.raises(AifluxxError, match="invalid"):
        client.rotate_key("a/b")


def test_tarball_skips_local_meta(tmp_path: Path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "spec.yaml").write_text("schema: aifluxx/agent/v1\n", encoding="utf-8")
    for name in (".aifluxx", ".truest"):
        folder = package / name
        folder.mkdir()
        (folder / "agent.lock").write_text("{}\n", encoding="utf-8")
    with tarfile.open(fileobj=io.BytesIO(_tarball(package)), mode="r:gz") as archive:
        names = archive.getnames()
    assert names == ["spec.yaml"]
