"""`aifluxx` CLI. Same commands from any IDE terminal. `truest` still runs this program."""
from __future__ import annotations

import sys
from pathlib import Path

import typer

from aifluxx_sdk.client import TruestClient
from aifluxx_sdk.credentials import DEFAULT_URL, Credentials, load_credentials, save_credentials
from aifluxx_sdk.exceptions import AifluxxError, AuthError
from aifluxx_sdk.lockfile import load_lock
from aifluxx_sdk.package import validate_package
from aifluxx_sdk.templates import TEMPLATES, get_template, render_spec, slug_to_name

def _prog() -> str:
    stem = Path(sys.argv[0]).name.split(".")[0].lower()
    return stem if stem in {"aifluxx", "truest"} else "aifluxx"


PROG = _prog()

app = typer.Typer(
    name=PROG,
    no_args_is_help=True,
    add_completion=False,
    help="Author an agent package from any IDE. Signup stays on the developer site.",
)


def _client() -> TruestClient:
    creds = load_credentials()
    return TruestClient(creds.url, api_key=creds.api_key)


def _die(exc: Exception) -> None:
    typer.secho(str(exc), err=True, fg="red")
    raise typer.Exit(code=1)


def _package_dir(path: Path | None) -> Path:
    if path:
        return path.resolve()
    cwd = Path.cwd()
    if (cwd / "spec.yaml").is_file():
        return cwd
    raise AifluxxError("No spec.yaml here. Pass a path or run the command inside the package folder.")


@app.command()
def login(
    api_key: str | None = typer.Option(None, "--api-key", help="afx_dev_ key from Home. Prompted if omitted."),
    url: str = typer.Option(DEFAULT_URL, "--url", help="Truest API root."),
) -> None:
    """Save the afx_dev_ key from Home. Works in any IDE terminal."""
    key = (api_key or typer.prompt("API key from Home", hide_input=True)).strip()
    if not key:
        _die(AuthError("api_key is required."))
    if not (key.startswith("afx_dev_") or key.startswith("afx_live_") or key.startswith("mcpat_")):
        typer.secho("Keys from Home start with afx_dev_. Subscriber keys start with afx_live_.", fg="yellow")
    store = save_credentials(Credentials(url=url, api_key=key))
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
    typer.echo(f"Created {root}. Commit this folder to your Git repo, then `{PROG} push` or Import from Git.")


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


def _pretty(payload: object) -> str:
    import json

    if isinstance(payload, (dict, list)):
        return json.dumps(payload, indent=2)
    return str(payload)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
