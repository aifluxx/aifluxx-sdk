"""A contract between two agents for one call.

The caller offers the work. The callee accepts it. The document names both
agents, the skill, and the tokens the call will use. A call with no money
amount settles when the callee accepts, including when the token count is
zero. A call with a money amount stays an offer until a payment mandate
exists. This module does not charge a card and does not call the other agent.

The same rules live in dubai-agents at backend/a2a_server/agent_contract.py.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

AP2_EXTENSION_URI = "https://github.com/google-agentic-commerce/ap2/tree/v0.1"
PARTY_KINDS = frozenset({"orchestrator", "developer", "sdk", "connector"})
CART_MINUTES = 15


class ContractError(ValueError):
    """The offer is not a contract two agents can make."""


@dataclass(frozen=True)
class AgentParty:
    """One side of a call. A connector party names the connector. It carries no secret."""

    agent_id: str
    name: str
    kind: str

    def as_dict(self) -> dict[str, str]:
        return {"agent_id": self.agent_id, "name": self.name, "kind": self.kind}


def offer(
    *,
    caller: AgentParty,
    callee: AgentParty,
    skill_id: str,
    token_count: int = 0,
    amount_minor: int = 0,
    currency: str = "tokens",
    task_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The caller proposes a contract to the callee. Nothing is settled yet."""

    _check_parties(caller, callee)
    _check_terms(skill_id, token_count, amount_minor, currency)
    moment = _utc(now)
    task = task_id or str(uuid.uuid4())
    body = {
        "contract_id": task,
        "caller": caller.as_dict(),
        "callee": callee.as_dict(),
        "skill_id": skill_id,
        "token_count": token_count,
        "amount_minor": amount_minor,
        "currency": currency,
        "extension_uri": AP2_EXTENSION_URI,
        "cart_expires_at": (moment + timedelta(minutes=CART_MINUTES)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    body["cart_hash"] = _hash(body)
    document = {
        "status": "offered",
        "contract": body,
        "cart": _cart(body),
        "receipt": None,
        "error": None,
    }
    return document


def accept(document: dict[str, Any], acceptor: AgentParty, *, now: datetime | None = None) -> dict[str, Any]:
    """The callee accepts. A free call settles. A priced call waits for payment."""

    contract = document.get("contract") or {}
    callee = contract.get("callee") or {}
    if acceptor.kind not in PARTY_KINDS:
        raise ContractError("acceptor kind must be orchestrator, developer, sdk, or connector")
    if acceptor.agent_id != callee.get("agent_id"):
        return _declined(document, "only the called agent can accept this contract")
    if document.get("status") == "settled":
        return document
    if int(contract.get("amount_minor") or 0) > 0:
        return {
            "status": "payment_required",
            "contract": {**contract, "status": "offered"},
            "cart": document.get("cart"),
            "receipt": None,
            "error": {
                "code": "payment_required",
                "price_minor": contract["amount_minor"],
                "currency": contract["currency"],
                "extension_uri": AP2_EXTENSION_URI,
            },
        }
    moment = _utc(now)
    receipt = {
        "ap2.receipts.PaymentReceipt": {
            "payment_intent_id": None,
            "settlement": "free",
            "amount": {"currency": contract["currency"], "value": _money(contract)},
            "token_count": contract["token_count"],
            "caller": contract["caller"],
            "callee": contract["callee"],
            "task_id": contract["contract_id"],
            "settled_at": moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    }
    return {
        "status": "settled",
        "contract": {**contract, "status": "settled"},
        "cart": document.get("cart"),
        "receipt": receipt,
        "error": None,
    }


def _check_parties(caller: AgentParty, callee: AgentParty) -> None:
    for party in (caller, callee):
        if party.kind not in PARTY_KINDS:
            raise ContractError("agent kind must be orchestrator, developer, sdk, or connector")
        if not party.agent_id.strip() or not party.name.strip():
            raise ContractError("each agent needs an id and a name")
    if caller.agent_id == callee.agent_id:
        raise ContractError("a contract is between two agents")


def _check_terms(skill_id: str, token_count: int, amount_minor: int, currency: str) -> None:
    if not skill_id.strip():
        raise ContractError("skill_id is required")
    if token_count < 0 or amount_minor < 0:
        raise ContractError("token count and amount cannot be negative")
    if currency != "tokens" and (len(currency) != 3 or not currency.isalpha()):
        raise ContractError("currency is tokens or a 3-letter code")
    if currency == "tokens" and amount_minor != 0:
        raise ContractError("a token contract has no money amount")


def _cart(contract: dict[str, Any]) -> dict[str, Any]:
    label = f"{contract['callee']['name']} — {contract['skill_id']}"
    if contract["token_count"]:
        label = f"{label} — {contract['token_count']} tokens"
    amount = {"currency": contract["currency"], "value": _money(contract)}
    return {
        "ap2.mandates.CartMandate": {
            "contents": {
                "id": contract["contract_id"],
                "caller": contract["caller"],
                "callee": contract["callee"],
                "user_cart_confirmation_required": False,
                "payment_request": {
                    "details": {
                        "id": contract["contract_id"],
                        "display_items": [{"label": label, "amount": amount}],
                        "total": {"label": "Total", "amount": amount},
                    }
                },
                "cart_expiry": contract["cart_expires_at"],
                "merchant_name": contract["callee"]["name"],
            }
        }
    }


def _money(contract: dict[str, Any]) -> str:
    if contract["currency"] == "tokens":
        return "0.00"
    return f"{contract['amount_minor'] / 100:.2f}"


def _hash(body: dict[str, Any]) -> str:
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _utc(now: datetime | None) -> datetime:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _declined(document: dict[str, Any], reason: str) -> dict[str, Any]:
    contract = document.get("contract") or {}
    return {
        "status": "declined",
        "contract": {**contract, "status": "declined"},
        "cart": document.get("cart"),
        "receipt": None,
        "error": {"code": "declined", "reason": reason},
    }
