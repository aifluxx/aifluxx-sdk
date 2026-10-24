"""Developer Platform client (`/api/dev`). Host lives in dubai-agents."""
from __future__ import annotations

import io
import tarfile
from pathlib import Path
from typing import Any, Iterator

import httpx

from aifluxx_sdk.exceptions import AifluxxError, AuthError, Forbidden, HostUnavailable
from aifluxx_sdk.lockfile import AgentLock, save_lock
from aifluxx_sdk.package import validate_package


class DevClient:
    def __init__(self, http: httpx.Client, api_root: str) -> None:
        self._http = http
        self._api_root = api_root.rstrip("/")

    def me(self) -> dict[str, Any]:
        return self._json(self._http.get(f"{self._api_root}/api/dev/me"))

    def status(self) -> Any:
        return self._json(self._http.get(f"{self._api_root}/api/dev/agents"))

    def push(self, package_dir: Path) -> dict[str, Any]:
        report = validate_package(package_dir)
        if not report.ok:
            codes = ", ".join(sorted({row.code for row in report.errors}))
            raise AifluxxError(f"Package failed validate ({codes}). Run `truest validate`.")
        slug = str(report.spec.get("slug") or package_dir.name)
        version = str(report.spec.get("version") or "0.1.0")
        archive = _tarball(package_dir)
        res = self._http.post(
            f"{self._api_root}/api/dev/agents/{slug}/versions",
            files={"package": ("package.tar.gz", archive, "application/gzip")},
        )
        payload = self._json(res)
        save_lock(
            package_dir,
            AgentLock(id=payload.get("id") or report.spec.get("id"), slug=slug, last_pushed_version=version),
        )
        return payload

    def run(self, slug: str, prompt: str, *, version: str | None = None) -> Iterator[str]:
        path = f"{self._api_root}/api/dev/agents/{slug}/versions/{version or 'latest'}/runs"
        with self._http.stream("POST", path, json={"prompt": prompt}) as res:
            self._raise(res)
            for line in res.iter_lines():
                if line:
                    yield line

    def submit(self, slug: str, version: str | None = None) -> dict[str, Any]:
        path = f"{self._api_root}/api/dev/agents/{slug}/versions/{version or 'latest'}/submit"
        return self._json(self._http.post(path))

    def import_git(self, repo_url: str, *, token: str | None = None, ref: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"repo_url": repo_url}
        if token:
            body["token"] = token
        if ref:
            body["ref"] = ref
        return self._json(self._http.post(f"{self._api_root}/api/dev/imports/git", json=body))

    def _json(self, res: httpx.Response) -> Any:
        self._raise(res)
        if not res.content:
            return {}
        return res.json()

    def _raise(self, res: httpx.Response) -> None:
        if res.status_code < 400:
            return
        detail = _detail(res)
        if res.status_code == 401:
            raise AuthError(detail or "Key was rejected. Run `truest login` with an afx_dev_ key from Home.")
        if res.status_code == 403:
            raise Forbidden(detail or "This key cannot see that resource.")
        if res.status_code == 404:
            raise HostUnavailable(
                detail or "Developer API is not mounted on this host yet. The CLI is ready; /api/dev ships with DEV-167."
            )
        raise AifluxxError(detail or f"Request failed ({res.status_code}).")


def _detail(res: httpx.Response) -> str:
    try:
        body = res.json()
        return str(body.get("detail") or body.get("error") or "")
    except Exception:
        return (res.text or "")[:300]


def _tarball(package_dir: Path) -> bytes:
    buf = io.BytesIO()
    root = package_dir.resolve()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in root.rglob("*"):
            if not path.is_file() or ".truest" in path.parts:
                continue
            tar.add(path, arcname=str(path.relative_to(root)))
    return buf.getvalue()
