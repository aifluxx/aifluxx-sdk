# aifluxx-sdk

Python client and `aifluxx` command-line tool for [AIfluxx](https://aifluxx.co.za). The CLI authors an agent package from any IDE terminal. The library calls the developer API and connected-mailbox send as the person who owns the key.

Signup, docs, and the developer site stay on the AIfluxx host. This repository does not ship a UI.

## Install

This package is not on PyPI, and the GitHub repository is private. These commands fail today:

```bash
pip install aifluxx
pip install aifluxx-sdk
pip install git+https://github.com/aifluxx/aifluxx-sdk.git
```

`pip install aifluxx` looks up a different name and finds nothing. `pip install aifluxx-sdk` looks on PyPI, where this project has not been published. An unauthenticated `git+https` URL gets a 404 from GitHub because the repository is private.

Install from a checkout you can already read:

```bash
gh repo clone aifluxx/aifluxx-sdk
cd aifluxx-sdk
pip install -e .
```

If your SSH key can read `aifluxx/aifluxx-sdk`:

```bash
pip install "aifluxx-sdk @ git+ssh://git@github.com/aifluxx/aifluxx-sdk.git"
```

Publishing to PyPI, and making the repository public, are separate decisions. Neither is required to install from a clone. See `.github/workflows/publish.yml`.

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

`https://api.truest.biz` is retired. The CLI rewrites it to `https://api.aifluxx.co.za`. It is not a profile and it is not the default. `--platform truest` is what selects `https://api.truest.ae`.

Credentials are written to `~/.aifluxx/credentials` (mode `0600`). If that file is missing and `~/.truest/credentials` exists, the CLI copies it into `~/.aifluxx/` and rewrites a retired host. The override for that path is `AIFLUXX_CREDENTIALS`. `TRUEST_CREDENTIALS` still works and prints a deprecation warning. The file stays on your machine. Do not commit it.

`truest` still runs this program and prints a deprecation warning. Use `aifluxx`.

## Author a package

```bash
aifluxx init my-agent --template compliance
aifluxx validate
aifluxx push
aifluxx run "Summarise open compliance tasks"
aifluxx run my-agent "Summarise open compliance tasks"
aifluxx submit
```

`init` scaffolds `spec.yaml`, `instructions.md`, a short README, and `samples.yaml`. New packages use schema `aifluxx/agent/v1`. `truest/agent/v1` still validates. `validate` is offline. `push` uploads the folder and creates a Draft. It does not `git push`.

`run` takes a prompt, and a slug when you are not inside the package. Inside the package directory, `aifluxx run PROMPT` reads the slug from `spec.yaml`. Otherwise pass it: `aifluxx run SLUG PROMPT` or `aifluxx run PROMPT --slug SLUG`. The same slug is the one `run` sends to the API.

`submit` and `run` call `/api/dev/agents/{slug}/versions/{version_id}/...`. `version_id` is a UUID. The CLI does not send the word `latest` or a semver such as `0.1.0` in that path. It uses the UUID saved at push, or looks the slug up with `GET /api/dev/agents`. Pass `--version <uuid>` to choose one yourself. A semver passed to `--version` is looked up, not sent as the path id.

Other commands:

```bash
aifluxx status
aifluxx import-git https://github.com/your-org/your-agent
aifluxx keys list
aifluxx keys rotate <key-id>
aifluxx keys revoke <key-id>
```

After a successful push the CLI writes `.aifluxx/agent.lock` in the package, including the version UUID. An older `.truest/agent.lock` is copied to `.aifluxx/agent.lock` the next time it is read. Neither directory is uploaded. New commands do not write `~/.truest` or `.truest/agent.lock`.

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

## Errors from the API

`afx_dev_` keys that the host rejects, a failed push, and a redirect are printed with the HTTP status, the method, the URL, and the response body. A 401 is the host rejecting the bearer key (the body may say `Sign in again to create a key.`). A 500 is a host failure on a request that did reach the API, including push. The SDK does not follow redirects. A 307 whose `Location` is `http://...` is reported as a TLS downgrade instead of being followed.

`aifluxx run` reads an error body before it raises. A streamed 4xx or 5xx is shown as that host message, not as `httpx.ResponseNotRead`.

## MCP

MCP clients talk to the host. This package does not embed an MCP server. Use the HTTPS URL with a trailing slash:

```json
{
  "mcpServers": {
    "aifluxx": {
      "url": "https://api.aifluxx.co.za/mcp/",
      "headers": {
        "Authorization": "Bearer afx_live_…"
      }
    }
  }
}
```

`https://api.aifluxx.co.za/mcp` (no slash) currently returns 307 to `http://api.aifluxx.co.za/mcp/`, which drops TLS. That redirect is a host bug. The trailing-slash HTTPS URL avoids it. For the Truest profile use `https://api.truest.ae/mcp/`. Multi-business keys pass `business_id` the same way the Python client does.

## Develop

```bash
pip install -e ".[dev]"
pytest
python -m build
twine check dist/*
```

Requires Python 3.11 or newer.
