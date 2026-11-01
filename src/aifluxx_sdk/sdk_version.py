"""Each commit of this repository carries a newer SDK version.

CI compares ``pyproject.toml`` with the parent commit. A commit on ``main``
whose version moved is tagged ``vX.Y.Z``. That tag publishes the package and
moves the ``latest`` tag the dev container installs.
"""
from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path


class VersionError(Exception):
    """The commit does not carry a newer SDK version."""


def parse_semver(value: str) -> tuple[int, int, int]:
    parts = value.split(".")
    if len(parts) != 3:
        raise VersionError(f"{value} is not an SDK version. Use major.minor.patch.")
    numbers: list[int] = []
    for part in parts:
        if not part.isdigit() or (len(part) > 1 and part.startswith("0")):
            raise VersionError(f"{value} is not an SDK version. Use major.minor.patch.")
        numbers.append(int(part))
    return numbers[0], numbers[1], numbers[2]


def project_version(text: str) -> str:
    try:
        version = tomllib.loads(text)["project"]["version"]
    except (tomllib.TOMLDecodeError, KeyError, TypeError) as exc:
        raise VersionError("pyproject.toml has no project version.") from exc
    if not isinstance(version, str):
        raise VersionError("pyproject.toml has no project version.")
    parse_semver(version)
    return version


def require_newer(previous: str | None, current: str, changelog: str) -> None:
    """``current`` must be newer than ``previous`` and named in the changelog."""
    parse_semver(current)
    if previous is not None and parse_semver(current) <= parse_semver(previous):
        raise VersionError(
            f"This commit is SDK {current}. The previous commit is {previous}. "
            "Each commit needs a new SDK version in pyproject.toml."
        )
    if f"## {current}" not in changelog:
        raise VersionError(f"CHANGELOG.md needs a heading for {current}.")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


def parent_pyproject(repo: Path) -> str | None:
    """The parent commit's pyproject, or None for the first commit."""
    parent = _git(repo, "rev-parse", "--verify", "HEAD^")
    if parent.returncode != 0:
        shallow = _git(repo, "rev-parse", "--is-shallow-repository")
        if shallow.stdout.strip() == "true":
            raise VersionError("The checkout is shallow. Fetch the parent commit before checking the SDK version.")
        return None
    shown = _git(repo, "show", "HEAD^:pyproject.toml")
    if shown.returncode != 0:
        return None
    return shown.stdout


def check_repo(repo: Path) -> str:
    """Return this commit's SDK version, or raise ``VersionError``."""
    current = project_version((repo / "pyproject.toml").read_text(encoding="utf-8"))
    changelog = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    previous_text = parent_pyproject(repo)
    previous = project_version(previous_text) if previous_text is not None else None
    require_newer(previous, current, changelog)
    return current


def main() -> None:
    try:
        version = check_repo(Path.cwd())
    except VersionError as exc:
        raise SystemExit(str(exc)) from exc
    print(version)


if __name__ == "__main__":
    main()
