# Handoffs

Shared project handoffs live in this folder, one markdown file per finished piece of work. Another person should be able to continue from the file alone.

## File name

`YYYY-MM-DD-<topic-slug>.md`

- **Date.** The work date, `YYYY-MM-DD`. That is the date of the last user message before the handoff was requested, in that message's local offset. Use the day the file is written only when the chat has no earlier timestamp.
- **Topic slug.** Lowercase letters, digits, and hyphens. Take it from the topic the user named. If they did not name one, slug the conversation title.

Example: `2026-10-31-demo-vertical-skill.md`

## Collisions

If `YYYY-MM-DD-<topic-slug>.md` already exists, do not overwrite it. Write `YYYY-MM-DD-<topic-slug>-2.md`, then `-3`, and so on.

## Secrets

Never put secrets in these files. That includes API keys, passwords, tokens, connection strings, private keys, `.env` values, and Key Vault secret values. Refer to a secret as "the value is or is not in the approved secret store."

Reference plans, issues, commits, and diffs by path or URL. Do not paste them.
