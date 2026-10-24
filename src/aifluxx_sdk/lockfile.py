"""Per-package lock written after the first successful push."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


def lock_path(package_dir: Path) -> Path:
    return package_dir / ".truest" / "agent.lock"


@dataclass
class AgentLock:
    id: str | None = None
    slug: str | None = None
    last_pushed_version: str | None = None


def load_lock(package_dir: Path) -> AgentLock | None:
    store = lock_path(package_dir)
    if not store.is_file():
        return None
    data = json.loads(store.read_text(encoding="utf-8"))
    return AgentLock(
        id=data.get("id"),
        slug=data.get("slug"),
        last_pushed_version=data.get("last_pushed_version"),
    )


def save_lock(package_dir: Path, lock: AgentLock) -> Path:
    store = lock_path(package_dir)
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(
        json.dumps(
            {
                "id": lock.id,
                "slug": lock.slug,
                "last_pushed_version": lock.last_pushed_version,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return store
