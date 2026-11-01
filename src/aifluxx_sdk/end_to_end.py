"""Files `aifluxx init` writes so a commit to main can submit the agent.

The dev container is built in the GitHub Action and discarded. These files do
not name a container registry and do not push an image. After a person
approves the submitted draft, dev.aifluxx.co.za makes the container available.
"""
from __future__ import annotations

from pathlib import Path

# Order is the order init prints. Paths are relative to the package root.
END_TO_END_FILES: dict[str, str] = {
    "Dockerfile": """\
FROM python:3.11-slim-bookworm

RUN apt-get update \\
    && apt-get install -y --no-install-recommends git ca-certificates \\
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "git+https://github.com/aifluxx/aifluxx-sdk@latest"

COPY devcontainer/submit.sh /opt/aifluxx/submit.sh
RUN chmod 755 /opt/aifluxx/submit.sh

WORKDIR /work
CMD ["sleep", "infinity"]
""",
    "compose.yaml": """\
# Dev container for this agent. Built when the Action runs. Not pushed anywhere.
services:
  dev:
    build:
      context: .
      dockerfile: Dockerfile
    init: true
    working_dir: /work
    volumes:
      - .:/work
    environment:
      AIFLUXX_API_URL: https://dev.aifluxx.co.za
""",
    "devcontainer/submit.sh": """\
#!/bin/sh
set -eu
if [ -z "${AIFLUXX_API_KEY:-}" ]; then
  echo "Set the AIFLUXX_API_KEY repository secret. It is the key from Home." >&2
  exit 1
fi
printf '%s' "$AIFLUXX_API_KEY" | aifluxx login --api-key-stdin --platform dev
aifluxx validate
aifluxx push
aifluxx submit
""",
    ".devcontainer/devcontainer.json": """\
{
  "name": "AIFluxx agent",
  "dockerComposeFile": "../compose.yaml",
  "service": "dev",
  "workspaceFolder": "/work"
}
""",
    ".github/workflows/submit.yml": """\
name: Submit agent

on:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  submit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Validate, push, and submit
        env:
          AIFLUXX_API_KEY: ${{ secrets.AIFLUXX_API_KEY }}
        run: docker compose run --rm -e AIFLUXX_API_KEY dev sh /opt/aifluxx/submit.sh
""",
    ".dockerignore": """\
.git
.venv
**/__pycache__
""",
}


def write_end_to_end(root: Path) -> list[Path]:
    """Write the dev container, Compose file, and GitHub Action into ``root``."""
    written: list[Path] = []
    for relative, body in END_TO_END_FILES.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8", newline="\n")
        written.append(path)
    return written
