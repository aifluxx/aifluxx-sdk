"""Bundle repo-root files into the wheel so ``aifluxx source`` can copy them out.

Pip installs into site-packages and cannot write the SDK tree into the project
directory. The wheel build copies README, pyproject.toml, LICENSE, the
packaging files, and examples into ``aifluxx_sdk/_source_root``. ``aifluxx
source`` writes that snapshot into the project folder.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

# Keep in sync with aifluxx_sdk.source.ROOT_FILENAMES and EXAMPLES_DIRNAME.
ROOT_FILENAMES = ("README.md", "pyproject.toml", "LICENSE", "setup.py", "MANIFEST.in")
EXAMPLES_DIRNAME = "examples"
BUNDLE_DIRNAME = "_source_root"


def stage_source_root(project_root: Path) -> Path:
    """Copy the repo-root files ``aifluxx source`` republishes into a temp dir."""
    dest = Path(tempfile.mkdtemp(prefix="aifluxx-source-root-"))
    try:
        for name in ROOT_FILENAMES:
            src = project_root / name
            if not src.is_file():
                raise FileNotFoundError(f"Cannot bundle {src}")
            shutil.copy2(src, dest / name)
        examples = project_root / EXAMPLES_DIRNAME
        if not examples.is_dir():
            raise FileNotFoundError(f"Cannot bundle {examples}")
        shutil.copytree(
            examples,
            dest / EXAMPLES_DIRNAME,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return dest


class BuildPy(build_py):
    def run(self) -> None:
        # Stage outside the source tree. A ``*.py`` file under the package makes
        # setuptools treat ``_source_root`` as an importable package.
        editable = bool(getattr(self, "editable_mode", False))
        staged: Path | None = None
        if not editable:
            staged = stage_source_root(Path(__file__).resolve().parent)
        try:
            super().run()
            if staged is not None:
                bundled = Path(self.build_lib) / "aifluxx_sdk" / BUNDLE_DIRNAME
                if bundled.exists():
                    shutil.rmtree(bundled)
                shutil.copytree(staged, bundled)
        finally:
            if staged is not None and staged.exists():
                shutil.rmtree(staged, ignore_errors=True)


setup(cmdclass={"build_py": BuildPy})
