# aifluxx-sdk

Python client and `aifluxx` command-line tool for [AIFluxx](https://aifluxx.co.za). The CLI authors an agent package from any IDE terminal. The library calls the developer API and connected-mailbox send as the person who owns the key.

Signup, docs, and the developer site stay on the AIFluxx host. This repository does not ship a UI.

## Install with Cursor

Open Cursor, copy the prompt below, and paste it into Cursor's chat. Cursor sets up everything.

```text
Set up aifluxx in this workspace.

Check that Python is 3.11 or newer. Run `python3 --version` or `python --version`. Stop if it is older than 3.11.

Optionally create and activate a virtual environment, then install into it. Skip this if I want the current environment.
- bash: `python -m venv .venv` then `source .venv/bin/activate`
- Windows PowerShell: `python -m venv .venv` then `.\.venv\Scripts\Activate.ps1`

Install aifluxx 1.3.1:

pip install git+https://github.com/aifluxx/aifluxx-sdk@v1.3.1

Run `aifluxx login`. Tell me to paste the API key from Home myself. Never echo the key, never pass it with `--api-key`, and never write it into the repo. In a terminal, `aifluxx login` prompts `API key from Home` and hides the input. If this shell is not a terminal, the command exits without saving a key. Ask me to run `aifluxx login` in Cursor's terminal and paste the key there.

Scaffold a package. Use the slug I give you, or ask me for one.
- With a virtual environment inside the package: `aifluxx init <project> --venv`
  This writes spec.yaml, instructions.md, README.md, and samples.yaml, and creates `<project>/.venv` with `python -m venv` using the Python that is running `aifluxx`. That directory is local. Do not commit it. `aifluxx push` does not upload it. It is separate from the environment used to pip install aifluxx.
- Without one: `aifluxx init <project> --no-venv`
  This is the default. Plain `aifluxx init <project>` does the same. The same files are written, and no `.venv` is created.

Then run `aifluxx validate <project>`. `aifluxx validate` with no path only works when the current directory contains spec.yaml, so change into `<project>` first if you omit the path.

Report what you did: the Python version, whether you created and activated an install virtual environment, the pip command, whether login saved credentials, which init command you ran and whether `<project>/.venv` exists, and the validate result.
```

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

To pin a release, append `@` and a tag once one is published (none yet), for example `pip install git+https://github.com/aifluxx/aifluxx-sdk@v1.3.1`.

You need an approved developer account to get an API key. Sign up at https://developer.aifluxx.co.za/signup; accounts need approval before you can create a key.

## Components

What the SDK contains. Everything below exists in this repo unless it is marked **planned**.

| Component | Where | What it does |
|---|---|---|
| CLI `aifluxx` | `src/aifluxx_sdk/cli.py` | `login`, `init` (with `--template`, `--list`, `--venv`, `--cursor-mcp`), `validate`, `push`, `submit`, `status`, `run`, `import-git`, `keys list/create/rotate/revoke`, `chat`, `companion status`, `starter-ui`, `source`, `mcp`. See [Log in](#log-in), [Author a package](#author-a-package) and [API keys](#api-keys). |
| Python client | `client.py` (`AifluxxClient`, `CompanionClient`), `dev.py` (developer platform `/api/dev`) | Programmatic access. See [Python](#python). |
| Credentials | `credentials.py` | API URL and key resolution: `AIFLUXX_API_URL`, `AIFLUXX_API_KEY`, `AIFLUXX_CREDENTIALS`, then the file saved by `aifluxx login`. |
| Package validator | `package.py`, `catalog.py`, `lockfile.py` | Offline manifest checks with the same codes as the host, tool allow-lists (the host `GET /api/dev/tools` wins when you are logged in), and the per-package lock. |
| Templates | `templates.py` | Starter packages for `aifluxx init --template`. See [Templates](#templates). |
| Mail | `mail.py` | Connected-mailbox send, with the same rules as the in-app agent tool. Example: `examples/send_mail.py`. |
| Starter UI | `src/aifluxx_sdk/starter_ui/` | Local React app (screens: Run console, Tools, Status, Settings) behind a local proxy that keeps the key server-side. Layout file: `layout.py`. See [Starter UI](#starter-ui). |
| A2UI components | Developer portal A2UI SDK (`aifluxx-a2ui-sdk` registry, 104 entries) | UI building blocks the companion's `build` mode and the Starter UI use. Examples: DataTable, ChatPanel, Bar/Line/Area charts, Stat/KPI, Timeline, ApprovalGate, AgentRunStatus, ToolCallTrace, StreamingOutput, UsageMeter (tokens/cost ZAR), API key management, Permissions matrix, Citations/Sources and Tree view. A graph view component is **planned**. |
| Companion | `aifluxx chat` / `aifluxx companion` | See [Companion](#companion). |
| MCP server | `mcp_server.py` (extra `aifluxx-sdk[mcp]`) | Tools for projects, agents, connectors, validate, push, review, companion, handoffs and portfolios. See [MCP server](#mcp-server). Cursor config comes from `aifluxx init --cursor-mcp`. |
| Source copy | `source.py` | `aifluxx source` writes the SDK sources into a project folder. |

## Templates

```bash
aifluxx init --list                      # show templates
aifluxx init my-agent --template finance # scaffold from a template
```

| Template | Purpose |
|---|---|
| `compliance` | Lists open obligations and missing evidence from documents the caller can already see. |
| `finance` | Explains period movements in plain language, with a citation on every number. |
| `qa-over-documents` | Answers questions from named connectors. Read only, no write tools. |
| `standup` | Covers yesterday, today and blockers from tasks and mail the user can already see. |
| `account-snapshot` | Builds a one-page account brief from CRM notes and vault files. |

Then `aifluxx validate`, `aifluxx push`, `aifluxx submit`. Tool ids match `GET /api/dev/templates` on the host.

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

`init` scaffolds `spec.yaml`, `instructions.md`, a short README, and `samples.yaml`. `aifluxx init SLUG --venv` also creates `SLUG/.venv` with `python -m venv`. `aifluxx init SLUG --no-venv` is the default and scaffolds the package only. `--list` does not write a package or a `.venv`. `aifluxx init SLUG --cursor-mcp` also writes `SLUG/.cursor/mcp.json` for the local MCP server. That file does not contain an API key. `--list` does not write it. Do not commit `.venv`. `validate` skips files inside it, and `push` leaves it out of the upload. In a terminal, `aifluxx init` with no slug prompts for one. Outside a terminal it prints a usage line. `aifluxx init --list` prints the starters and does not write a folder. The default starter is `compliance` in both `init --help` and `init --list`. Starter tools and aliases match `GET /api/dev/templates`. `compliance` declares `list_obligations`. `finance` declares `ask_assistant`. `qa-over-documents` declares `search_company_knowledge` and `ask_assistant`. `standup` and `account-snapshot` declare their list tools and `search_company_knowledge`, and do not add `get_document`. Old ids are aliases: `compliance-checklist`, `finance-summariser`, and `qa-documents`. The ask tool id follows the API host: AIFluxx hosts, and a machine that is not logged in, use `ask_assistant`. `search_documents` is a former name: `validate` rejects it and tells you to use `search_company_knowledge`. New packages use schema `aifluxx/agent/v1`. `pricing.currency` is the logged-in org's currency when `GET /api/dev/me` includes one. A ZA-region org with no currency gets `ZAR`. With no org currency and no ZA region, including when you are not logged in, the scaffold uses `USD`.

`validate` uses `GET /api/dev/tools` when you are logged in and that route exists. If you are not logged in, the route is missing, or the catalogue cannot be read, it uses the bundled allow-list. `push` checks the same host catalogue before it uploads, so a tool the host does not publish fails locally instead of as a `422 unknown_tool`. `push` uploads the folder and creates a Draft. It does not `git push`. Both commands leave out `.aifluxx/`, `.venv/`, the legacy metadata directory, a top-level `sdk/` directory, `*.egg-info`, and paths listed in `.aifluxxignore`.

`status`, `push`, `submit`, `import-git`, and `keys` print a short text view. States use one casing (`Draft`, `Submitted`, `Published`, `Rejected`, and the same for the other known states). `--json` prints the API payload unchanged. It works on the command (`aifluxx status --json`) and before it (`aifluxx --json status`).

`aifluxx push` sends one request:

| | |
|---|---|
| Method and path | `POST /api/dev/agents/{slug}/versions` |
| Request `Content-Type` | `multipart/form-data` with a boundary. The body is not raw gzip, and the request is not `Content-Type: application/gzip`. |
| Field `package` | File. Filename `package.tar.gz`. Part `Content-Type: application/gzip`. Bytes are a gzip-compressed ustar archive (magic `1f 8b`). Paths are relative to the package root. `.aifluxx`, a leftover metadata directory from an older install, `.venv`, a top-level `sdk/` directory, `*.egg-info`, and paths in `.aifluxxignore` are left out. |
| Field `metadata` | Form field, no filename. Part `Content-Type: application/json`. UTF-8 JSON object: `slug`, `version` (the semver from `spec.yaml`), `schema`, and `spec` (the parsed `spec.yaml`). |

The host should read `package` as an uploaded file and `metadata` as a form string, then `json.loads` that string. Gzip magic byte `0x8b` is inside the `package` part only.

`validate` and the upload share one exclude list. These paths are left out of the secret scan and of `package.tar.gz`:

- `.aifluxx/` and a leftover metadata directory from an older install, at any depth
- `.venv/` at any depth (`aifluxx init --venv` creates it next to `spec.yaml`)
- the `sdk/` directory at the package root, so a vendored copy of this SDK is not checked or uploaded (its README, `examples/send_mail.py`, and test fixtures stay on your machine)
- a file or directory whose name matches `*.egg-info`, at any depth, including `sdk/src/*.egg-info` and metadata from an editable install
- every extra path listed in `.aifluxxignore` at the package root

`.aifluxxignore` is the exclude list. It is a gitignore-style file next to `spec.yaml`, and it does not change the spec sent to the host. Blank lines and lines that start with `#` are ignored. A trailing `/` matches a directory (`vendor/` matches a directory named `vendor` in any directory). A pattern with no `/` matches that name in any directory (`*.pem`). A pattern with a `/` in the middle is relative to the package root (`docs/*.md` matches `docs/a.md` and leaves `docs/sub/a.md` in the package). `**` matches across directories. `\` is read as `/`. Matching is case-sensitive. The defaults above always apply. A line that starts with `!`, a `..` segment, or a file that is not UTF-8 makes `validate` fail. The ignore file is uploaded unless a pattern excludes it. Leave `spec.yaml`, `instructions.md`, and declared subagent directories out of the list so the host still receives them. `.png`, `.jpg`, and `.webp` files that are not excluded are uploaded and are not secret-scanned. A nested directory named `sdk` is still packaged; add it to `.aifluxxignore` when it should be left out.

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

## Companion

`aifluxx companion` talks to the developer companion. `aifluxx chat` is the same chat.

```bash
aifluxx chat
aifluxx chat "how do I add a connector"
aifluxx chat --mode config --project my-agent "how do I add a connector"
aifluxx companion status
```

Log in first with `aifluxx login`. Chat and status use that saved key and the same API root as the other developer commands: `AIFLUXX_API_URL`, then the URL saved by login, then `https://api.aifluxx.co.za`. The key goes out as `Authorization: Bearer` and is never printed.

Inside a package (a folder with `spec.yaml`, the manifest `init`, `validate`, and `push` use), the slug is read from that file. Elsewhere pass `--project SLUG`.

With no message, `aifluxx chat` opens a prompt labeled with the mode (`build>` or `config>`). `/exit` or Ctrl-D leaves. `/build` and `/config` switch mode. `/mode` prints the current one. The default is `build`. `--mode build` or `--mode config` sets it for a one-shot message and for the start of the chat.

`build` is UI design and wiring: starter UI screens, components, A2UI, and how they connect to the agent. `config` is the agent instructions, the system prompt, tools, and connectors. Both modes talk to the same companion.

Each turn is `POST /api/dev/companion/messages` with `message`, `project_slug`, and `mode`. The message starts with a short focus line for that mode, so a host that ignores `mode` still gets the focus. The reply is printed. A refusal is shown as `Refused: …`.

`aifluxx companion status` calls `GET /api/dev/companion` and prints the version, approval, whether it is servable, the region endpoint, and the limits.

A 401 tells you to run `aifluxx login`. A 429 says the limit was reached. A 503, or a payload that is not servable, says the companion is not servable right now.

### Layout edit

A terminal cannot drag, so build mode places components in the Starter UI. `/layout` (build mode only) opens `http://127.0.0.1:5173/?layout=1` and watches `aifluxx.layout.json` in the package. It does not run a shell.

The page has a **Layout edit** toggle. Drag a block to reorder it, drag the corner to resize it, then **Save layout**. The file is canonical JSON (stable key order, packed on a 12-column grid) so diffs stay small. The write is local.

Press Enter in the chat after a save. The chat sends the layout diff to the companion, shows the suggestion, and asks `Apply these project file updates? [y/N]`. The default is no. Yes writes `aifluxx.wiring.json` from the layout, plus any companion file edits that stay on the allow-list inside the package: `instructions.md`, `spec.yaml`, `aifluxx.layout.json`, and files under `ui/`. Paths outside the package are refused.

Start the UI with the package path so Save writes that file:

```bash
AIFLUXX_PROJECT=/path/to/package AIFLUXX_LAYOUT_EDIT=1 npm run dev
```

From a copied starter (`aifluxx starter-ui`), run that in the copy and point `AIFLUXX_PROJECT` at the agent package. `?layout=1` turns Layout edit on when the page opens.

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

## MCP server

`pip install 'aifluxx-sdk[mcp]'` adds a local MCP server built with FastMCP from the official Python `mcp` SDK (`mcp>=1.20,<2`). The extra is optional. The rest of the SDK installs and runs without it.

Stdio is the default. `aifluxx mcp` and `aifluxx-mcp` start the same server. `aifluxx mcp --http` (or `aifluxx-mcp --http`) serves streamable HTTP on `http://127.0.0.1:8000/mcp`. `--host` and `--port` change that bind address.

Auth is the existing SDK config. `AIFLUXX_API_KEY` wins when it is set. Otherwise the server uses the key saved by `aifluxx login` (`~/.aifluxx/credentials`, or `AIFLUXX_CREDENTIALS`). The API root is `AIFLUXX_API_URL`, then the saved login URL, then `https://api.aifluxx.co.za`. The key is not written into MCP config, tool results, or logs.

### Cursor

`aifluxx init my-agent --cursor-mcp` writes this file at `my-agent/.cursor/mcp.json`. It does not contain an API key. Put the same JSON in a repo yourself if you skip the flag.

```json
{
  "mcpServers": {
    "aifluxx": {
      "command": "aifluxx",
      "args": ["mcp"]
    }
  }
}
```

Set `AIFLUXX_API_KEY` in the environment Cursor uses to launch the process, or run `aifluxx login` on that machine first.

### Other MCP clients

```json
{
  "mcpServers": {
    "aifluxx": {
      "command": "aifluxx-mcp"
    }
  }
}
```

Streamable HTTP, after `aifluxx mcp --http`:

```json
{
  "mcpServers": {
    "aifluxx": {
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

Clients discover tools, resources, and prompts from the MCP list methods. No custom integration is required.

### Tools

Projects are developer packages. Published OpenAPI 1.0.0 has no `/api/dev/projects` collection, so project tools use `GET` and `POST /api/dev/agents`. Companion `project_slug` is that package slug.

| Tool | Route |
|---|---|
| `projects_list`, `projects_get`, `projects_create` | `GET` / `POST /api/dev/agents` |
| `agents_list`, `agents_get`, `agents_create`, `agents_update` | `GET` / `POST /api/dev/agents`. There is no `GET /api/dev/agents/{slug}` on OpenAPI 1.0.0, so get filters the list. Save Agent is create or update. |
| `connectors_list_catalog`, `connectors_read_schema` | `GET /api/dev/connectors`. The dev developer host serves this path. Published OpenAPI 1.0.0 does not list it yet. The schema is `schema_version`, `access`, and entities with fields. Provider tool lists are dropped. |
| `connectors_list_connections` | `external_connections` on `GET /api/dev/agents`. Secrets are removed. `POST /api/dev/connections/discover` accepts secrets and is not a tool. |
| `validate_manifest` | Local `spec.yaml` check. No HTTP call. |
| `push_package` | `POST /api/dev/agents/{slug}/versions` |
| `submit_for_review` | `POST /api/dev/agents/{slug}/versions/{version_id}/submit` |
| `review_status` | `GET /api/dev/agents/{slug}/versions/{version_id}` (version, validator report, scan report, badges, and state) |
| `companion_send_message`, `companion_get_reply` | `POST /api/dev/companion/messages`. The reply is on that response. There is no separate GET. |
| `handoffs_create`, `handoffs_list`, `handoffs_get` | `POST` / `GET /api/dev/agents/{agent}/handoffs` and `GET .../handoffs/{handoff_id}`. **requires platform v1.1** |
| `portfolios_me`, `portfolios_overview`, `portfolios_org`, `portfolios_hide` | `GET /api/dev/portfolios/me`, `GET /api/dev/portfolios/overview`, `GET /api/dev/portfolios/orgs/{org_id}`, `POST .../hide`. **requires platform v1.1** |

Handoffs and portfolios are not in published OpenAPI 1.0.0. They follow the routes documented for aifluxx-developer PR 46. Until that API is on the host you are calling, those tools return the host's not-found error. Each tool description includes `requires platform v1.1`.

Agents read connector data through `connectors_read_schema`. They do not receive raw provider tools.

### Resources and prompts

| Kind | Name | What it is |
|---|---|---|
| Resource | `aifluxx://schemas/agent` | Agent manifest schema `aifluxx/agent/v1` |
| Resource | `aifluxx://schemas/connectors` | Platform connector schema rules |
| Resource template | `aifluxx://agents/{slug}/manifest` | Stored manifest from `GET /api/dev/agents`, secrets removed |
| Prompt | `start_new_agent` | Start a new agent (validate, platform schema, create, push, review) |
| Prompt | `resume_from_handoff` | Continue from a handoff. **requires platform v1.1** |

### Host MCP URL

`AifluxxClient.mcp_url` is still the host endpoint: the resolved API root plus `/mcp/`, with a trailing slash. Production is `https://api.aifluxx.co.za/mcp/`. A dev login uses `https://dev.aifluxx.co.za/mcp/`. That URL is the platform host. The server in this section runs locally and calls the developer API with the SDK client.

## Signals

**Planned.** There is no developer signals endpoint in the SDK yet. Once it ships, a developer can read only the signal types their project is granted for companies their project is granted. Person and PII signals are restricted. The planned shape is:

```python
# planned, not yet available
for s in client.signals.list(company_id, types=["<signal_type>"], since="2026-10-01"):
    ...
client.signal_types.list()
```

Today the platform's admin dashboards build developer activity signals (`signup`, `push`, `validation`, `submission`, `failure`, `handoff`, `connector_use`). Those are for platform admins and are not exposed to developers.

## Tracing with Langfuse

**Planned for the SDK.** The SDK does not send traces itself yet. The AIFluxx platform traces hosted agent runs in its own Langfuse, which is separate from the UAE Langfuse; never point an AIFluxx agent at the UAE instance. For local runs, set the standard Langfuse variables in `.env` (names only; take the values from your AIFluxx Langfuse project, never commit them):

```
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=
LANGFUSE_TRACING_ENVIRONMENT=
```

## Demo companies (dev sandbox)

The dev sandbox has 11 **fictitious** South African demo companies: Biltong & Bougainvillea Retail, Vaalkop Mining, Karoo Kraal Industrial Supply, Pincushion & Ironwood Medical Centre, Skaapsteker District Municipality, Korhaanfontein Metropolitan Municipality, Wolksloof Managing Agents, Grysbok Freight Forwarding, Suurvy Citrus & Wine, Boekenhout Advisory and Kuifkoppie Insurance Brokers. Each one has personas, knowledge documents, 24 months of financials and connector fixtures. Use them to try templates and vertical agents. They are dev only.

Slugs, verticals, fixtures and matching agents: [Demo companies](https://github.com/aifluxx/aifluxx-developer/blob/main/docs/developer/demo-companies.md) in the developer docs.

## Develop

```bash
pip install -e ".[dev]"
pytest
python -m build
twine check dist/*
```

Requires Python 3.11 or newer.

Do not push a `v*` tag to try a release. `.github/workflows/publish.yml` runs on `workflow_dispatch` and on tags `v*`, and that job uploads to PyPI.
