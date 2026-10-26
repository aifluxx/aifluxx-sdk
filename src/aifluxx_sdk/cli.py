"""`aifluxx` CLI. `truest` is a deprecated console-script alias."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, NoReturn

import httpx
import typer

from aifluxx_sdk.client import AifluxxClient
from aifluxx_sdk.credentials import (
    PLATFORMS,
    Credentials,
    dev_key_on_prod_host,
    load_credentials,
    normalize_api_url,
    resolve_api_url,
    save_credentials,
)
from aifluxx_sdk.exceptions import AifluxxError, AuthError, HostUnavailable
from aifluxx_sdk.lockfile import load_lock
from aifluxx_sdk.package import validate_package
from aifluxx_sdk.templates import TEMPLATES, get_template, render_spec, slug_to_name

_SECRET_FIELDS = ("api_key", "key", "secret", "token")
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
    stem = Path(sys.argv[0]).name.split(".")[0].lower()
    return stem if stem in {"aifluxx", "truest"} else "aifluxx"


def _platform_help() -> str:
    ordered = ("aifluxx", "truest", "dev", "truest-dev")
    bits = [f"{name} ({PLATFORMS[name]})" for name in ordered]
    return "Named host: " + "; ".join(bits) + "."


app = typer.Typer(
    name=_prog(),
    no_args_is_help=True,
    add_completion=False,
    help="Author an agent package and call the AIfluxx API. Signup stays on the developer site.",
)
keys_app = typer.Typer(no_args_is_help=True, help="List, rotate, or revoke developer API keys.")
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
    override = os.environ.get("AIFLUXX_API_URL", "").strip()
    url = normalize_api_url(override) if override else creds.url
    _warn_dev_key(creds.api_key, url)
    return AifluxxClient(url, api_key=creds.api_key)


def _warn_dev_key(api_key: str, url: str) -> None:
    if not dev_key_on_prod_host(api_key, url):
        return
    typer.secho(
        f"WARNING: this afx_dev_ key is pointed at a production host ({url}).\n"
        "Dev keys belong on the dev platform. Log in again with --platform dev "
        f"({PLATFORMS['dev']}) or --platform truest-dev ({PLATFORMS['truest-dev']}).",
        err=True,
        fg="red",
        bold=True,
    )


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
        bits = [ident]
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


def _retired_host_in_selection(url: str | None, platform: str | None) -> bool:
    if url is not None and url.strip():
        return "api.truest.biz" in url
    if platform is not None and platform.strip():
        return False
    return "api.truest.biz" in os.environ.get("AIFLUXX_API_URL", "")


def _new_secret(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    for field in _SECRET_FIELDS:
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


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
    override = os.environ.get("AIFLUXX_API_URL", "").strip()
    url = normalize_api_url(override) if override else creds.url
    _warn_dev_key(creds.api_key, url)
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
        f"Usage: {prog} init SLUG [--template NAME]\n"
        f"       {prog} init --list\n"
        "SLUG is the package folder name, in kebab-case. "
        "In a terminal, omitting SLUG prompts for it."
    )


def _resolve_slug(slug: str | None) -> str:
    if slug is not None and slug.strip():
        return slug.strip()
    if _interactive():
        entered = typer.prompt("Package slug (kebab-case)").strip()
        if entered:
            return entered
    typer.echo(_init_usage(), err=True)
    raise typer.Exit(code=1)


@app.callback()
def root(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Print API payloads as JSON."),
) -> None:
    """Author an agent package and call the AIfluxx API. Signup stays on the developer site."""
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
        help="API root. Overrides --platform and AIFLUXX_API_URL. Default https://api.aifluxx.co.za.",
    ),
    platform: str | None = typer.Option(None, "--platform", help=_platform_help()),
) -> None:
    """Check the key with GET /api/dev/me, then save it. Works in any IDE terminal."""
    key = _read_api_key(api_key, api_key_stdin)
    if not (key.startswith("afx_dev_") or key.startswith("afx_live_") or key.startswith("mcpat_")):
        typer.secho("Keys from Home start with afx_dev_. Subscriber keys start with afx_live_.", fg="yellow")
    try:
        resolved = resolve_api_url(url=url, platform=platform)
    except AifluxxError as exc:
        _die(exc)
    if _retired_host_in_selection(url, platform):
        typer.secho(
            f"api.truest.biz is retired. Using {resolved}. For the Truest profile, pass --platform truest.",
            fg="yellow",
        )
    _warn_dev_key(key, resolved)
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
    template: str = typer.Option("compliance", "--template", "-t", help="Starter: " + ", ".join(sorted(TEMPLATES))),
    dest: Path | None = typer.Option(None, "--dest", help="Parent folder. Defaults to the current directory."),
    list_templates: bool = typer.Option(False, "--list", help="List starter templates and do not write a package."),
    json_output: bool = _json_option(),
) -> None:
    """Scaffold a package in your repo. git push still goes to GitHub or GitLab."""
    if list_templates:
        rows = [
            {
                "template": name,
                "title": chosen.name,
                "category": chosen.category,
                "description": chosen.description.strip(),
                "tools": list(chosen.tools),
            }
            for name, chosen in ((key, TEMPLATES[key]) for key in sorted(TEMPLATES))
        ]
        if _as_json(ctx, json_output):
            typer.echo(_pretty(rows))
            return
        for row in rows:
            tools = ", ".join(row["tools"])
            typer.echo(f"{row['template']}  {row['title']}  ({row['category']})")
            typer.echo(f"  {row['description']}")
            typer.echo(f"  tools: {tools}")
            if row["template"] == "compliance":
                typer.echo("  alias: compliance-checklist")
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
    (root / "spec.yaml").write_text(render_spec(folder, chosen), encoding="utf-8")
    (root / "instructions.md").write_text(chosen.instructions, encoding="utf-8")
    (root / "README.md").write_text(f"# {slug_to_name(folder)}\n\n{chosen.description}\n", encoding="utf-8")
    (root / "samples.yaml").write_text("prompts:\n  - Summarise what you can already see.\n", encoding="utf-8")
    typer.echo(f"Created {root}. Commit this folder to your Git repo, then `aifluxx push` or Import from Git.")


@app.command()
def validate(path: Path | None = typer.Argument(None, help="Package folder. Defaults to the current directory.")) -> None:
    """Check the package. Uses the host tool catalogue when you are logged in."""
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
    """Upload the folder you have open. Creates a Draft. Does not git push."""
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
    parts: list[str] = typer.Argument(..., metavar="[SLUG] PROMPT", help="Prompt, or slug then prompt."),
    path: Path | None = typer.Option(None, "--path", help="Package folder when you pass only a prompt."),
    slug: str | None = typer.Option(None, "--slug", help="Package slug. Use this or the SLUG argument, not both."),
    version: str | None = typer.Option(
        None,
        "--version",
        help="Version UUID, or a semver to look up. The word latest is never sent to the API.",
    ),
) -> None:
    """Stream a sandbox run. Inside a package, pass the prompt. Otherwise pass SLUG then the prompt."""
    try:
        package_slug, prompt, package = _run_target(parts, slug, path)
        lock = load_lock(package) if package is not None else None
        with _client() as client:
            for line in client.dev.run(package_slug, prompt, version=version, lock=lock):
                typer.echo(line)
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
    secret = _new_secret(payload)
    as_json = _as_json(ctx, json_output)
    if isinstance(payload, dict):
        shown = {key: value for key, value in payload.items() if key not in _SECRET_FIELDS}
        _emit(shown, as_json=as_json)
    else:
        _emit(payload, as_json=as_json)
    if not secret:
        return
    typer.secho("New key (shown once):", fg="yellow")
    typer.echo(secret)
    if not save:
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


def main() -> None:
    if _prog() == "truest":
        typer.secho(
            "The truest command is deprecated and will be removed. Use aifluxx.",
            err=True,
            fg="yellow",
        )
    app()


if __name__ == "__main__":
    main()
