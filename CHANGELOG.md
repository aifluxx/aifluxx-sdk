# Changelog

## Unreleased

### Added

- `aifluxx starter-ui [DEST]` copies the bundled AIFluxx Starter UI into a folder. The UI ships inside the wheel and sdist, so no separate download is needed.

### Fixed

- `aifluxx login` sends a Home key (`afx_dev_`) to `https://api.aifluxx.co.za` and checks it with `GET /api/dev/me`. The prefix is the developer key on production and on the dev host. A key for the wrong host is rejected by that check and is not saved.
- On Windows, login saves the key. The credentials file and its folder are limited to the current user. Unix modes are not how Windows records that, so the old mode check rejected every save.
- Starter tools and aliases match `GET /api/dev/templates`. `compliance` scaffolds `list_obligations`. `finance` and the document Q&A starter scaffold `ask_assistant`. `standup` and `account-snapshot` no longer add `get_document`. `finance-summariser` and `qa-documents` select those starters, along with `compliance-checklist`. The ask tool id follows the API host.

### Breaking

- The legacy agent schema id is no longer accepted. Packages must use `aifluxx/agent/v1`.
- The legacy ask tool was removed and has no alias. Delete it from `tools`.
- The legacy client class was removed. Construct `AifluxxClient`.
- Legacy platform names were removed. Named hosts are `aifluxx` (`https://api.aifluxx.co.za`) and `dev` (`https://dev.developer.aifluxx.co.za`). Any other host is a custom `--url`.
- The legacy credentials migration was removed. New logins do not read or move an older credentials file, and the old credentials environment variable is ignored. The store is `~/.aifluxx/credentials`, overridable with `AIFLUXX_CREDENTIALS`.
