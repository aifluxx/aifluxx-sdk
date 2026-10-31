"""Copy the installed SDK into a project folder as a repo-style tree.

A pip install lands in site-packages. This module writes the same sources a
clone would show: package code (including templates and the starter UI),
README, pyproject.toml, LICENSE, and examples.
"""
from __future__ import annotations

import shutil
import tomllib
from pathlib import Path

from aifluxx_sdk.exceptions import AifluxxError

PACKAGE_NAME = "aifluxx-sdk"
# Keep in sync with setup.py. Those files are staged into the wheel.
ROOT_FILENAMES = ("README.md", "pyproject.toml", "LICENSE", "setup.py", "MANIFEST.in")
EXAMPLES_DIRNAME = "examples"
EXAMPLE_FILES = ("README.md", "send_mail.py")
BUNDLE_DIRNAME = "_source_root"

_SKIP_DIR_NAMES = frozenset(
    {
        "__pycache__",
        "node_modules",
        ".pytest_cache",
        ".mypy_cache",
        ".git",
        ".venv",
        "venv",
        "dist",
        "build",
        BUNDLE_DIRNAME,
    }
)


def package_dir() -> Path:
    return Path(__file__).resolve().parent


def project_name(pyproject: Path) -> str | None:
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    project = data.get("project")
    if isinstance(project, dict) and isinstance(project.get("name"), str):
        return project["name"]
    return None


def checkout_root(pkg: Path | None = None) -> Path | None:
    """Repo root when this process is running from a ``src/`` checkout."""
    pkg = (pkg or package_dir()).resolve()
    if pkg.parent.name != "src":
        return None
    root = pkg.parent.parent
    if (root / "src" / "aifluxx_sdk").resolve() != pkg:
        return None
    if project_name(root / "pyproject.toml") != PACKAGE_NAME:
        return None
    return root


def bundled_root(pkg: Path | None = None) -> Path | None:
    """``_source_root`` shipped inside a wheel or sdist install."""
    root = (pkg or package_dir()).resolve() / BUNDLE_DIRNAME
    if project_name(root / "pyproject.toml") != PACKAGE_NAME:
        return None
    return root


def _ignored_name(name: str) -> bool:
    if name in _SKIP_DIR_NAMES or name.endswith(".egg-info"):
        return True
    if name.endswith((".pyc", ".pyo")) or name == ".DS_Store":
        return True
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return True
    return False


def _ignore(directory: str, names: list[str]) -> set[str]:
    return {name for name in names if _ignored_name(name)}


def _overlaps(dest: Path, src: Path) -> bool:
    dest_r = dest.resolve()
    src_r = src.resolve()
    if dest_r == src_r:
        return True
    try:
        dest_r.relative_to(src_r)
        return True
    except ValueError:
        pass
    try:
        src_r.relative_to(dest_r)
        return True
    except ValueError:
        return False


def _require_tree(file_root: Path) -> Path:
    missing = [name for name in ROOT_FILENAMES if not (file_root / name).is_file()]
    examples = file_root / EXAMPLES_DIRNAME
    if not examples.is_dir():
        missing.append(EXAMPLES_DIRNAME + "/")
    else:
        missing.extend(
            f"{EXAMPLES_DIRNAME}/{name}" for name in EXAMPLE_FILES if not (examples / name).is_file()
        )
    if missing:
        joined = ", ".join(missing)
        raise AifluxxError(
            f"The SDK source is missing from this install ({joined}). Reinstall aifluxx-sdk."
        )
    return examples


def copy_sdk_source(dest: Path, *, force: bool = False) -> Path:
    """Copy the installed SDK tree into ``dest``.

    An editable checkout is copied from the repository. A regular install is
    copied from the package plus the ``_source_root`` files shipped in the wheel.
    A non-empty destination is left unchanged unless ``force`` is set.
    """
    pkg = package_dir()
    checkout = checkout_root(pkg)
    bundle = None if checkout is not None else bundled_root(pkg)
    if checkout is None and bundle is None:
        raise AifluxxError("The SDK source is missing from this install. Reinstall aifluxx-sdk.")
    file_root = checkout if checkout is not None else bundle
    assert file_root is not None
    examples = _require_tree(file_root)

    root = dest.expanduser().resolve()
    if _overlaps(root, pkg) or _overlaps(root, examples):
        raise AifluxxError(f"Refusing to copy the SDK onto its own files ({root}). Choose a different folder.")
    if checkout is not None and root == checkout.resolve():
        raise AifluxxError(f"Refusing to copy the SDK onto its own files ({root}). Choose a different folder.")
    if bundle is not None and _overlaps(root, bundle):
        raise AifluxxError(f"Refusing to copy the SDK onto its own files ({root}). Choose a different folder.")
    if root.exists() and not root.is_dir():
        raise AifluxxError(f"{root} exists and is not a folder.")
    if root.exists() and any(root.iterdir()) and not force:
        raise AifluxxError(f"{root} already exists and is not empty. Pass --force to overwrite.")

    root.mkdir(parents=True, exist_ok=True)
    try:
        for name in ROOT_FILENAMES:
            shutil.copy2(file_root / name, root / name)
        shutil.copytree(examples, root / EXAMPLES_DIRNAME, dirs_exist_ok=True, ignore=_ignore)
        shutil.copytree(pkg, root / "src" / "aifluxx_sdk", dirs_exist_ok=True, ignore=_ignore)
    except (OSError, shutil.Error) as exc:
        raise AifluxxError(f"Could not copy the SDK source into {root}. {exc}") from exc
    return root
