"""`aifluxx` CLI. `truest` is a deprecated console-script alias."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import NoReturn

import typer

from aifluxx_sdk.client import AifluxxClient
from aifluxx_sdk.credentials import Credentials, load_credentials, normalize_api_url, resolve_api_url, save_credentials
from aifluxx_sdk.exceptions import AifluxxError, AuthError
from aifluxx_sdk.lockfile import load_lock
from aifluxx_sdk.package import validate_package
from aifluxx_sdk.templates import TEMPLATES, get_template, render_spec, slug_to_name

_SECRET_FIELDS = ("api_key", "key", "secret", "token")


def _prog() -> str:
    stem = Path(sys.argv[0]).name.split(".")[0].lower()
    return stem if stem in {"aifluxx", "truest"} else "aifluxx"


app = typer.Typer(
    name=_prog(),
    no_args_is_help=True,
    add_completion=False,
    help="Author an agent package and call the AIfluxx API. Signup stays on the developer site.",
)
keys_app = typer.Typer(no_args_is_help=True, help="List, rotate, or revoke developer API keys.")
app.add_typer(keys_app, name="keys")


def _client() -> AifluxxClient:
    creds = load_credentials()
    override = os.environ.get("AIFLUXX_API_URL", "").strip()
    url = normalize_api_url(override) if override else creds.url
    return AifluxxClient(url, api_key=creds.api_key)


def _die(exc: Exception) -> NoReturn:
    typer.secho(str(exc), err=True, fg="red")
    raise typer.Exit(code=1)


def _package_dir(path: Path | None) -> Path:
    if path:
        return path.resolve()
    cwd = Path.cwd()
    if (cwd / "spec.yaml").is_file():
        return cwd
    raise AifluxxError("No spec.yaml here. Pass a path or run the command inside the package folder.")


def _pretty(payload: object) -> str:
    import json

    if isinstance(payload, (dict, list)):
        return json.dumps(payload, indent=2)
    return str(payload)


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


@app.command()
def login(
    api_key: str | None = typer.Option(None, "--api-key", help="afx_dev_ key from Home. Prompted if omitted."),
    url: str | None = typer.Option(
        None,
        "--url",
        help="API root. Overrides --platform and AIFLUXX_API_URL. Default https://api.aifluxx.co.za.",
    ),
    platform: str | None = typer.Option(
        None,
        "--platform",
        help="Named host: aifluxx (https://api.aifluxx.co.za) or truest (https://api.truest.ae).",
    ),
) -> None:
    """Save the afx_dev_ key from Home. Works in any IDE terminal."""
    key = (api_key or typer.prompt("API key from Home", hide_input=True)).strip()
    if not key:
        _die(AuthError("api_key is required."))
    if not (key.startswith("afx_dev_") or key.startswith("afx_live_") or key.startswith("mcpat_")):
        typer.secho("Keys from Home start with afx_dev_. Subscriber keys start with afx_live_.", fg="yellow")
    try:
        resolved = resolve_api_url(url=url, platform=platform)
    except AifluxxError as exc:
        _die(exc)
    if _retired_host_in_selection(url, platform):
        typer.secho(f"api.truest.biz is retired. Using {resolved}.", fg="yellow")
    store = save_credentials(Credentials(url=resolved, api_key=key))
    typer.echo(f"Saved {store}. This file is on your machine, not in the package repo.")


@app.command("init")
def init_cmd(
    slug: str = typer.Argument(..., help="Package folder name, kebab-case."),
    template: str = typer.Option("compliance", "--template", "-t", help="Starter: " + ", ".join(sorted(TEMPLATES))),
    dest: Path | None = typer.Option(None, "--dest", help="Parent folder. Defaults to the current directory."),
) -> None:
    """Scaffold a package in your repo. git push still goes to GitHub or GitLab."""
    try:
        chosen = get_template(template)
    except AifluxxError as exc:
        _die(exc)
    root = (dest or Path.cwd()).resolve() / slug
    if root.exists() and any(root.iterdir()):
        _die(AifluxxError(f"{root} already exists and is not empty."))
    root.mkdir(parents=True, exist_ok=True)
    (root / "spec.yaml").write_text(render_spec(slug, chosen), encoding="utf-8")
    (root / "instructions.md").write_text(chosen.instructions, encoding="utf-8")
    (root / "README.md").write_text(f"# {slug_to_name(slug)}\n\n{chosen.description}\n", encoding="utf-8")
    (root / "samples.yaml").write_text("prompts:\n  - Summarise what you can already see.\n", encoding="utf-8")
    typer.echo(f"Created {root}. Commit this folder to your Git repo, then `aifluxx push` or Import from Git.")


@app.command()
def validate(path: Path | None = typer.Argument(None, help="Package folder. Defaults to the current directory.")) -> None:
    """Run the same validator the host will run. No network."""
    try:
        report = validate_package(_package_dir(path))
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
def push(path: Path | None = typer.Argument(None, help="Package folder. Defaults to the current directory.")) -> None:
    """Upload the folder you have open. Creates a Draft. Does not git push."""
    try:
        package = _package_dir(path)
        with _client() as client:
            payload = client.dev.push(package)
    except (AifluxxError, OSError) as exc:
        _die(exc)
    typer.echo(payload if isinstance(payload, str) else _pretty(payload))


@app.command("run")
def run_cmd(
    prompt: str = typer.Argument(..., help="Prompt to run against the sandbox."),
    path: Path | None = typer.Option(None, "--path", help="Package folder if you are not inside it."),
    version: str | None = typer.Option(None, "--version"),
) -> None:
    """Stream a sandbox run for the package slug."""
    try:
        package = _package_dir(path)
        report = validate_package(package)
        slug = str(report.spec.get("slug") or package.name)
        lock = load_lock(package)
        with _client() as client:
            for line in client.dev.run(slug, prompt, version=version or (lock.last_pushed_version if lock else None)):
                typer.echo(line)
    except (AifluxxError, OSError) as exc:
        _die(exc)


@app.command()
def submit(
    path: Path | None = typer.Argument(None, help="Package folder. Defaults to the current directory."),
    version: str | None = typer.Option(None, "--version"),
) -> None:
    """Submit the latest Draft for review."""
    try:
        package = _package_dir(path)
        report = validate_package(package)
        slug = str(report.spec.get("slug") or package.name)
        lock = load_lock(package)
        with _client() as client:
            payload = client.dev.submit(slug, version or (lock.last_pushed_version if lock else None))
    except (AifluxxError, OSError) as exc:
        _die(exc)
    typer.echo(_pretty(payload))


@app.command()
def status() -> None:
    """List org agents, versions, and states."""
    try:
        with _client() as client:
            payload = client.dev.status()
    except (AifluxxError, OSError) as exc:
        _die(exc)
    typer.echo(_pretty(payload))


@app.command("import-git")
def import_git(
    repo_url: str = typer.Argument(..., help="GitHub or GitLab URL you already pushed."),
    token: str | None = typer.Option(None, "--token", help="Optional clone token. Never stored in the package."),
    ref: str | None = typer.Option(None, "--ref"),
) -> None:
    """Create Drafts from a repository you own. git remotes stay yours."""
    try:
        with _client() as client:
            payload = client.dev.import_git(repo_url, token=token, ref=ref)
    except (AifluxxError, OSError) as exc:
        _die(exc)
    typer.echo(_pretty(payload))


@keys_app.command("list")
def keys_list() -> None:
    """Show developer API keys for the logged-in account. Secrets are not returned."""
    try:
        with _client() as client:
            payload = client.dev.list_keys()
    except (AifluxxError, OSError) as exc:
        _die(exc)
    typer.echo(_pretty(payload))


@keys_app.command("rotate")
def keys_rotate(
    key_id: str = typer.Argument(..., help="Key id from `aifluxx keys list`."),
    save: bool = typer.Option(False, "--save", help="Write the new secret into the local credentials file."),
) -> None:
    """Rotate one key. The new secret is shown once."""
    try:
        with _client() as client:
            payload = client.dev.rotate_key(key_id)
    except (AifluxxError, OSError) as exc:
        _die(exc)
    secret = _new_secret(payload)
    if isinstance(payload, dict):
        shown = {key: value for key, value in payload.items() if key not in _SECRET_FIELDS}
        typer.echo(_pretty(shown))
    else:
        typer.echo(_pretty(payload))
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
    key_id: str = typer.Argument(..., help="Key id from `aifluxx keys list`."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Revoke without a confirmation prompt."),
) -> None:
    """Revoke one key. It stops working immediately."""
    if not yes and not typer.confirm(f"Revoke key {key_id}?"):
        raise typer.Exit(code=1)
    try:
        with _client() as client:
            payload = client.dev.revoke_key(key_id)
    except (AifluxxError, OSError) as exc:
        _die(exc)
    typer.echo(_pretty(payload))


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
