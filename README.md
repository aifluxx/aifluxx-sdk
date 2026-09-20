# aifluxx-sdk

Python client for **Truest** (and Enterprise after port). Same credentials as Connected apps (`afx_live_…` or `mcpat_…`). Tag-pinned like `aifluxx-connectors`. Not on PyPI in v0.1.

Specs: [DEV-162](../dubai-agents/specs/DEV-162-truest-a2a-sdk/spec.md) (A2A + this package) · [DEV-165](../dubai-agents/specs/DEV-165-mailbox-agent-send/spec.md) (send from a connected mailbox) · [DEV-166](../dubai-agents/specs/DEV-166-agent-marketplace/spec.md) (partner marketplace).

## How it works

Three ways to talk to the product. They all act **as the user who owns the key**.

| Surface | Who uses it | Protocol |
|---|---|---|
| **Chat** | A person in Chief of Staff | In-app. The agent calls the send **tool**. |
| **MCP** | Cursor, Claude, ChatGPT | DEV-158 `/mcp`. Apps, not other agents. |
| **SDK / A2A** | Other agents and Python scripts | This package. Mail send is REST in v0.1. Chat-to-a-skill (`client.send("chief_of_staff", …)`) is A2A (`/a2a`) when DEV-162 phases 1–2 are up. |

Mailbox send (DEV-165) is one host function. Chat, MCP, and the SDK all call it. Rules are the same everywhere:

- Key must be a **company admin or delegate**.
- **`from` is required** and must match a connected mailbox (`imap_mail`, `gmail_mail`, `ms_graph_mail`).
- Send is **immediate**. No draft step.
- Invites and password reset do **not** use this path (platform Gmail).

```
Your script / remote agent
        │  aifluxx-sdk  (Bearer afx_live_…)
        ▼
Truest API  POST /api/companies/{id}/mail/send
        │  resolve From → connector instance
        ▼
IMAP SMTP  or  Gmail API  or  Microsoft Graph
        │
        ▼
pinnacle@palmerclan.us (or whichever From you named)
```

## Install (local)

```text
pip install -e C:\1_Local\Apps\aifluxx-sdk
```

Git pin, same pattern as connectors (private repo; do not float on `main`):

```text
aifluxx-sdk @ git+https://github.com/aifluxx/aifluxx-sdk.git@<sha>
```

CI (pytest + package build) runs on every `main` push and pull request. Push a `v*` tag to cut a GitHub Release.

## Mail

```python
from aifluxx_sdk import TruestClient, AuthError, Forbidden, MailboxNotConnected

client = TruestClient("https://api.aifluxx.com", api_key="afx_live_…")
client.mail.send(
    from_="pinnacle@palmerclan.us",
    to="colleague@example.com",
    subject="Q4 stock",
    body="Please find the note below.",
    business_id="<company uuid>",
)
```

`client.mail.mailboxes(business_id=…)` lists connected identities you may name as `from_`.

## Chat skills (A2A — after DEV-162 server)

```python
for ev in client.send("chief_of_staff", "Draft a note to Coert", business_id="…", stream=True):
    print(ev)
```

Until `/a2a` is mounted, `send()` raises `NotImplementedError`. Mail does not wait on A2A.

## Partners — listing your agent on the Marketplace (DEV-166)

You host your agent. AIfluxx calls it over A2A and pays you a share of usage.

1. Build an A2A agent (any language; `a2a-sdk` for Python). Publish `/.well-known/agent-card.json`. A `serve_agent(card, handler)` helper lands in this package with DEV-166.
2. Sign up as a partner, finish **Stripe Connect Express** onboarding.
3. Create a **Listing**: card URL, name, description, price per task (or free). Submit. A platform admin approves.
4. Subscribers **Hire** you from Marketplace. Each task they run is metered. AIfluxx bills them; you get your share (default 80%) by monthly Connect payout.

You receive the prompt and whatever the subscriber passes. You never get their connector documents or company data by default.

## Auth

`Authorization: Bearer` with a Connected-apps key. Multi-business users must pass `business_id` (same as MCP). Wrong company or non-admin → `Forbidden`. Named From not connected → `MailboxNotConnected`.
