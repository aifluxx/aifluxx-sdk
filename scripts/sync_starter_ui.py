#!/usr/bin/env python3
"""Refresh the vendored AIFluxx Starter UI from upstream.

Usage: python scripts/sync_starter_ui.py [--ref main] [--source /path/to/checkout]

Copies the git-tracked files of github.com/aifluxx/aifluxx-starter-ui into
src/aifluxx_sdk/starter_ui/ and records the source commit in UPSTREAM.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

UPSTREAM = "https://github.com/aifluxx/aifluxx-starter-ui.git"
DEST = Path(__file__).resolve().parents[1] / "src" / "aifluxx_sdk" / "starter_ui"


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def sync(source: Path) -> str:
    sha = _git("rev-parse", "HEAD", cwd=source).strip()
    files = [f for f in _git("ls-files", "-z", cwd=source).split("\0") if f]
    if DEST.exists():
        shutil.rmtree(DEST)
    for rel in files:
        target = DEST / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / rel, target)
    (DEST / "UPSTREAM").write_text(f"source: {UPSTREAM}\ncommit: {sha}\n", encoding="utf-8")
    return sha


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="main", help="Branch, tag, or commit SHA.")
    parser.add_argument("--source", type=Path, help="Existing checkout to copy from instead of cloning.")
    args = parser.parse_args()
    if args.source:
        sha = sync(args.source.resolve())
    else:
        with tempfile.TemporaryDirectory() as tmp:
            # --ref may be a branch, tag, or commit SHA.
            subprocess.run(["git", "clone", "-q", UPSTREAM, tmp], check=True)
            subprocess.run(["git", "checkout", "-q", "--detach", args.ref], cwd=tmp, check=True)
            sha = sync(Path(tmp))
    print(f"Vendored starter UI at {sha} into {DEST}")


if __name__ == "__main__":
    main()
