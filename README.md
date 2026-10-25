# aifluxx-sdk

Python client and `aifluxx` command-line tool for [AIfluxx](https://aifluxx.co.za). The CLI authors an agent package from any IDE terminal. The library calls the developer API and connected-mailbox send as the person who owns the key.

Signup, docs, and the developer site stay on the AIfluxx host. This repository does not ship a UI.

## Install

Once a maintainer publishes the package:

```bash
pip install aifluxx-sdk
```

From a checkout of this repository:

```bash
pip install -e .
```

A git install needs a public repository, or credentials that can read a private one:

```bash
pip install "aifluxx-sdk @ git+https://github.com/aifluxx/aifluxx-sdk.git@v0.1.0"
```

Publishing to PyPI and making this repository public are separate steps. Neither is done by installing the package. See the release workflow in `.github/workflows/publish.yml`.

## Log in

The default API root is `https://api.aifluxx.co.za`.

```bash
aifluxx login --api-key afx_dev_…
```

Override the host for this login with `--url`, or for every command in the current process with `AIFLUXX_API_URL`:

```bash
aifluxx login --url https://api.aifluxx.co.za
export AIFLUXX_API_URL=https://api.aifluxx.co.za
```

`--url` wins over `--platform`, which wins over `AIFLUXX_API_URL`. When `AIFLUXX_API_URL` is set, later commands use it instead of the URL saved at login.

Truest is a named profile. It always uses `https://api.truest.ae`:

```bash
aifluxx login --platform truest
```

`https://api.truest.biz` is retired. Passing it as `--url` or `AIFLUXX_API_URL` stores and calls `https://api.truest.ae` instead.

Credentials are written to `~/.aifluxx/credentials` (mode `0600`). If that file is missing and `~/.truest/credentials` exists, the CLI copies it and rewrites a retired host. The file stays on your machine. Do not commit it.

`truest` still runs this program and prints a deprecation warning. Use `aifluxx`.

Point the credentials file somewhere else with `AIFLUXX_CREDENTIALS`.

## Author a package

```bash
aifluxx init my-agent --template compliance
aifluxx validate
aifluxx push
aifluxx run "Summarise open compliance tasks"
aifluxx submit
```

`init` scaffolds `spec.yaml`, `instructions.md`, a short README, and `samples.yaml`. New packages use schema `aifluxx/agent/v1`. `truest/agent/v1` still validates. `validate` is offline. `push` uploads the folder and creates a Draft. It does not `git push`. `run` streams a sandbox run. `submit` sends the latest Draft for review.

Other commands:

```bash
aifluxx status
aifluxx import-git https://github.com/your-org/your-agent
aifluxx keys list
aifluxx keys rotate <key-id>
aifluxx keys revoke <key-id>
```

After a successful push the CLI writes `.aifluxx/agent.lock` in the package. An older `.truest/agent.lock` is still read. Neither directory is uploaded.

## API keys

`aifluxx keys` calls the developer key API:

| Command | Request |
|---|---|
| `aifluxx keys list` | `GET /api/dev/keys` |
| `aifluxx keys rotate <id>` | `POST /api/dev/keys/{id}/rotate` |
| `aifluxx keys revoke <id>` | `POST /api/dev/keys/{id}/revoke` |

List responses omit the secret. Rotate prints a new secret once. `--save` on rotate replaces the key in `~/.aifluxx/credentials`. Revoke asks for confirmation unless you pass `--yes`.

## Python

```python
from aifluxx_sdk import AifluxxClient

client = AifluxxClient("https://api.aifluxx.co.za", api_key="afx_live_…")
client.mail.send(
    from_="owner@example.com",
    to="colleague@example.com",
    subject="Q4 stock",
    body="Please find the note below.",
    business_id="<company uuid>",
)
```

`TruestClient` still constructs the same client and emits a `DeprecationWarning`. Use `AifluxxClient`.

`client.mail.mailboxes(business_id=…)` lists connected identities you may name as `from_`. `from_` is required and must match a connected mailbox (`imap_mail`, `gmail_mail`, or `ms_graph_mail`). Send is immediate. The key must be a company admin or delegate. Multi-business users pass `business_id`.

`client.send(...)` talks to an agent over A2A at `/a2a`. It raises `NotImplementedError` until that route is available. Mail send does not use it.

Authorization is `Authorization: Bearer` with a Connected-apps key (`afx_live_…` or `mcpat_…`) or a developer key from Home (`afx_dev_…`).

## MCP

MCP clients talk to the host. This package does not embed an MCP server. Point Cursor, Claude, or another client at `/mcp` with the same bearer key:

```json
{
  "mcpServers": {
    "aifluxx": {
      "url": "https://api.aifluxx.co.za/mcp",
      "headers": {
        "Authorization": "Bearer afx_live_…"
      }
    }
  }
}
```

For the Truest profile use `https://api.truest.ae/mcp`. Multi-business keys pass `business_id` the same way the Python client does.

## Develop

```bash
pip install -e ".[dev]"
pytest
python -m build
twine check dist/*
```

Requires Python 3.11 or newer.
