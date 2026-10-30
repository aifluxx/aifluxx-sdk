"""Developer Platform client (`/api/dev`). Host lives in dubai-agents."""
from __future__ import annotations

import io
import json
import re
import tarfile
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote, urlsplit

import httpx

from aifluxx_sdk.catalog import parse_tool_catalogue
from aifluxx_sdk.credentials import mcp_url
from aifluxx_sdk.exceptions import AifluxxError, AuthError, Forbidden, HostUnavailable
from aifluxx_sdk.lockfile import AgentLock, save_lock
from aifluxx_sdk.package import LOCAL_META_DIRS, validate_package

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


class DevClient:
    def __init__(self, http: httpx.Client, api_root: str) -> None:
        self._http = http
        self._api_root = api_root.rstrip("/")

    def me(self) -> dict[str, Any]:
        return self._json(self._http.get(f"{self._api_root}/api/dev/me"))

    def tools(self) -> Any:
        return self._json(self._http.get(f"{self._api_root}/api/dev/tools"))

    def read_tool_names(self) -> frozenset[str] | None:
        """Tool ids from ``GET /api/dev/tools``.

        ``None`` means this host does not publish a catalogue (404) or the
        body was not a catalogue. ``AuthError`` and ``Forbidden`` propagate.
        A non-response body (tests, proxies) also returns ``None``.
        """
        try:
            payload = self.tools()
        except HostUnavailable:
            return None
        except (TypeError, ValueError, AttributeError):
            return None
        if not isinstance(payload, (dict, list)):
            return None
        names = parse_tool_catalogue(payload)
        return names or None

    def status(self) -> Any:
        return self._json(self._http.get(f"{self._api_root}/api/dev/agents"))

    def push(self, package_dir: Path) -> dict[str, Any]:
        report = validate_package(package_dir, read_tools=self.read_tool_names())
        if not report.ok:
            codes = ", ".join(sorted({row.code for row in report.errors}))
            raise AifluxxError(f"Package failed validate ({codes}). Run `aifluxx validate`.")
        slug = str(report.spec.get("slug") or package_dir.name)
        version = str(report.spec.get("version") or "0.1.0")
        # One upload shape: multipart/form-data, file field "package" (.tar.gz)
        # and form field "metadata" (application/json). Never a raw gzip body.
        res = self._http.post(
            f"{self._api_root}/api/dev/agents/{slug}/versions",
            files=version_upload(package_dir, report.spec, slug, version),
        )
        payload = self._json(res)
        version_id = version_uuid_from_push(payload if isinstance(payload, dict) else {}, version)
        save_lock(
            package_dir,
            AgentLock(
                id=_text(payload.get("id")) if isinstance(payload, dict) else None,
                slug=slug,
                last_pushed_version=version,
                version_id=version_id,
            ),
        )
        return payload

    def resolve_version_id(self, slug: str, version: str | None = None, *, lock: AgentLock | None = None) -> str:
        """Return the version UUID the API accepts. Never returns ``latest`` or a semver."""
        hint = _version_hint(version)
        if _is_uuid(hint):
            return hint
        if lock is not None and _is_uuid(lock.version_id) and (not hint or hint == (lock.last_pushed_version or "")):
            return str(lock.version_id)
        semver = hint or (lock.last_pushed_version if lock and not hint else None)
        payload = self.status()
        found = select_version_id(payload, slug, semver=semver if semver and not _is_uuid(semver) else None)
        if found:
            return found
        if lock is not None and not hint and _is_uuid(lock.id):
            return str(lock.id)
        raise AifluxxError(
            f"Could not resolve a version UUID for {slug}. "
            "submit and run require a version UUID. The API rejects the word 'latest' with 422 uuid_parsing. "
            "Push the package, or pass --version <uuid>."
        )

    def run(
        self,
        slug: str,
        prompt: str,
        *,
        version: str | None = None,
        lock: AgentLock | None = None,
    ) -> Iterator[str]:
        version_id = self.resolve_version_id(slug, version, lock=lock)
        path = f"{self._api_root}/api/dev/agents/{slug}/versions/{version_id}/runs"
        try:
            with self._http.stream("POST", path, json={"prompt": prompt}) as res:
                if res.status_code >= 300:
                    _ensure_body(res)
                self._raise(res)
                for line in res.iter_lines():
                    if line:
                        yield line
        except httpx.ResponseNotRead as exc:
            raise AifluxxError(
                f"HTTP error from POST {path}, but the response body was not read ({exc}). "
                "The host's error was hidden by a streaming client bug."
            ) from exc

    def submit(self, slug: str, version: str | None = None, *, lock: AgentLock | None = None) -> dict[str, Any]:
        version_id = self.resolve_version_id(slug, version, lock=lock)
        path = f"{self._api_root}/api/dev/agents/{slug}/versions/{version_id}/submit"
        return self._json(self._http.post(path))

    def import_git(self, repo_url: str, *, token: str | None = None, ref: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"repo_url": repo_url}
        if token:
            body["token"] = token
        if ref:
            body["ref"] = ref
        return self._json(self._http.post(f"{self._api_root}/api/dev/imports/git", json=body))

    def list_keys(self) -> Any:
        return self._json(self._http.get(f"{self._api_root}/api/dev/keys"))

    def rotate_key(self, key_id: str) -> Any:
        return self._json(self._http.post(self._key_path(key_id, "rotate")))

    def revoke_key(self, key_id: str) -> Any:
        return self._json(self._http.post(self._key_path(key_id, "revoke")))

    def _key_path(self, key_id: str, action: str) -> str:
        cleaned = (key_id or "").strip()
        if not cleaned or any(mark in cleaned for mark in ("/", "\\", "?", "#")):
            raise AifluxxError("key id is invalid.")
        safe = quote(cleaned, safe="")
        return f"{self._api_root}/api/dev/keys/{safe}/{action}"

    def _json(self, res: httpx.Response) -> Any:
        self._raise(res)
        if not res.content:
            return {}
        return res.json()

    def _raise(self, res: httpx.Response) -> None:
        if 300 <= res.status_code < 400:
            raise AifluxxError(_redirect_message(res))
        if res.status_code < 400:
            return
        _ensure_body(res)
        detail = _detail(res)
        where = _http_where(res)
        if res.status_code == 401:
            extra = detail or "The host rejected the bearer key."
            raise AuthError(
                f"{where}: {extra} The API returned 401. The SDK sent the key from local credentials; "
                "this response is from the host."
            )
        if res.status_code == 403:
            raise Forbidden(f"{where}: {detail or 'This key cannot see that resource.'}")
        if res.status_code == 404:
            raise HostUnavailable(f"{where}: {detail or 'That developer API path was not found on this host.'}")
        if res.status_code >= 500:
            raise AifluxxError(
                f"{where}: {detail or 'The host returned a server error.'} This is an API error, not a local validation failure."
            )
        raise AifluxxError(f"{where}: {detail or 'The host rejected the request.'}")


def _ensure_body(res: httpx.Response) -> None:
    """Read a streamed error body so ``.json()`` does not raise ``ResponseNotRead``."""
    if getattr(res, "is_stream_consumed", True):
        return
    try:
        res.read()
    except httpx.ResponseNotRead:
        raise
    except Exception:
        return


def _http_where(res: httpx.Response) -> str:
    request = getattr(res, "request", None)
    method = getattr(request, "method", None)
    url = getattr(request, "url", None)
    if isinstance(method, str) and url is not None and type(url).__name__ != "MagicMock":
        return f"HTTP {res.status_code} from {method} {url}"
    return f"HTTP {res.status_code}"


def _redirect_message(res: httpx.Response) -> str:
    headers = getattr(res, "headers", {}) or {}
    try:
        location = str(headers.get("location") or headers.get("Location") or "")
    except Exception:
        location = ""
    where = _http_where(res)
    target = location or "(no Location header)"
    message = f"{where}: redirects to {target}."
    if location.startswith("http://"):
        message += " The Location URL is http, so the host is downgrading TLS."
    request_url = str(getattr(getattr(res, "request", None), "url", "") or "")
    if "/mcp" in request_url or "/mcp" in location:
        hinted = _mcp_hint(location if "/mcp" in location else request_url)
        if hinted:
            message += f" For MCP, use the https URL exactly as shown: {hinted}"
    return message


def _mcp_hint(raw: str) -> str | None:
    """HTTPS MCP URL for the host in ``raw``. None when ``raw`` has no host."""
    netloc = urlsplit(raw).netloc
    if not netloc:
        return None
    return mcp_url(f"https://{netloc}")


def _detail(res: httpx.Response) -> str:
    try:
        _ensure_body(res)
    except httpx.ResponseNotRead as exc:
        return f"(response body was not read: {exc})"
    try:
        body = res.json()
    except httpx.ResponseNotRead as exc:
        return f"(response body was not read: {exc})"
    except Exception:
        try:
            return (res.text or "")[:500]
        except httpx.ResponseNotRead as exc:
            return f"(response body was not read: {exc})"
        except Exception:
            return ""
    if isinstance(body, dict):
        detail = body.get("detail")
        if detail in (None, ""):
            detail = body.get("error") or body.get("message")
        if isinstance(detail, (dict, list)):
            return json.dumps(detail)[:500]
        if detail:
            return str(detail)[:500]
        return json.dumps(body)[:500]
    if body in (None, ""):
        return ""
    return str(body)[:500]


def _is_uuid(value: object) -> bool:
    return isinstance(value, str) and bool(_UUID.fullmatch(value.strip()))


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _version_hint(version: str | None) -> str:
    hint = (version or "").strip()
    if hint.lower() == "latest":
        return ""
    return hint


_VERSION_ID_KEYS = ("version_id", "versionId")
# Objects that are the version itself, not the agent that owns it.
_NESTED_VERSION_KEYS = ("version", "latest_version", "created_version", "draft")
_VERSION_ROW_KEYS = ("versions", "drafts")
_ENVELOPE_KEYS = ("agent", "data", "result")


def version_uuid_from_push(payload: dict[str, Any], semver: str) -> str | None:
    """Version UUID from a push response.

    Explicit ``version_id`` wins. Otherwise the id of the version object, a
    ``versions`` or ``drafts`` row, or the resource ``id`` when ``version`` is
    the semver that was just uploaded. That created-version object includes
    the package slug, so a slug alone does not hide the id.
    """
    return _version_uuid_in(payload, semver, depth=0)


def _version_uuid_in(node: Any, semver: str, depth: int) -> str | None:
    if depth > 5 or not isinstance(node, dict):
        return None
    for key in _VERSION_ID_KEYS:
        if _is_uuid(node.get(key)):
            return str(node[key]).strip()
    for key in _NESTED_VERSION_KEYS:
        child = node.get(key)
        if not isinstance(child, dict):
            continue
        found = _version_uuid_in(child, semver, depth + 1)
        if found:
            return found
        if _is_uuid(child.get("id")):
            return str(child["id"]).strip()
    for key in _VERSION_ROW_KEYS:
        found = _uuid_from_version_rows(node.get(key))
        if found:
            return found
    # The created version's own id. Check it before wrapped copies so a nested
    # agent summary cannot replace the version UUID on the response itself.
    if _is_uuid(node.get("id")) and _is_pushed_version(node, semver):
        return str(node["id"]).strip()
    for key in _ENVELOPE_KEYS:
        child = node.get(key)
        if isinstance(child, dict):
            found = _version_uuid_in(child, semver, depth + 1)
            if found:
                return found
    return None


def _uuid_from_version_rows(rows: Any) -> str | None:
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        return None
    chosen = _prefer([row for row in rows if isinstance(row, dict)])
    if chosen is None:
        return None
    vid = chosen.get("version_id") or chosen.get("versionId") or chosen.get("id")
    return str(vid).strip() if _is_uuid(vid) else None


def _is_pushed_version(node: dict[str, Any], semver: str) -> bool:
    """True when this object is the version that was just uploaded.

    ``POST .../versions`` returns that version. Its ``id`` is the version UUID
    and its ``version`` is the semver from spec.yaml. A slug on that object is
    the package slug, not a sign that ``id`` belongs to the agent. An agent
    summary whose semver does not match, and which has no state, is left alone.
    """
    version = node.get("version")
    if not isinstance(version, str):
        return False
    if version.strip() == (semver or "").strip():
        return True
    has_state = bool(node.get("state") or node.get("status"))
    if node.get("slug") and not has_state:
        return False
    return has_state


def select_version_id(payload: Any, slug: str, *, semver: str | None = None) -> str | None:
    versions = _versions_for_slug(payload, slug)
    if semver:
        versions = [row for row in versions if _version_label(row) == semver]
    if not versions:
        return None
    chosen = _prefer(versions)
    if chosen is None:
        return None
    vid = chosen.get("version_id") or chosen.get("id")
    return str(vid).strip() if _is_uuid(vid) else None


def _version_label(row: dict[str, Any]) -> str:
    for key in ("version", "name", "label"):
        value = row.get(key)
        if isinstance(value, str):
            return value
    return ""


def _prefer(versions: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not versions:
        return None
    drafts = [row for row in versions if str(row.get("state") or row.get("status") or "").lower() == "draft"]
    pool = drafts or versions

    def _stamp(row: dict[str, Any]) -> str:
        for key in ("created_at", "updated_at", "version"):
            value = row.get(key)
            if isinstance(value, str):
                return value
        return ""

    return max(pool, key=_stamp)


def _versions_for_slug(payload: Any, slug: str) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}

    def add(row: dict[str, Any]) -> None:
        vid = row.get("version_id") or row.get("id")
        if _is_uuid(vid):
            found[str(vid).strip()] = row

    def from_agent(agent: dict[str, Any]) -> None:
        for key in ("versions", "drafts"):
            rows = agent.get(key)
            if isinstance(rows, dict):
                rows = [rows]
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict):
                        add(row)
        if _is_uuid(agent.get("version_id")):
            label = agent.get("version") if isinstance(agent.get("version"), str) else None
            add(
                {
                    "id": agent.get("version_id"),
                    "version": label,
                    "state": agent.get("state") or agent.get("status"),
                    "created_at": agent.get("created_at") or agent.get("updated_at"),
                }
            )

    def walk(node: Any, active: bool) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item, active)
            return
        if not isinstance(node, dict):
            return
        node_slug = node.get("slug")
        here = active
        if isinstance(node_slug, str):
            here = node_slug == slug
        if here:
            from_agent(node)
        for value in node.values():
            if isinstance(value, (dict, list)):
                walk(value, here if isinstance(node_slug, str) else active)

    walk(payload, False)
    return list(found.values())


def version_upload(package_dir: Path, spec: dict[str, Any], slug: str, version: str) -> dict[str, tuple[Any, ...]]:
    """Multipart parts for ``POST /api/dev/agents/{slug}/versions``.

    The request ``Content-Type`` is ``multipart/form-data`` with a boundary
    chosen by the HTTP client. There is no raw gzip body and no
    ``Content-Type: application/gzip`` on the request.

    * ``package`` — file part, filename ``package.tar.gz``, part
      ``Content-Type: application/gzip``. Bytes are a gzip-compressed ustar
      archive (magic ``1f 8b``). Member names are paths relative to the
      package root. ``.aifluxx`` and a leftover metadata directory from an
      older install are omitted.
    * ``metadata`` — form field (no filename), part
      ``Content-Type: application/json``. UTF-8 JSON object with keys
      ``slug``, ``version`` (semver from spec.yaml), ``schema``, and ``spec``
      (the parsed spec.yaml object).
    """
    metadata = {
        "slug": slug,
        "version": version,
        "schema": spec.get("schema"),
        "spec": spec,
    }
    encoded = json.dumps(metadata, ensure_ascii=False).encode("utf-8")
    return {
        "package": ("package.tar.gz", _tarball(package_dir), "application/gzip"),
        "metadata": (None, encoded, "application/json"),
    }


def _tarball(package_dir: Path) -> bytes:
    buf = io.BytesIO()
    root = package_dir.resolve()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in root.rglob("*"):
            if not path.is_file() or LOCAL_META_DIRS.intersection(path.parts):
                continue
            tar.add(path, arcname=str(path.relative_to(root)))
    return buf.getvalue()
