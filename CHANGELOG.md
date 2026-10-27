# Changelog

## Unreleased

### Changed

- `aifluxx login` resolves the developer API host from `--platform` (`truest` or `za`; `aifluxx` is an alias of `za`) and `--env` (`dev` or `prod`). ZA production is `https://developer.aifluxx.co.za`. ZA dev is `https://dev.developer.aifluxx.co.za`. `--platform dev` remains a deprecated alias of ZA dev. `--url` still overrides the named host. `AIFLUXX_PLATFORM`, `AIFLUXX_ENV`, and `~/.aifluxx/config.json` supply the same choice. `aifluxx login --help` lists platforms and envs without host URLs, and prints only the one resolved host.

### Fixed

- Starter tools and aliases match `GET /api/dev/templates`. `compliance` scaffolds `list_obligations`. `finance` and the document Q&A starter scaffold `ask_assistant`. `standup` and `account-snapshot` no longer add `get_document`. `finance-summariser` and `qa-documents` select those starters, along with `compliance-checklist`. The ask tool id follows the API host.

### Breaking

- The legacy agent schema id is no longer accepted. Packages must use `aifluxx/agent/v1`.
- The legacy ask tool was removed and has no alias. Delete it from `tools`.
- The legacy client class was removed. Construct `AifluxxClient`.
- Legacy platform names were removed. Named hosts are `aifluxx` (`https://api.aifluxx.co.za`) and `dev` (`https://dev.developer.aifluxx.co.za`). Any other host is a custom `--url`.
- The legacy credentials migration was removed. New logins do not read or move an older credentials file, and the old credentials environment variable is ignored. The store is `~/.aifluxx/credentials`, overridable with `AIFLUXX_CREDENTIALS`.
