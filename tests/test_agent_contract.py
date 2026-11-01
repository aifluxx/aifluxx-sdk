from datetime import datetime, timezone

import pytest

from aifluxx_sdk.agent_contract import AgentParty, ContractError, accept, offer

CALLER = AgentParty("sdk-demo", "Demo agent", "sdk")
CALLEE = AgentParty("orchestrator", "Orchestrator", "orchestrator")
WHEN = datetime(2026, 11, 1, 18, 0, tzinfo=timezone.utc)


def _offer(**kwargs):
    return offer(caller=CALLER, callee=CALLEE, skill_id="chief_of_staff", now=WHEN, task_id="task-1", **kwargs)


def test_free_call_settles_as_a_contract_between_the_two_agents():
    settled = accept(_offer(token_count=0), CALLEE, now=WHEN)
    receipt = settled["receipt"]["ap2.receipts.PaymentReceipt"]

    assert settled["status"] == "settled"
    assert settled["error"] is None
    assert receipt["settlement"] == "free"
    assert receipt["payment_intent_id"] is None
    assert receipt["token_count"] == 0
    assert receipt["caller"]["agent_id"] == "sdk-demo"
    assert receipt["callee"]["agent_id"] == "orchestrator"
    assert settled["cart"]["ap2.mandates.CartMandate"]["contents"]["merchant_name"] == "Orchestrator"


def test_recorded_tokens_stay_free_until_there_is_a_money_amount():
    settled = accept(_offer(token_count=1200), CALLEE, now=WHEN)
    receipt = settled["receipt"]["ap2.receipts.PaymentReceipt"]

    assert settled["status"] == "settled"
    assert receipt["token_count"] == 1200
    assert receipt["amount"] == {"currency": "tokens", "value": "0.00"}
    assert "pm_" not in str(settled)


def test_a_priced_call_is_not_settled():
    offered = _offer(token_count=0, amount_minor=2500, currency="AED")
    waiting = accept(offered, CALLEE, now=WHEN)

    assert waiting["status"] == "payment_required"
    assert waiting["receipt"] is None
    assert waiting["error"]["code"] == "payment_required"
    assert waiting["error"]["price_minor"] == 2500
    assert waiting["error"]["currency"] == "AED"


def test_only_the_called_agent_can_accept():
    stranger = AgentParty("other", "Other", "developer")
    declined = accept(_offer(), stranger, now=WHEN)

    assert declined["status"] == "declined"
    assert declined["receipt"] is None


def test_accepting_twice_returns_the_same_receipt():
    first = accept(_offer(), CALLEE, now=WHEN)
    second = accept(first, CALLEE, now=WHEN)

    assert second == first


def test_a_connector_can_be_a_party_without_a_secret():
    connector = AgentParty("freshdesk", "Freshdesk", "connector")
    settled = accept(
        offer(caller=CALLER, callee=connector, skill_id="freshdesk", now=WHEN, task_id="task-2"),
        connector,
        now=WHEN,
    )

    assert settled["status"] == "settled"
    assert "access_token" not in str(settled)
    assert "password" not in str(settled)


def test_one_agent_cannot_contract_with_itself():
    with pytest.raises(ContractError, match="two agents"):
        offer(caller=CALLER, callee=CALLER, skill_id="chief_of_staff")
