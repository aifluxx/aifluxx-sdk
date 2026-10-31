# aifluxx-sdk

Python client and `aifluxx` command-line tool for [AIFluxx](https://aifluxx.co.za). The CLI authors an agent package from any IDE terminal. The library calls the developer API and connected-mailbox send as the person who owns the key.

Signup, docs, and the developer site stay on the AIFluxx host. This repository does not ship a UI.

## Install

Requires Python 3.11 or newer. The package is not on PyPI. Use a virtual environment.

Pip installs the package into that environment. It leaves the project directory unchanged. To have the SDK as a normal folder in the project, use the clone below, or copy it out after a pip install with `aifluxx source`.

### Recommended: clone and editable install

Clone the repository, then install that folder in editable mode. Python imports the clone, so the SDK is a normal directory in your project. Templates (`src/aifluxx_sdk/templates.py`) and the starter UI (`src/aifluxx_sdk/starter_ui/`) are part of that tree. This works on macOS, Linux, and Windows.

bash:

```bash
python -m venv .venv
source .venv/bin/activate
git clone https://github.com/aifluxx/aifluxx-sdk
pip install -e ./aifluxx-sdk
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
git clone https://github.com/aifluxx/aifluxx-sdk
pip install -e .\aifluxx-sdk
```

If PowerShell refuses the activate script, allow scripts for this window and run the activate command again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

The clone is a git checkout. The folders you use look like this:

```
aifluxx-sdk/
  LICENSE
  README.md
  pyproject.toml
  examples/
    send_mail.py
  src/
    aifluxx_sdk/
      templates.py
      starter_ui/
        package.json
        .env.example
        .gitignore
        ...
  tests/
```

The checkout also contains the tests and the GitHub workflows.

### Pip install, then copy the source into the project

Install from GitHub when you want the package on `PATH` without a clone. Copy the installed SDK into the project with `aifluxx source`. The default folder is `./aifluxx-sdk`.

bash:

```bash
python -m venv .venv
source .venv/bin/activate
pip install git+https://github.com/aifluxx/aifluxx-sdk
aifluxx source
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install git+https://github.com/aifluxx/aifluxx-sdk
aifluxx source
```

`aifluxx source my-sdk` writes `./my-sdk` instead. The command leaves a non-empty destination unchanged. Pass `--force` to overwrite files in that folder.

The folder this writes:

```
aifluxx-sdk/
  LICENSE
  README.md
  pyproject.toml
  setup.py
  MANIFEST.in
  examples/
    README.md
    send_mail.py
  src/
    aifluxx_sdk/
      __init__.py
      cli.py
      templates.py
      starter_ui/
        package.json
        .env.example
        .gitignore
        ...
```

That tree is the installed version: package code, templates, starter UI, README, pyproject.toml, LICENSE, and examples. `setup.py` and `MANIFEST.in` are the packaging files that put this tree in the wheel. To work on the SDK itself and keep git history, use the clone and editable install above.

To pin a release, append `@` and a tag once one is published (none yet), for example `pip install git+https://github.com/aifluxx/aifluxx-sdk@v1.2.0`.

You need an approved developer account to get an API key. Sign up at https://developer.aifluxx.co.za/signup; accounts need approval before you can create a key.

## Log in

`aifluxx login` uses production when no other host is set: platform `aifluxx`, API root `https://api.aifluxx.co.za`. It prints that platform before it checks the key. A URL already saved in the credentials file is used before that default, so `aifluxx login --url https://dev.aifluxx.co.za` keeps later commands on the dev host. Pass `--platform aifluxx` or `--url https://api.aifluxx.co.za` to save production again.

Keys from Home start with `afx_dev_`. That prefix is the developer key on production and on the dev host. Paste the one Home showed:

```bash
aifluxx login
aifluxx login --url https://api.aifluxx.co.za
```

For the dev host, pass `--platform dev`:

```bash
aifluxx login --platform dev
aifluxx login --platform dev --api-key afx_dev_…
```

`login` calls `GET /api/dev/me` before it writes the credentials file. A rejected key or an unreachable host prints the error and does not say `Saved`. A key created on one host does not verify on the other.

Pipe a key with `--api-key-stdin`. That reads stdin directly, so `getpass` is not used and Python does not emit `GetPassWarning`:

```bash
printf '%s' "$AIFLUXX_API_KEY" | aifluxx login --api-key-stdin --platform dev
```

Override the host for this login with `--url`, or for every command in the current process with `AIFLUXX_API_URL`:

```bash
aifluxx login --url https://api.aifluxx.co.za --api-key afx_dev_…
export AIFLUXX_API_URL=https://dev.aifluxx.co.za
```

The API root is chosen in this order: `--url` (or the `url` argument to `AifluxxClient`), then `--platform`, then `AIFLUXX_API_URL`, then the URL saved in `~/.aifluxx/credentials`, then `https://api.aifluxx.co.za`. When `AIFLUXX_API_URL` is unset, later commands use the saved login URL, including a dev host from `aifluxx login --url https://dev.aifluxx.co.za` or `aifluxx login --platform dev`.

Named platforms:

| `--platform` | API root |
|---|---|
| `aifluxx` | `https://api.aifluxx.co.za` |
| `dev` | `https://dev.aifluxx.co.za` |

`dev` is the dev API at `https://dev.aifluxx.co.za`. `aifluxx` is production. Any other host is a custom `--url`.

```bash
aifluxx login --platform dev
aifluxx login --platform aifluxx --api-key afx_dev_…
```

Credentials are written to `~/.aifluxx/credentials`. On macOS and Linux the file is mode `0600` and the directory is mode `0700`. On Windows the file and its folder allow only the current user. If that lock cannot be set, login stops and the new key file is removed. The override for the path is `AIFLUXX_CREDENTIALS`. The file stays on your machine. Do not commit it.

## Author a package

```bash
aifluxx init --list
aifluxx init my-agent --template compliance
aifluxx validate
aifluxx push
aifluxx run "Summarise open compliance tasks"
aifluxx run my-agent "Summarise open compliance tasks"
aifluxx submit
```

`init` scaffolds `spec.yaml`, `instructions.md`, a short README, and `samples.yaml`. In a terminal, `aifluxx init` with no slug prompts for one. Outside a terminal it prints a usage line. `aifluxx init --list` prints the starters and does not write a folder. The default starter is `compliance` in both `init --help` and `init --list`. Starter tools and aliases match `GET /api/dev/templates`. `compliance` declares `list_obligations`. `finance` declares `ask_assistant`. `qa-over-documents` declares `search_company_knowledge` and `ask_assistant`. `standup` and `account-snapshot` declare their list tools and `search_company_knowledge`, and do not add `get_document`. Old ids are aliases: `compliance-checklist`, `finance-summariser`, and `qa-documents`. The ask tool id follows the API host: AIFluxx hosts, and a machine that is not logged in, use `ask_assistant`. `search_documents` is a former name: `validate` rejects it and tells you to use `search_company_knowledge`. New packages use schema `aifluxx/agent/v1`. `pricing.currency` is the logged-in org's currency when `GET /api/dev/me` includes one. A ZA-region org with no currency gets `ZAR`. With no org currency and no ZA region, including when you are not logged in, the scaffold uses `USD`.

`validate` uses `GET /api/dev/tools` when you are logged in and that route exists. If you are not logged in, the route is missing, or the catalogue cannot be read, it uses the bundled allow-list. `push` checks the same host catalogue before it uploads, so a tool the host does not publish fails locally instead of as a `422 unknown_tool`. `push` uploads the folder and creates a Draft. It does not `git push`.

`status`, `push`, `submit`, `import-git`, and `keys` print a short text view. States use one casing (`Draft`, `Submitted`, `Published`, `Rejected`, and the same for the other known states). `--json` prints the API payload unchanged. It works on the command (`aifluxx status --json`) and before it (`aifluxx --json status`).

`aifluxx push` sends one request:

| | |
|---|---|
| Method and path | `POST /api/dev/agents/{slug}/versions` |
| Request `Content-Type` | `multipart/form-data` with a boundary. The body is not raw gzip, and the request is not `Content-Type: application/gzip`. |
| Field `package` | File. Filename `package.tar.gz`. Part `Content-Type: application/gzip`. Bytes are a gzip-compressed ustar archive (magic `1f 8b`). Paths are relative to the package root. `.aifluxx` and a leftover metadata directory from an older install are left out. |
| Field `metadata` | Form field, no filename. Part `Content-Type: application/json`. UTF-8 JSON object: `slug`, `version` (the semver from `spec.yaml`), `schema`, and `spec` (the parsed `spec.yaml`). |

The host should read `package` as an uploaded file and `metadata` as a form string, then `json.loads` that string. Gzip magic byte `0x8b` is inside the `package` part only.

`run` takes a prompt, and a slug when you are not inside the package. Inside the package directory, `aifluxx run PROMPT` reads the slug from `spec.yaml`. Otherwise pass it: `aifluxx run SLUG PROMPT` or `aifluxx run PROMPT --slug SLUG`. The same slug is the one `run` sends to the API. With no prompt, `aifluxx run` reads one prompt from stdin. In a terminal, no prompt prints usage and exits 1.

`submit` and `run` call `/api/dev/agents/{slug}/versions/{version_id}/...`. `version_id` is a UUID. The CLI does not send the word `latest` or a semver such as `0.1.0` in that path. It uses the UUID saved at push, or looks the slug up with `GET /api/dev/agents`. Pass `--version <uuid>` to choose one yourself. A semver passed to `--version` is looked up, not sent as the path id.

Other commands:

```bash
aifluxx status
aifluxx import-git https://github.com/your-org/your-agent
aifluxx keys list
aifluxx keys rotate <key-id>
aifluxx keys revoke <key-id>
aifluxx source
```

After a successful push the CLI writes `.aifluxx/agent.lock` in the package. The lock stores the slug and the semver from `spec.yaml`. `version_id` is filled from the push response: an explicit `version_id`, the id on the nested version object, or the response `id` when `version` is the semver that was just uploaded (that object also includes the package slug). It stays `null` when the response has no version UUID. `submit` and `run` use that UUID when it is present, and otherwise look the slug up with `GET /api/dev/agents`. The lock directory is not uploaded.

## Starter UI

The SDK ships the [AIFluxx Starter UI](https://github.com/aifluxx/aifluxx-starter-ui), a local developer console for agent packages. Copy it out and run it with Node 20+:

```bash
aifluxx starter-ui my-console   # defaults to ./aifluxx-starter-ui
cd my-console && npm install && npm run dev
```

The command refuses a non-empty folder unless you pass `--force`. The bundled upstream commit is recorded in `aifluxx_sdk/starter_ui/UPSTREAM`; maintainers refresh it with `python scripts/sync_starter_ui.py`.

## Getting a developer key

Sign up for a developer account at https://developer.aifluxx.co.za/signup. For help or access questions, contact developer@aifluxx.com.

## API keys

`aifluxx keys` calls the developer key API:

| Command | Request |
|---|---|
| `aifluxx keys list` | `GET /api/dev/keys` |
| `aifluxx keys create` | `POST /api/dev/keys` |
| `aifluxx keys rotate <id>` | `POST /api/dev/keys/{id}/rotate` |
| `aifluxx keys revoke <id>` | `POST /api/dev/keys/{id}/revoke` |

List responses omit the secret. The text view prints each key's `name` when the API sends one, then the id, prefix, and state. Create and rotate print the new secret once (`key_once`); it is left out of the text view and the JSON payload. `--name` on create sets the name (at most 80 characters). Omit it and the API uses `Sandbox key`. `--save` on create or rotate replaces the key in `~/.aifluxx/credentials`. Revoke asks for confirmation unless you pass `--yes`.

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

Omit `url` and the client uses the same order as the CLI: `AIFLUXX_API_URL`, then the saved login URL, then production. `AifluxxClient(api_key="afx_dev_…")` is that form. `client.mcp_url` is the MCP endpoint for whichever root was resolved.

`client.mail.mailboxes(business_id=…)` lists connected identities you may name as `from_`. `from_` is required and must match a connected mailbox (`imap_mail`, `gmail_mail`, or `ms_graph_mail`). Send is immediate. The key must be a company admin or delegate. Multi-business users pass `business_id`.

`client.send(...)` (A2A chat with an agent) is **coming soon / not yet available**. It currently raises `NotImplementedError`; use `aifluxx run` (or the developer runs API) to run an agent today. Mail send does not use it.

Authorization is `Authorization: Bearer` with a Connected-apps key (`afx_live_…` or `mcpat_…`) or a developer key from Home (`afx_dev_…`).

## Errors from the API

`afx_dev_` keys that the host rejects, a failed push, and a redirect are printed with the HTTP status, the method, the URL, and the response body. A 401 is the host rejecting the bearer key (the body may say `Sign in again to create a key.`). A 500 is a host failure on a request that did reach the API, including push. The SDK does not follow redirects. A 307 whose `Location` is `http://...` is reported as a TLS downgrade instead of being followed.

`aifluxx run` reads an error body before it raises. A streamed 4xx or 5xx is shown as that host message, not as `httpx.ResponseNotRead`.

## MCP

MCP clients talk to the host. This package does not embed an MCP server. The MCP URL is the resolved API root plus `/mcp/`, with a trailing slash. Production is `https://api.aifluxx.co.za/mcp/`. A dev login uses `https://dev.aifluxx.co.za/mcp/`. `AifluxxClient.mcp_url` returns that URL for the client.

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

Use the HTTPS URL exactly as shown, including the trailing slash. Multi-business keys pass `business_id` the same way the Python client does.

## Develop

```bash
pip install -e ".[dev]"
pytest
python -m build
twine check dist/*
```

Requires Python 3.11 or newer.

Do not push a `v*` tag to try a release. `.github/workflows/publish.yml` runs on `workflow_dispatch` and on tags `v*`, and that job uploads to PyPI.
