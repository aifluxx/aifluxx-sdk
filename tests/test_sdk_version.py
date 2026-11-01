"""A commit has to raise the SDK version above its parent."""
import subprocess
from pathlib import Path

import pytest

from aifluxx_sdk.sdk_version import VersionError, check_repo, require_newer

CHANGELOG = "## 1.3.2 - 2026-11-01\n"
PYPROJECT = '[project]\nname = "aifluxx-sdk"\nversion = "{version}"\n'


def test_require_newer_accepts_a_raised_version():
    require_newer("1.3.1", "1.3.2", CHANGELOG)


def test_require_newer_rejects_the_same_version():
    with pytest.raises(VersionError, match="Each commit needs a new SDK version"):
        require_newer("1.3.1", "1.3.1", CHANGELOG)


def test_require_newer_rejects_a_missing_changelog_heading():
    with pytest.raises(VersionError, match="CHANGELOG.md needs a heading for 1.3.2"):
        require_newer("1.3.1", "1.3.2", "## 1.3.1 - 2026-10-31\n")


def _commit(repo: Path, version: str, message: str) -> None:
    (repo / "pyproject.toml").write_text(PYPROJECT.format(version=version), encoding="utf-8")
    (repo / "CHANGELOG.md").write_text(f"## {version} - 2026-11-01\n\n{message}\n", encoding="utf-8")
    subprocess.run(["git", "add", "pyproject.toml", "CHANGELOG.md"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=dev@example.com", "-c", "user.name=Dev", "commit", "-m", message],
        cwd=repo,
        check=True,
    )


def test_check_repo_reads_the_parent_commit(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True)
    _commit(tmp_path, "1.3.1", "first")
    assert check_repo(tmp_path) == "1.3.1"
    _commit(tmp_path, "1.3.1", "same")
    with pytest.raises(VersionError, match="previous commit is 1.3.1"):
        check_repo(tmp_path)
    _commit(tmp_path, "1.3.2", "raised")
    assert check_repo(tmp_path) == "1.3.2"
