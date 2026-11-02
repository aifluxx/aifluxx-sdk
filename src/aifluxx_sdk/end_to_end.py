"""Files `aifluxx init` writes so a commit to main can upload the agent.

The default workflow validates and pushes a Draft. It does not submit.
`--container` also writes the dev container. Those files do not name a
container registry and do not push an image.
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

RUN pip install --no-cache-dir "aifluxx-sdk @ git+https://github.com/aifluxx/aifluxx-sdk.git"

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
      AIFLUXX_API_URL: ${AIFLUXX_API_URL:-https://dev.developer.aifluxx.co.za}
""",
    "devcontainer/submit.sh": """\
#!/bin/sh
set -eu
if [ -z "${AIFLUXX_API_KEY:-}" ]; then
  echo "Set the AIFLUXX_API_KEY repository secret. It is the key from Home." >&2
  exit 1
fi
printf '%s' "$AIFLUXX_API_KEY" | aifluxx login --api-key-stdin --platform developer
aifluxx validate
aifluxx push
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
name: Push agent

on:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  push:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Validate and push a Draft
        env:
          AIFLUXX_API_KEY: ${{ secrets.AIFLUXX_API_KEY }}
          AIFLUXX_API_URL: https://dev.developer.aifluxx.co.za
        run: |
          pip install "aifluxx-sdk @ git+https://github.com/aifluxx/aifluxx-sdk.git"
          printf '%s' "$AIFLUXX_API_KEY" | aifluxx login --api-key-stdin --platform developer
          aifluxx validate
          aifluxx push
""",
    ".dockerignore": """\
.git
.venv
**/__pycache__
""",
}


_WORKFLOW = ".github/workflows/submit.yml"


def write_end_to_end(root: Path, *, container: bool = False) -> list[Path]:
    """Write the push workflow. Docker files are written only when ``container`` is set."""
    chosen = END_TO_END_FILES if container else {_WORKFLOW: END_TO_END_FILES[_WORKFLOW]}
    written: list[Path] = []
    for relative, body in chosen.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8", newline="\n")
        written.append(path)
    return written
