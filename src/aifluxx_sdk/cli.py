"""`aifluxx` CLI."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn

import httpx
import typer

from aifluxx_sdk import __version__
from aifluxx_sdk.client import AifluxxClient
from aifluxx_sdk.credentials import (
    PLATFORMS,
    Credentials,
    load_credentials,
    normalize_api_url,
    resolve_api_url,
    save_credentials,
)
from aifluxx_sdk.exceptions import AifluxxError, AuthError, HostUnavailable
from aifluxx_sdk.lockfile import load_lock
from aifluxx_sdk.package import validate_package
from aifluxx_sdk.source import copy_sdk_source
from aifluxx_sdk.templates import (
    DEFAULT_TEMPLATE,
    get_template,
    render_spec,
    slug_to_name,
    template_option_help,
    template_rows,
)

# Fields that carry a secret or a hash of one. `key_once` is the value POST /api/dev/keys returns.
_SECRET_FIELDS = ("key_once", "api_key", "key", "secret", "token")
_REDACT_FIELDS = _SECRET_FIELDS + ("key_hash", "password", "password_hash", "hash")
_STATE_LABELS = {
    "active": "Active",
    "approved": "Approved",
    "draft": "Draft",
    "error": "Error",
    "failed": "Failed",
    "in review": "In review",
    "paused": "Paused",
    "pending": "Pending",
    "published": "Published",
    "ready": "Ready",
    "rejected": "Rejected",
    "revoked": "Revoked",
    "submitted": "Submitted",
}
_STATE_KEYS = {"state", "status"}


def _prog() -> str:
    return "aifluxx"


def _platform_help() -> str:
    ordered = ("aifluxx", "dev")
    bits = [f"{name} ({PLATFORMS[name]})" for name in ordered]
    return (
        "Named host. Default: aifluxx (production). "
        + "; ".join(bits)
        + ". Example: aifluxx login --platform dev."
    )


def _named_platform(url: str) -> str | None:
    normalized = normalize_api_url(url)
    for name in ("aifluxx", "dev"):
        if PLATFORMS[name] == normalized:
            return name
    return None


def _login_banner(url: str) -> str:
    """Say which platform this login will use. Production stays the default."""
    name = _named_platform(url)
    if name == "aifluxx":
        return f"Logging in to aifluxx (production, {url})."
    if name == "dev":
        return f"Logging in to dev ({url})."
    return f"Logging in to {url}."


app = typer.Typer(
    name=_prog(),
    no_args_is_help=True,
    add_completion=False,
    help="Author an agent package and call the AIFluxx API. Signup stays on the developer site.",
)
keys_app = typer.Typer(no_args_is_help=True, help="List, create, rotate, or revoke developer API keys.")
app.add_typer(keys_app, name="keys")


def _json_option() -> Any:
    return typer.Option(False, "--json", help="Print the API payload as JSON.")


def _interactive() -> bool:
    try:
        return bool(sys.stdin.isatty())
    except Exception:
        return False


def _die(exc: Exception) -> NoReturn:
    typer.secho(str(exc), err=True, fg="red")
    raise typer.Exit(code=1)


def _client() -> AifluxxClient:
    creds = load_credentials()
    return AifluxxClient(api_key=creds.api_key)


def _package_dir(path: Path | None) -> Path:
    if path:
        return path.resolve()
    cwd = Path.cwd()
    if (cwd / "spec.yaml").is_file():
        return cwd
    raise AifluxxError("No spec.yaml here. Pass a path or run the command inside the package folder.")


def _as_json(ctx: typer.Context, json_output: bool) -> bool:
    if json_output:
        return True
    current: typer.Context | None = ctx
    while current is not None:
        obj = current.obj
        if isinstance(obj, dict) and obj.get("json"):
            return True
        current = current.parent
    return False


def _pretty(payload: object) -> str:
    if isinstance(payload, (dict, list)):
        return json.dumps(payload, indent=2)
    return str(payload)


def display_state(value: str) -> str:
    """Return one casing for a version or key state."""
    cleaned = " ".join(value.replace("_", " ").replace("-", " ").split())
    key = cleaned.lower()
    if key in _STATE_LABELS:
        return _STATE_LABELS[key]
    if value.isupper() or value.islower() or "_" in value or "-" in value:
        return cleaned.title()
    return value


def _normalize_states(node: Any) -> Any:
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key in _STATE_KEYS and isinstance(value, str):
                out[key] = display_state(value)
            else:
                out[key] = _normalize_states(value)
        return out
    if isinstance(node, list):
        return [_normalize_states(item) for item in node]
    return node


def _kv(node: Any, indent: int = 0) -> str:
    pad = "  " * indent
    if isinstance(node, dict):
        if not node:
            return f"{pad}(empty)"
        lines: list[str] = []
        for key, value in node.items():
            if isinstance(value, (dict, list)):
                lines.append(f"{pad}{key}:")
                lines.append(_kv(value, indent + 1))
            else:
                lines.append(f"{pad}{key}: {value}")
        return "\n".join(lines)
    if isinstance(node, list):
        if not node:
            return f"{pad}(none)"
        lines = []
        for item in node:
            if isinstance(item, (dict, list)):
                lines.append(_kv(item, indent))
            else:
                lines.append(f"{pad}- {item}")
        return "\n".join(lines)
    return f"{pad}{node}"


def _version_bits(row: dict[str, Any]) -> str:
    parts: list[str] = []
    label = row.get("version") or row.get("name") or row.get("label")
    if label:
        parts.append(str(label))
    state = row.get("state") if isinstance(row.get("state"), str) else row.get("status")
    if isinstance(state, str) and state.strip():
        parts.append(display_state(state))
    vid = row.get("version_id") or row.get("id")
    if isinstance(vid, str) and vid.strip():
        parts.append(vid.strip())
    return "  ".join(parts)


def _format_agents(agents: list[Any]) -> str:
    if not agents:
        return "No agents."
    blocks: list[str] = []
    for agent in agents:
        if not isinstance(agent, dict):
            blocks.append(str(agent))
            continue
        slug = str(agent.get("slug") or agent.get("name") or "agent")
        name = agent.get("name")
        title = slug if not isinstance(name, str) or not name.strip() or name.strip() == slug else f"{slug}  {name.strip()}"
        lines = [title]
        versions = agent.get("versions")
        if isinstance(versions, list) and versions:
            for row in versions:
                if isinstance(row, dict):
                    line = _version_bits(row)
                    lines.append(f"  {line}" if line else f"  {_kv(row).strip()}")
                else:
                    lines.append(f"  {row}")
        else:
            line = _version_bits(agent)
            if line and line != slug:
                lines.append(f"  {line}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def _format_keys(keys: list[Any]) -> str:
    if not keys:
        return "No keys."
    lines: list[str] = []
    for row in keys:
        if not isinstance(row, dict):
            lines.append(str(row))
            continue
        ident = str(row.get("id") or row.get("prefix") or "key")
        bits: list[str] = []
        name = row.get("name")
        if isinstance(name, str) and name.strip() and name.strip() != ident:
            bits.append(name.strip())
        bits.append(ident)
        prefix = row.get("prefix")
        if isinstance(prefix, str) and prefix.strip() and prefix.strip() != ident:
            bits.append(prefix.strip())
        state = row.get("status") if isinstance(row.get("status"), str) else row.get("state")
        if isinstance(state, str) and state.strip():
            bits.append(display_state(state))
        lines.append("  ".join(bits))
    return "\n".join(lines)


def _human(payload: object) -> str:
    if isinstance(payload, dict):
        agents = payload.get("agents")
        if isinstance(agents, list):
            return _format_agents(agents)
        keys = payload.get("keys")
        if isinstance(keys, list):
            return _format_keys(keys)
        for key in ("packages", "imported", "drafts", "results"):
            rows = payload.get(key)
            if isinstance(rows, list):
                head = key.replace("_", " ").title()
                body = _format_agents(rows) if rows and isinstance(rows[0], dict) and "slug" in rows[0] else _kv(_normalize_states(rows))
                return f"{head}\n{body}"
        if any(key in payload for key in ("slug", "state", "status", "version", "version_id")):
            title = _version_bits(payload)
            extra = {
                key: value
                for key, value in payload.items()
                if key not in {"slug", "name", "state", "status", "version", "version_id", "id", "label"}
            }
            lines = [line for line in (payload.get("slug") if isinstance(payload.get("slug"), str) else "", title) if line]
            if extra:
                lines.append(_kv(_normalize_states(extra), 1))
            return "\n".join(lines) if lines else _kv(_normalize_states(payload))
        return _kv(_normalize_states(payload))
    if isinstance(payload, list):
        if payload and all(isinstance(item, dict) and ("slug" in item or "version" in item) for item in payload):
            return _format_agents(payload)
        return _kv(_normalize_states(payload))
    return str(payload)


def _emit(payload: object, *, as_json: bool) -> None:
    if as_json:
        typer.echo(_pretty(payload))
        return
    if isinstance(payload, str):
        typer.echo(payload)
        return
    typer.echo(_human(payload))


def _new_secret(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    for field in _SECRET_FIELDS:
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _without_secrets(payload: object) -> object:
    if not isinstance(payload, dict):
        return payload
    return {key: value for key, value in payload.items() if key not in _REDACT_FIELDS}


def _show_secret_once(payload: object, *, as_json: bool) -> str | None:
    """Print the payload with the secret removed, then the secret on its own line."""
    secret = _new_secret(payload)
    _emit(_without_secrets(payload), as_json=as_json)
    if not secret:
        return None
    typer.secho("New key (shown once):", fg="yellow")
    typer.echo(secret)
    return secret


def _read_api_key(api_key: str | None, api_key_stdin: bool) -> str:
    if api_key is not None and api_key_stdin:
        _die(AifluxxError("Pass the key with --api-key or --api-key-stdin, not both."))
    if api_key_stdin:
        key = sys.stdin.read().strip()
        if not key:
            _die(AuthError("api_key is required."))
        return key
    if api_key is not None:
        key = api_key.strip()
        if not key:
            _die(AuthError("api_key is required."))
        return key
    if not _interactive():
        _die(
            AifluxxError(
                "No API key was provided, and stdin is not a terminal.\n"
                f"Usage: {_prog()} login (--api-key KEY | --api-key-stdin) [--platform NAME | --url URL]\n"
                "Pipe a key with --api-key-stdin so the prompt does not read it."
            )
        )
    key = typer.prompt("API key from Home", hide_input=True).strip()
    if not key:
        _die(AuthError("api_key is required."))
    return key


def _org_dict(account: dict[str, Any]) -> dict[str, Any]:
    for key in ("org", "organisation", "organization"):
        value = account.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _iso_currency(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    code = value.strip().upper()
    if len(code) == 3 and code.isalpha():
        return code
    return None


def _find_currency(node: dict[str, Any]) -> str | None:
    for key in ("currency", "default_currency", "billing_currency"):
        code = _iso_currency(node.get(key))
        if code:
            return code
    billing = node.get("billing")
    if isinstance(billing, dict):
        return _iso_currency(billing.get("currency"))
    return None


def _za_token(value: object) -> bool:
    """True for a ZA country, region, or locale such as ``ZA`` or ``en-ZA``."""
    if isinstance(value, dict):
        return any(_za_token(value.get(key)) for key in ("code", "country", "country_code", "id", "region", "name"))
    if not isinstance(value, str):
        return False
    token = " ".join(value.strip().upper().replace("_", " ").split())
    if token in {"ZA", "ZAF", "SOUTH AFRICA"}:
        return True
    parts = [part for part in token.replace(" ", "-").replace("/", "-").split("-") if part]
    if not parts:
        return False
    if parts[0] == "ZA":
        return True
    return len(parts) == 2 and parts[1] == "ZA" and parts[0].isalpha() and len(parts[0]) <= 3


def _is_za_region(node: dict[str, Any]) -> bool:
    return any(_za_token(node.get(key)) for key in ("region", "country", "country_code"))


def currency_for_account(account: object | None) -> str:
    """Currency for a new spec.

    Uses the org currency when ``GET /api/dev/me`` includes one. A ZA-region
    org with no currency uses ZAR. Otherwise USD.
    """
    if not isinstance(account, dict):
        return "USD"
    org = _org_dict(account)
    code = _find_currency(org) or _find_currency(account)
    if code:
        return code
    if _is_za_region(org) or _is_za_region(account):
        return "ZAR"
    return "USD"


def _scaffold_api_url() -> str:
    """API root for template tool ids. Does not call the host.

    Same order as every other command: ``AIFLUXX_API_URL``, then the saved
    login URL, then production.
    """
    return resolve_api_url()


def _account_for_scaffold() -> dict[str, Any] | None:
    """Logged-in ``GET /api/dev/me`` payload, or None when init cannot read it."""
    try:
        creds = load_credentials()
    except AuthError:
        return None
    try:
        return _verify_credentials(resolve_api_url(), creds.api_key)
    except (AifluxxError, OSError, httpx.HTTPError, httpx.StreamError) as exc:
        typer.secho(f"Could not read the org currency ({exc}). Using USD.", err=True, fg="yellow")
        return None


def _account_label(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    org = payload.get("org") or payload.get("organisation") or payload.get("organization")
    if isinstance(org, dict):
        for key in ("name", "slug"):
            value = org.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(org, str) and org.strip():
        return org.strip()
    for key in ("name", "email"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _verify_credentials(url: str, api_key: str) -> dict[str, Any]:
    with AifluxxClient(url, api_key=api_key) as client:
        payload = client.dev.me()
    return payload if isinstance(payload, dict) else {}


def _host_read_tools() -> frozenset[str] | None:
    """Catalogue from the logged-in host, or None to use the bundled list."""
    try:
        creds = load_credentials()
    except AuthError:
        return None
    url = resolve_api_url()
    try:
        with AifluxxClient(url, api_key=creds.api_key) as client:
            names = client.dev.read_tool_names()
    except HostUnavailable:
        return None
    except (AifluxxError, OSError, httpx.HTTPError, httpx.StreamError) as exc:
        typer.secho(
            f"Could not fetch the host tool catalogue ({exc}). Using the bundled list.",
            err=True,
            fg="yellow",
        )
        return None
    if not names:
        typer.secho("The host tool catalogue did not list any tools. Using the bundled list.", err=True, fg="yellow")
        return None
    typer.secho(f"Using the host tool catalogue from {url}.", err=True)
    return names


def _init_usage() -> str:
    prog = _prog()
    return (
        f"Usage: {prog} init SLUG [--template NAME] [--venv | --no-venv] [--cursor-mcp]\n"
        f"       {prog} init --list\n"
        "SLUG is the package folder name, in kebab-case. "
        "In a terminal, omitting SLUG prompts for it. "
        "--venv creates SLUG/.venv. The default is --no-venv. "
        "--cursor-mcp writes SLUG/.cursor/mcp.json and does not put an API key in it."
    )


def _create_venv(root: Path) -> Path:
    """Create ``root/.venv`` with this interpreter. Remove a partial directory on failure."""
    dest = root / ".venv"
    try:
        subprocess.run(
            [sys.executable, "-m", "venv", str(dest)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        shutil.rmtree(dest, ignore_errors=True)
        detail = (exc.stderr or exc.stdout or "").strip()
        message = f"Could not create {dest}."
        if detail:
            message = f"{message} {detail}"
        raise AifluxxError(message) from exc
    except OSError as exc:
        shutil.rmtree(dest, ignore_errors=True)
        raise AifluxxError(f"Could not create {dest}. {exc}") from exc
    return dest


def _resolve_slug(slug: str | None) -> str:
    if slug is not None and slug.strip():
        return slug.strip()
    if _interactive():
        entered = typer.prompt("Package slug (kebab-case)").strip()
        if entered:
            return entered
    typer.echo(_init_usage(), err=True)
    raise typer.Exit(code=1)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def root(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Print API payloads as JSON."),
    _version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Print the aifluxx-sdk version and exit.",
    ),
) -> None:
    """Author an agent package and call the AIFluxx API. Signup stays on the developer site."""
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_output


@app.command()
def login(
    api_key: str | None = typer.Option(None, "--api-key", help="afx_dev_ key from Home. Prompted if omitted."),
    api_key_stdin: bool = typer.Option(
        False,
        "--api-key-stdin",
        help="Read the API key from stdin. Use this when piping a key.",
    ),
    url: str | None = typer.Option(
        None,
        "--url",
        help=(
            "API root. Overrides --platform, AIFLUXX_API_URL, and the saved login URL. "
            "Default https://api.aifluxx.co.za."
        ),
    ),
    platform: str | None = typer.Option(None, "--platform", help=_platform_help()),
) -> None:
    """Check the key with GET /api/dev/me, then save it. Works in any IDE terminal.

    Login defaults to production (platform aifluxx, https://api.aifluxx.co.za).
    For the dev host, run: aifluxx login --platform dev
    """
    key = _read_api_key(api_key, api_key_stdin)
    if not (key.startswith("afx_dev_") or key.startswith("afx_live_") or key.startswith("mcpat_")):
        typer.secho("Keys from Home start with afx_dev_. Subscriber keys start with afx_live_.", fg="yellow")
    try:
        resolved = resolve_api_url(url=url, platform=platform)
    except AifluxxError as exc:
        _die(exc)
    typer.echo(_login_banner(resolved))
    try:
        identity = _verify_credentials(resolved, key)
    except (AifluxxError, OSError, httpx.HTTPError, httpx.StreamError) as exc:
        _die(AifluxxError(f"Login failed, nothing was saved. {exc}"))
    try:
        store = save_credentials(Credentials(url=resolved, api_key=key))
    except (AifluxxError, OSError) as exc:
        _die(exc)
    label = _account_label(identity)
    verified = f"Verified {resolved}" + (f" ({label})" if label else "") + "."
    typer.echo(verified)
    typer.echo(f"Saved {store}. This file is on your machine, not in the package repo.")


@app.command("init")
def init_cmd(
    ctx: typer.Context,
    slug: str | None = typer.Argument(
        None,
        help="Package folder name, kebab-case. Prompted when omitted in a terminal.",
    ),
    template: str = typer.Option(DEFAULT_TEMPLATE, "--template", "-t", help=template_option_help()),
    dest: Path | None = typer.Option(None, "--dest", help="Parent folder. Defaults to the current directory."),
    list_templates: bool = typer.Option(False, "--list", help="List starter templates and do not write a package."),
    venv: bool = typer.Option(
        False,
        "--venv/--no-venv",
        help="Create SLUG/.venv with python -m venv. Default --no-venv: do not create one.",
    ),
    cursor_mcp: bool = typer.Option(
        False,
        "--cursor-mcp",
        help="Also write .cursor/mcp.json for the local aifluxx MCP server. The file does not contain an API key.",
    ),
    json_output: bool = _json_option(),
) -> None:
    """Scaffold a package in your repo. git push still goes to GitHub or GitLab."""
    api_url = _scaffold_api_url()
    if list_templates:
        rows = template_rows(api_url=api_url)
        if _as_json(ctx, json_output):
            typer.echo(_pretty(rows))
            return
        for row in rows:
            tools = ", ".join(row["tools"])
            label = row["template"]
            if row["default"]:
                label = f"{label} [default]"
            typer.echo(f"{label}  {row['title']}  ({row['category']})")
            typer.echo(f"  {row['description']}")
            typer.echo(f"  tools: {tools}")
            for alias in row["aliases"]:
                typer.echo(f"  alias: {alias}")
        return
    try:
        chosen = get_template(template)
        folder = _resolve_slug(slug)
    except AifluxxError as exc:
        _die(exc)
    root = (dest or Path.cwd()).resolve() / folder
    if root.exists() and any(root.iterdir()):
        _die(AifluxxError(f"{root} already exists and is not empty."))
    root.mkdir(parents=True, exist_ok=True)
    currency = currency_for_account(_account_for_scaffold())
    (root / "spec.yaml").write_text(
        render_spec(folder, chosen, currency=currency, api_url=api_url),
        encoding="utf-8",
    )
    (root / "instructions.md").write_text(chosen.instructions, encoding="utf-8")
    (root / "README.md").write_text(f"# {slug_to_name(folder)}\n\n{chosen.description}\n", encoding="utf-8")
    (root / "samples.yaml").write_text("prompts:\n  - Summarise what you can already see.\n", encoding="utf-8")
    from aifluxx_sdk.end_to_end import write_end_to_end

    write_end_to_end(root)
    if venv:
        try:
            created = _create_venv(root)
        except AifluxxError as exc:
            _die(exc)
        typer.echo(f"Created {created}. Do not commit it. `aifluxx push` leaves it out.")
    if cursor_mcp:
        from aifluxx_sdk.mcp_server import cursor_mcp_document

        mcp_file = root / ".cursor" / "mcp.json"
        mcp_file.parent.mkdir(parents=True, exist_ok=True)
        mcp_file.write_text(cursor_mcp_document(), encoding="utf-8")
        typer.echo(f"Wrote {mcp_file}. It does not contain an API key.")
    typer.echo(
        f"Created {root}. The first commit includes the GitHub Action. "
        "A push to main validates, pushes a Draft, and submits it for review."
    )


@app.command()
def validate(path: Path | None = typer.Argument(None, help="Package folder. Defaults to the current directory.")) -> None:
    """Check the package. Uses the host tool catalogue when you are logged in.

    Skips .aifluxx/, .venv/, the legacy metadata directory, a top-level sdk/ directory,
    any *.egg-info path, and paths listed in .aifluxxignore. push leaves those paths out.
    """
    try:
        directory = _package_dir(path)
        tools = _host_read_tools()
        report = validate_package(directory, read_tools=tools)
    except AifluxxError as exc:
        _die(exc)
    for row in report.findings:
        colour = "red" if row.severity == "error" else "yellow"
        typer.secho(f"{row.severity.upper()} {row.code}  {row.path}  {row.note}", fg=colour)
    if report.ok:
        slug = report.spec.get("slug") or "package"
        typer.echo(f"OK  {slug} {report.spec.get('version', '')}".rstrip())
        return
    raise typer.Exit(code=1)


@app.command()
def push(
    ctx: typer.Context,
    path: Path | None = typer.Argument(None, help="Package folder. Defaults to the current directory."),
    json_output: bool = _json_option(),
) -> None:
    """Upload the folder you have open. Creates a Draft. Does not git push.

    The archive leaves out the same paths validate skips, including .aifluxxignore entries.
    """
    try:
        package = _package_dir(path)
        with _client() as client:
            payload = client.dev.push(package)
    except (AifluxxError, OSError, httpx.HTTPError, httpx.StreamError) as exc:
        _die(exc)
    _emit(payload, as_json=_as_json(ctx, json_output))


def _package_for_slug(path: Path | None, slug: str | None) -> Path | None:
    if path is not None:
        return _package_dir(path)
    cwd = Path.cwd()
    if not (cwd / "spec.yaml").is_file():
        return None
    if slug is None:
        return cwd
    report = validate_package(cwd)
    spec_slug = str(report.spec.get("slug") or cwd.name)
    return cwd if spec_slug == slug else None


_RUN_FAILURE_STATES = frozenset({"failed", "error", "errored"})


def _json_event(line: str) -> dict[str, Any] | None:
    text = line.strip()
    if text.startswith("data:"):
        text = text[5:].strip()
    if not text or text == "[DONE]":
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _state_name(payload: dict[str, Any]) -> str | None:
    for key in ("state", "status"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.replace("_", " ").replace("-", " ").split()).lower()
    return None


def _error_text(payload: dict[str, Any]) -> str | None:
    for key in ("error", "detail", "message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = _error_text(value)
            if nested:
                return nested
    return None


def _outcome_from_payload(payload: dict[str, Any]) -> tuple[str, str | None] | None:
    """Run state and error text from one stream object."""
    state = _state_name(payload)
    error = _error_text(payload)
    if state is None:
        for key in ("run", "result", "data"):
            child = payload.get(key)
            if isinstance(child, dict):
                found = _outcome_from_payload(child)
                if found is not None:
                    nested_state, nested_error = found
                    return nested_state, error or nested_error
        kind = str(payload.get("type") or "").strip().lower().replace("-", " ").replace("_", " ")
        if kind in _RUN_FAILURE_STATES:
            state = kind
    if state is None:
        return None
    return state, error


def _run_line_outcome(line: str) -> tuple[str, str | None] | None:
    """State and error from one stream line, or None when the line has no run state."""
    payload = _json_event(line)
    if payload is None:
        return None
    return _outcome_from_payload(payload)


def _run_failure_message(state: str, error: str | None) -> str:
    if state == "failed":
        label, plain = "Failed", "Run failed."
    else:
        label, plain = "Errored", "Run errored."
    if error:
        return f"{label}: {error}"
    return plain


def _run_usage() -> str:
    prog = _prog()
    return (
        f"Usage: {prog} run PROMPT\n"
        f"       {prog} run SLUG PROMPT\n"
        f"       {prog} run --slug SLUG PROMPT\n"
        "Pass a prompt, or pipe one on stdin."
    )


def _run_parts(parts: list[str] | None) -> list[str]:
    """Arguments for run. With none, the prompt is one stdin read, or a usage error."""
    given = [part.strip() for part in (parts or []) if part and part.strip()]
    if given:
        return given
    if not _interactive():
        prompt = sys.stdin.read().strip()
        if prompt:
            return [prompt]
    typer.echo(_run_usage(), err=True)
    raise typer.Exit(code=1)


def _run_target(parts: list[str], slug_opt: str | None, path: Path | None) -> tuple[str, str, Path | None]:
    if len(parts) == 1:
        prompt = parts[0]
        slug = slug_opt
    elif len(parts) == 2:
        slug, prompt = parts
        if slug_opt and slug_opt != slug:
            raise AifluxxError("Pass the slug once, either as the first argument or as --slug.")
    else:
        raise AifluxxError("Usage: aifluxx run PROMPT    or    aifluxx run SLUG PROMPT")
    package = _package_for_slug(path, slug)
    if not slug:
        if package is None:
            raise AifluxxError(
                "Pass the package slug: aifluxx run SLUG PROMPT. "
                "Inside a package directory, aifluxx run PROMPT reads the slug from spec.yaml."
            )
        report = validate_package(package)
        slug = str(report.spec.get("slug") or package.name)
    return slug, prompt, package


@app.command("run")
def run_cmd(
    parts: list[str] | None = typer.Argument(
        None,
        metavar="[SLUG] PROMPT",
        help="Prompt, or slug then prompt. Omit this and pipe a prompt on stdin.",
    ),
    path: Path | None = typer.Option(None, "--path", help="Package folder when you pass only a prompt."),
    slug: str | None = typer.Option(None, "--slug", help="Package slug. Use this or the SLUG argument, not both."),
    version: str | None = typer.Option(
        None,
        "--version",
        help="Version UUID, or a semver to look up. The word latest is never sent to the API.",
    ),
) -> None:
    """Stream a sandbox run. Inside a package, pass the prompt. Otherwise pass SLUG then the prompt.

    With no prompt, a pipe supplies it. A terminal with no prompt prints usage.
    Exits 1 when the stream's final state is failed or errored.
    """
    try:
        package_slug, prompt, package = _run_target(_run_parts(parts), slug, path)
        lock = load_lock(package) if package is not None else None
        outcome: tuple[str, str | None] | None = None
        with _client() as client:
            for line in client.dev.run(package_slug, prompt, version=version, lock=lock):
                typer.echo(line)
                parsed = _run_line_outcome(line)
                if parsed is not None:
                    outcome = parsed
        if outcome is not None and outcome[0] in _RUN_FAILURE_STATES:
            _die(AifluxxError(_run_failure_message(outcome[0], outcome[1])))
    except (AifluxxError, OSError, httpx.HTTPError, httpx.StreamError) as exc:
        _die(exc)


@app.command()
def submit(
    ctx: typer.Context,
    path: Path | None = typer.Argument(None, help="Package folder. Defaults to the current directory."),
    version: str | None = typer.Option(
        None,
        "--version",
        help="Version UUID, or a semver to look up. The word latest is never sent to the API.",
    ),
    json_output: bool = _json_option(),
) -> None:
    """Submit a draft for review. The version path is a UUID, looked up when you do not pass one."""
    try:
        package = _package_dir(path)
        report = validate_package(package)
        slug = str(report.spec.get("slug") or package.name)
        lock = load_lock(package)
        with _client() as client:
            payload = client.dev.submit(slug, version, lock=lock)
    except (AifluxxError, OSError, httpx.HTTPError, httpx.StreamError) as exc:
        _die(exc)
    _emit(payload, as_json=_as_json(ctx, json_output))


@app.command()
def status(
    ctx: typer.Context,
    json_output: bool = _json_option(),
) -> None:
    """List org agents, versions, and states."""
    try:
        with _client() as client:
            payload = client.dev.status()
    except (AifluxxError, OSError, httpx.HTTPError, httpx.StreamError) as exc:
        _die(exc)
    _emit(payload, as_json=_as_json(ctx, json_output))


@app.command("import-git")
def import_git(
    ctx: typer.Context,
    repo_url: str = typer.Argument(..., help="GitHub or GitLab URL you already pushed."),
    token: str | None = typer.Option(None, "--token", help="Optional clone token. Never stored in the package."),
    ref: str | None = typer.Option(None, "--ref"),
    json_output: bool = _json_option(),
) -> None:
    """Create Drafts from a repository you own. git remotes stay yours."""
    try:
        with _client() as client:
            payload = client.dev.import_git(repo_url, token=token, ref=ref)
    except (AifluxxError, OSError, httpx.HTTPError, httpx.StreamError) as exc:
        _die(exc)
    _emit(payload, as_json=_as_json(ctx, json_output))


@keys_app.command("list")
def keys_list(
    ctx: typer.Context,
    json_output: bool = _json_option(),
) -> None:
    """Show developer API keys for the logged-in account. Secrets are not returned."""
    try:
        with _client() as client:
            payload = client.dev.list_keys()
    except (AifluxxError, OSError, httpx.HTTPError, httpx.StreamError) as exc:
        _die(exc)
    _emit(payload, as_json=_as_json(ctx, json_output))


@keys_app.command("create")
def keys_create(
    ctx: typer.Context,
    name: str | None = typer.Option(
        None,
        "--name",
        help="Key name. Omit it and the API uses Sandbox key. At most 80 characters.",
    ),
    save: bool = typer.Option(False, "--save", help="Write the new secret into the local credentials file."),
    json_output: bool = _json_option(),
) -> None:
    """Create a developer API key with POST /api/dev/keys. The secret is shown once."""
    try:
        with _client() as client:
            payload = client.dev.create_key(name)
    except (AifluxxError, OSError, httpx.HTTPError, httpx.StreamError) as exc:
        _die(exc)
    secret = _show_secret_once(payload, as_json=_as_json(ctx, json_output))
    if not secret or not save:
        return
    try:
        current = load_credentials()
        store = save_credentials(Credentials(url=current.url, api_key=secret))
    except (AifluxxError, OSError) as exc:
        _die(exc)
    typer.echo(f"Updated {store}.")


@keys_app.command("rotate")
def keys_rotate(
    ctx: typer.Context,
    key_id: str = typer.Argument(..., help="Key id from `aifluxx keys list`."),
    save: bool = typer.Option(False, "--save", help="Write the new secret into the local credentials file."),
    json_output: bool = _json_option(),
) -> None:
    """Rotate one key. The new secret is shown once."""
    try:
        with _client() as client:
            payload = client.dev.rotate_key(key_id)
    except (AifluxxError, OSError, httpx.HTTPError, httpx.StreamError) as exc:
        _die(exc)
    secret = _show_secret_once(payload, as_json=_as_json(ctx, json_output))
    if not secret or not save:
        return
    try:
        current = load_credentials()
        store = save_credentials(Credentials(url=current.url, api_key=secret))
    except (AifluxxError, OSError) as exc:
        _die(exc)
    typer.echo(f"Updated {store}.")


@keys_app.command("revoke")
def keys_revoke(
    ctx: typer.Context,
    key_id: str = typer.Argument(..., help="Key id from `aifluxx keys list`."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Revoke without a confirmation prompt."),
    json_output: bool = _json_option(),
) -> None:
    """Revoke one key. It stops working immediately."""
    if not yes and not typer.confirm(f"Revoke key {key_id}?"):
        raise typer.Exit(code=1)
    try:
        with _client() as client:
            payload = client.dev.revoke_key(key_id)
    except (AifluxxError, OSError, httpx.HTTPError, httpx.StreamError) as exc:
        _die(exc)
    if _as_json(ctx, json_output):
        _emit(payload, as_json=True)
        return
    if isinstance(payload, dict) and payload.get("revoked") is True:
        typer.echo(f"Revoked {payload.get('id') or key_id}.")
        return
    _emit(payload, as_json=False)


class CompanionGroup(typer.core.TyperGroup):
    """``status`` is a subcommand. Any other words are the chat message."""

    def invoke(self, ctx: typer.Context) -> Any:
        pending = [*getattr(ctx, "_protected_args", []), *list(ctx.args)]
        if pending and self.get_command(ctx, pending[0]) is None:
            obj = ctx.ensure_object(dict)
            obj["companion_message"] = " ".join(pending)
            ctx._protected_args = []
            ctx.args = []
        return super().invoke(ctx)


_COMPANION_MODES = ("build", "config")
_FOCUS = {
    "build": (
        "Focus: build. UI design and wiring — starter UI screens, components, A2UI, "
        "and how they connect to the agent."
    ),
    "config": "Focus: config. Agent instructions, the system prompt, tools, and connectors.",
}
_LAYOUT_EDITOR_URL = "http://127.0.0.1:5173/?layout=1"

companion_app = typer.Typer(
    cls=CompanionGroup,
    no_args_is_help=False,
    invoke_without_command=True,
    help="Talk to the AIFluxx companion. `aifluxx chat` is the same chat.",
)


def _normalize_mode(value: str) -> str:
    key = (value or "").strip().lower()
    if key not in _COMPANION_MODES:
        raise AifluxxError("--mode must be build or config.")
    return key


def _with_focus(mode: str, text: str) -> str:
    """Prefix a short focus line so a host that ignores ``mode`` still follows it."""
    return f"{_FOCUS[mode]}\n\n{text.strip()}"


def _saved_key() -> str:
    try:
        return load_credentials().api_key
    except AuthError:
        return ""


def _redact_text(text: str, secret: str) -> str:
    from aifluxx_sdk.client import scrub_secret

    cleaned = scrub_secret(text)
    if secret and secret in cleaned:
        cleaned = cleaned.replace(secret, "[redacted]")
    return cleaned


def _project_dir() -> Path | None:
    cwd = Path.cwd()
    if (cwd / "spec.yaml").is_file():
        return cwd
    return None


def _slug_from_project(directory: Path) -> str:
    import yaml

    spec_path = directory / "spec.yaml"
    try:
        loaded = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise AifluxxError(f"Could not read {spec_path}.") from exc
    except yaml.YAMLError as exc:
        raise AifluxxError(f"Could not read {spec_path}.") from exc
    if not isinstance(loaded, dict):
        raise AifluxxError("spec.yaml must be a mapping.")
    slug = loaded.get("slug")
    if isinstance(slug, str) and slug.strip():
        return slug.strip()
    return directory.name


def _resolve_project_slug(project: str | None) -> tuple[str, Path | None]:
    """Slug from ``--project`` or from the package ``spec.yaml`` used by init, validate, and push."""
    directory = _project_dir()
    if project is not None and project.strip():
        return project.strip(), directory
    if directory is None:
        raise AifluxxError(
            "Pass --project SLUG, or run this inside an aifluxx package (a folder with spec.yaml)."
        )
    return _slug_from_project(directory), directory


def _companion_record(payload: dict[str, Any]) -> dict[str, Any]:
    markers = ("version", "approval", "approved", "servable", "region_endpoint", "regionEndpoint", "limits", "limit")
    if any(key in payload for key in markers):
        return payload
    for wrapper in ("companion", "data", "status"):
        child = payload.get(wrapper)
        if isinstance(child, dict):
            return child
    return payload


def _format_companion_status(payload: dict[str, Any]) -> str:
    row = _companion_record(payload)
    version = row.get("version")
    approval = row.get("approval")
    if approval is None:
        approval = row.get("approved")
    servable = row.get("servable")
    if servable is None:
        servable = row.get("is_servable")
    endpoint = row.get("region_endpoint") or row.get("regionEndpoint") or row.get("endpoint")
    limits = row.get("limits")
    if limits is None:
        limits = row.get("limit")
    if isinstance(approval, str):
        approval_text = display_state(approval)
    elif isinstance(approval, bool):
        approval_text = "Approved" if approval else "Not approved"
    elif approval in (None, ""):
        approval_text = "—"
    else:
        approval_text = str(approval)
    if isinstance(servable, bool):
        servable_text = "yes" if servable else "no"
    elif servable in (None, ""):
        servable_text = "—"
    else:
        servable_text = str(servable)
    lines = [
        "Companion",
        f"  version: {version if version not in (None, '') else '—'}",
        f"  approval: {approval_text}",
        f"  servable: {servable_text}",
        f"  region endpoint: {endpoint if endpoint else '—'}",
        "  limits:",
    ]
    if isinstance(limits, dict) and limits:
        lines.extend(f"    {key}: {value}" for key, value in limits.items())
    elif isinstance(limits, list) and limits:
        lines.extend(f"    - {item}" for item in limits)
    elif limits not in (None, "", {}, []):
        lines.append(f"    {limits}")
    else:
        lines.append("    —")
    return "\n".join(lines)


def _tool_line(tools: object) -> str | None:
    if not isinstance(tools, list) or not tools:
        return None
    names: list[str] = []
    for item in tools:
        if isinstance(item, str) and item.strip():
            names.append(item.strip())
        elif isinstance(item, dict):
            label = item.get("name") if isinstance(item.get("name"), str) else item.get("id")
            if isinstance(label, str) and label.strip():
                names.append(label.strip())
    if not names:
        return None
    return "Tools: " + ", ".join(names)


def _print_companion_reply(payload: dict[str, Any], *, secret: str, as_json: bool) -> bool:
    """Print one companion response. Return True when the host refused."""
    if as_json:
        typer.echo(_redact_text(json.dumps(payload, indent=2), secret))
    refusal = payload.get("refusal")
    refused = refusal is True or (isinstance(refusal, str) and bool(refusal.strip()))
    if as_json:
        return refused
    if refusal is True:
        typer.secho("Refused.", err=True, fg="red")
    elif isinstance(refusal, str) and refusal.strip():
        typer.secho(f"Refused: {_redact_text(refusal.strip(), secret)}", err=True, fg="red")
    reply = payload.get("reply")
    if isinstance(reply, str) and reply.strip():
        typer.echo(_redact_text(reply.strip(), secret))
    elif not refused:
        typer.echo("(No reply.)")
    tool_line = _tool_line(payload.get("tools"))
    if tool_line:
        typer.echo(_redact_text(tool_line, secret))
    return refused


def _send_companion(client: AifluxxClient, *, text: str, slug: str, mode: str, secret: str, as_json: bool) -> bool:
    payload = client.companion.send(_with_focus(mode, text), project_slug=slug, mode=mode)
    return _print_companion_reply(payload, secret=secret, as_json=as_json)


def _open_layout_editor() -> str:
    """Open the Starter UI in layout-edit mode. This does not run a shell."""
    import webbrowser

    try:
        webbrowser.open(_LAYOUT_EDITOR_URL)
    except Exception:
        pass
    return _LAYOUT_EDITOR_URL


def _layout_instructions(project: Path) -> str:
    return (
        "Layout edit runs in the Starter UI. A terminal cannot drag.\n"
        f"Open {_LAYOUT_EDITOR_URL}\n"
        "Turn on Layout edit, drag or resize the blocks, then Save layout.\n"
        f"This chat watches {project / 'aifluxx.layout.json'} and asks before it writes wiring.\n"
        "Start the UI with the package path. This command does not run a shell:\n"
        f"  AIFLUXX_PROJECT={project} AIFLUXX_LAYOUT_EDIT=1 npm run dev"
    )


def _consume_layout_save(
    client: AifluxxClient,
    *,
    project: Path,
    snapshot: str,
    slug: str,
    secret: str,
    as_json: bool,
) -> str:
    """Send a layout diff when the file changed. Return the snapshot to keep."""
    from aifluxx_sdk.layout import (
        apply_writes,
        format_changes,
        layout_changes,
        load_layout_text,
        proposed_writes,
        read_layout_file,
    )

    current, document = read_layout_file(project)
    if current == snapshot:
        return snapshot
    try:
        before = load_layout_text(snapshot)
    except AifluxxError:
        before = document
    changes = layout_changes(before, document)
    if not changes:
        return current
    preview = format_changes(changes)
    typer.echo("Layout saved.")
    typer.echo(preview)
    prompt = (
        "The developer saved a Starter UI layout change.\n"
        f"{preview}\n"
        "Suggest wiring and code updates that match this layout. "
        "File edits, if any, go in an aifluxx-files fence as JSON "
        '{"files":[{"path":"instructions.md","content":"..."}]}.'
    )
    try:
        payload = client.companion.send(_with_focus("build", prompt), project_slug=slug, mode="build")
    except (AifluxxError, OSError, httpx.HTTPError, httpx.StreamError) as exc:
        typer.secho(_redact_text(str(exc), secret), err=True, fg="red")
        return current
    if _print_companion_reply(payload, secret=secret, as_json=as_json):
        typer.echo("Not applied.")
        return current
    reply = payload.get("reply") if isinstance(payload.get("reply"), str) else ""
    writes, skipped = proposed_writes(document, reply)
    writes = [(relative, _redact_text(content, secret)) for relative, content in writes]
    for note in skipped:
        typer.secho(_redact_text(note, secret), err=True, fg="yellow")
    typer.echo("Project files:")
    for relative, _content in writes:
        typer.echo(f"  {relative}")
    answer = input("Apply these project file updates? [y/N] ").strip().lower()
    if answer not in {"y", "yes"}:
        typer.echo("Not applied.")
        return current
    try:
        apply_writes(project, writes)
    except (AifluxxError, OSError) as exc:
        typer.secho(_redact_text(str(exc), secret), err=True, fg="red")
        return current
    for relative, _content in writes:
        typer.echo(f"Wrote {relative}.")
    return current


def _repl(
    client: AifluxxClient,
    *,
    slug: str,
    mode: str,
    project: Path | None,
    secret: str,
    as_json: bool,
) -> None:
    from aifluxx_sdk.layout import read_layout_file

    watching = False
    snapshot = ""
    typer.echo(f"Companion chat ({mode}). /build /config /mode /layout /exit. Ctrl-D exits.")
    while True:
        try:
            line = input(f"{mode}> ")
        except EOFError:
            typer.echo()
            return
        text = line.strip()
        if not text:
            if watching and project is not None:
                snapshot = _consume_layout_save(
                    client, project=project, snapshot=snapshot, slug=slug, secret=secret, as_json=as_json
                )
            continue
        if text == "/exit":
            return
        if text == "/mode":
            typer.echo(f"Mode is {mode}.")
            continue
        if text == "/build":
            mode = "build"
            typer.echo("Mode is build.")
            continue
        if text == "/config":
            mode = "config"
            typer.echo("Mode is config.")
            continue
        if text == "/layout":
            if mode != "build":
                typer.echo("Layout edit is a build-mode tool. Switch with /build.")
                continue
            if project is None:
                typer.echo("Run /layout inside the package folder (the one with spec.yaml) so writes stay in the project.")
                continue
            snapshot, _document = read_layout_file(project)
            watching = True
            typer.echo(_layout_instructions(project))
            _open_layout_editor()
            continue
        if text.startswith("/"):
            typer.echo("Unknown command. Use /build, /config, /mode, /layout, or /exit.")
            continue
        if watching and project is not None:
            snapshot = _consume_layout_save(
                client, project=project, snapshot=snapshot, slug=slug, secret=secret, as_json=as_json
            )
        try:
            _send_companion(client, text=text, slug=slug, mode=mode, secret=secret, as_json=as_json)
        except (AifluxxError, OSError, httpx.HTTPError, httpx.StreamError) as exc:
            typer.secho(_redact_text(str(exc), secret), err=True, fg="red")


def _chat_usage() -> str:
    return (
        "Usage: aifluxx chat [MESSAGE]\n"
        "       aifluxx companion [MESSAGE]\n"
        "Omit MESSAGE in a terminal to open the chat. /exit or Ctrl-D leaves."
    )


def _chat_session(
    ctx: typer.Context,
    message: str | None,
    project: str | None,
    mode: str,
    json_output: bool,
) -> None:
    try:
        chosen = _normalize_mode(mode)
        slug, directory = _resolve_project_slug(project)
    except AifluxxError as exc:
        _die(exc)
    secret = _saved_key()
    as_json = _as_json(ctx, json_output)
    if message is not None and message.strip():
        try:
            with _client() as client:
                refused = _send_companion(
                    client, text=message, slug=slug, mode=chosen, secret=secret, as_json=as_json
                )
        except (AifluxxError, OSError, httpx.HTTPError, httpx.StreamError) as exc:
            _die(AifluxxError(_redact_text(str(exc), secret)))
        if refused:
            raise typer.Exit(code=1)
        return
    if not _interactive():
        typer.echo(_chat_usage(), err=True)
        raise typer.Exit(code=1)
    try:
        with _client() as client:
            _repl(client, slug=slug, mode=chosen, project=directory, secret=secret, as_json=as_json)
    except (AifluxxError, OSError, httpx.HTTPError, httpx.StreamError) as exc:
        _die(AifluxxError(_redact_text(str(exc), secret)))


def _project_option() -> Any:
    return typer.Option(None, "--project", help="Package slug. Defaults to the slug in spec.yaml.")


def _mode_option() -> Any:
    return typer.Option(
        "build",
        "--mode",
        help="build (UI and wiring) or config (instructions, tools, connectors). Default: build.",
    )


def _message_argument() -> Any:
    return typer.Argument(None, help="Send one message and exit. Omit this in a terminal to chat.")


@companion_app.callback(invoke_without_command=True)
def companion_cmd(
    ctx: typer.Context,
    project: str | None = _project_option(),
    mode: str = _mode_option(),
    json_output: bool = _json_option(),
) -> None:
    """Chat with the companion. `aifluxx chat` is the same command. `companion status` prints host status.

    A message after the options is sent once. With no message, a terminal opens the chat.
    """
    if ctx.invoked_subcommand is not None:
        return
    message = None
    if isinstance(ctx.obj, dict):
        message = ctx.obj.pop("companion_message", None)
    _chat_session(ctx, message if isinstance(message, str) else None, project, mode, json_output)


@companion_app.command("status")
def companion_status_cmd(
    ctx: typer.Context,
    json_output: bool = _json_option(),
) -> None:
    """Show companion version, approval, servable, region endpoint, and limits."""
    secret = _saved_key()
    try:
        with _client() as client:
            payload = client.companion.status()
    except (AifluxxError, OSError, httpx.HTTPError, httpx.StreamError) as exc:
        _die(AifluxxError(_redact_text(str(exc), secret)))
    if _as_json(ctx, json_output):
        typer.echo(_redact_text(json.dumps(payload, indent=2), secret))
        return
    typer.echo(_redact_text(_format_companion_status(payload), secret))


@app.command("chat")
def chat_cmd(
    ctx: typer.Context,
    message: str | None = _message_argument(),
    project: str | None = _project_option(),
    mode: str = _mode_option(),
    json_output: bool = _json_option(),
) -> None:
    """Chat with the companion. Alias of `aifluxx companion`."""
    _chat_session(ctx, message, project, mode, json_output)


app.add_typer(companion_app, name="companion")


STARTER_UI_DIR = Path(__file__).resolve().parent / "starter_ui"


@app.command("starter-ui")
def starter_ui_cmd(
    dest: Path = typer.Argument(Path("aifluxx-starter-ui"), help="Folder to create. Defaults to ./aifluxx-starter-ui."),
    force: bool = typer.Option(False, "--force", "-f", help="Write into a non-empty folder, overwriting files."),
) -> None:
    """Copy the bundled AIFluxx Starter UI (local developer console) into DEST."""
    if not STARTER_UI_DIR.is_dir():
        _die(AifluxxError("The starter UI is missing from this install. Reinstall aifluxx-sdk."))
    root = dest.resolve()
    if root.exists() and not root.is_dir():
        _die(AifluxxError(f"{root} exists and is not a folder."))
    if root.exists() and any(root.iterdir()) and not force:
        _die(AifluxxError(f"{root} already exists and is not empty. Pass --force to overwrite."))
    shutil.copytree(STARTER_UI_DIR, root, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "UPSTREAM"))
    typer.echo(f"Created {root}. Next: cd {dest} && npm install && npm run dev")


@app.command("source")
def source_cmd(
    dest: Path = typer.Argument(
        Path("aifluxx-sdk"),
        help="Folder to create. Defaults to ./aifluxx-sdk.",
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Write into a non-empty folder, overwriting files."),
) -> None:
    """Copy the installed SDK source tree into DEST.

    Writes package code, templates, the starter UI, README, pyproject.toml,
    LICENSE, and examples. A non-empty folder is left unchanged unless you
    pass --force.
    """
    try:
        root = copy_sdk_source(dest, force=force)
    except AifluxxError as exc:
        _die(exc)
    typer.echo(f"Created {root}.")


@app.command("mcp")
def mcp_cmd(
    http: bool = typer.Option(False, "--http", help="Serve streamable HTTP instead of stdio."),
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host for --http."),
    port: int = typer.Option(8000, "--port", help="Port for --http."),
) -> None:
    """Run the developer-platform MCP server.

    Stdio is the default. Auth is AIFLUXX_API_KEY or the key from `aifluxx login`.
    The key is not printed. Install the extra with pip install 'aifluxx-sdk[mcp]'.
    """
    argv = ["--host", host, "--port", str(port)]
    if http:
        argv.insert(0, "--http")
    from aifluxx_sdk.mcp_server import main as mcp_main

    try:
        mcp_main(argv)
    except SystemExit as exc:
        if exc.code not in (None, 0):
            _die(AifluxxError(str(exc.code) if not isinstance(exc.code, int) else "The MCP server stopped."))
        raise


def main() -> None:
    app()


if __name__ == "__main__":
    main()
