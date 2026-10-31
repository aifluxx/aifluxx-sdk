# Changelog

## Unreleased

## 1.3.0 - 2026-10-31

### Added

- `aifluxx init SLUG --venv` creates `SLUG/.venv` with `python -m venv`. The default `--no-venv` scaffolds the package only. `.venv` stays on the machine: `validate` skips it, and `push` leaves it out of the upload.
- Optional extra `aifluxx-sdk[mcp]` (`mcp>=1.20,<2`, FastMCP). `aifluxx mcp` and `aifluxx-mcp` serve the developer platform over stdio, or streamable HTTP with `--http`. Auth is `AIFLUXX_API_KEY` or `aifluxx login`. The key is left out of config, tool results, and logs.
- Tools wrap the published developer routes: projects and agents (`/api/dev/agents`), connector catalog and platform data schema (`/api/dev/connectors`), local manifest validation, push, submit for review, review status, and companion chat. Handoff and portfolio tools call the routes documented for platform v1.1 (aifluxx-developer PR 46) and say `requires platform v1.1` in the tool description.
- Resources for the agent manifest schema, connector schema rules, and a stored agent manifest. Prompts `start_new_agent` and `resume_from_handoff`.
- `aifluxx init --cursor-mcp` writes `.cursor/mcp.json` for the local server. The file does not contain an API key.

## 1.2.0 - 2026-10-31

### Added

- The recommended local install is a clone and an editable install: `git clone https://github.com/aifluxx/aifluxx-sdk`, then `pip install -e ./aifluxx-sdk` inside a virtual environment. The clone is a normal SDK folder in the project. Editable installs include the templates and the starter UI.
- `aifluxx source [DEST]` copies the installed SDK into a folder (default `./aifluxx-sdk`): package code, templates, starter UI, README, pyproject.toml, LICENSE, and examples. A non-empty destination is left unchanged unless you pass `--force`. Those files ship in the wheel and the sdist, so the command works after a pip install as well as from a checkout.

## 1.1.0 - 2026-10-31

### Added

- `aifluxx --version` prints the SDK version.
- `aifluxx starter-ui [DEST]` copies the bundled AIFluxx Starter UI into a folder. The UI ships inside the wheel and sdist, so no separate download is needed.

### Fixed

- The API root follows an explicit URL, then `AIFLUXX_API_URL`, then the URL saved by `aifluxx login`, then `https://api.aifluxx.co.za`. `--platform dev` is `https://dev.aifluxx.co.za`. A dev host saved with `aifluxx login --url` is reused when the environment variable is unset. MCP URLs are that API root plus `/mcp/`.
- `aifluxx keys create` calls `POST /api/dev/keys` and prints `key_once` once. The secret is left out of the text view and the JSON payload.
- `aifluxx run` with no prompt reads stdin. In a terminal it prints usage and exits 1.
- `aifluxx login` sends a Home key (`afx_dev_`) to `https://api.aifluxx.co.za` and checks it with `GET /api/dev/me`. The prefix is the developer key on production and on the dev host. A key for the wrong host is rejected by that check and is not saved.
- On Windows, login saves the key. The credentials file and its folder are limited to the current user. Unix modes are not how Windows records that, so the old mode check rejected every save.
- Starter tools and aliases match `GET /api/dev/templates`. `compliance` scaffolds `list_obligations`. `finance` and the document Q&A starter scaffold `ask_assistant`. `standup` and `account-snapshot` no longer add `get_document`. `finance-summariser` and `qa-documents` select those starters, along with `compliance-checklist`. The ask tool id follows the API host.

### Breaking

- The legacy agent schema id is no longer accepted. Packages must use `aifluxx/agent/v1`.
- The legacy ask tool was removed and has no alias. Delete it from `tools`.
- The legacy client class was removed. Construct `AifluxxClient`.
- Legacy platform names were removed. Named hosts are `aifluxx` (`https://api.aifluxx.co.za`) and `dev` (`https://dev.aifluxx.co.za`). Any other host is a custom `--url`.
- The legacy credentials migration was removed. New logins do not read or move an older credentials file, and the old credentials environment variable is ignored. The store is `~/.aifluxx/credentials`, overridable with `AIFLUXX_CREDENTIALS`.
