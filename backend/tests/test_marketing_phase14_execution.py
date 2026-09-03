import asyncio

import pytest

from marketing_os.services.execution_policy import (
    build_idempotency_key,
    canonical_provider,
    evaluate_execution_policy,
    next_request_status,
)
from marketing_os.services.execution_queue import (
    decide_request,
    perform_dry_run,
    prepare_execution_request,
    submit_for_approval,
)
from marketing_os.services.provider_adapters import (
    AdapterError,
    get_provider_adapter,
)


def test_provider_aliases_are_canonical():
    assert canonical_provider("google") == "google_ads"
    assert canonical_provider("facebook") == "meta_ads"
    assert canonical_provider("bing") == "microsoft_ads"


def test_idempotency_key_is_deterministic():
    first = build_idempotency_key(
        provider="google",
        action_type="campaign.pause",
        target_type="campaign",
        target_id="123",
        payload={
            "reason": "performance",
            "value": 1,
        },
    )

    second = build_idempotency_key(
        provider="google_ads",
        action_type="campaign.pause",
        target_type="campaign",
        target_id="123",
        payload={
            "value": 1,
            "reason": "performance",
        },
    )

    assert first == second


def test_request_starts_draft_and_requires_human_approval():
    prepared = prepare_execution_request(
        provider="google_ads",
        action_type="campaign.pause",
        target_type="campaign",
        target_id="123",
        payload={"reason": "review"},
    )

    assert prepared["valid"] is True

    request = prepared["request"]

    assert request["status"] == "draft"
    assert request["dry_run"] is True
    assert request["human_approval_required"] is True


def test_state_machine_requires_valid_approval_flow():
    request = prepare_execution_request(
        provider="meta_ads",
        action_type="campaign.pause",
        target_type="campaign",
        target_id="abc",
        payload={},
    )["request"]

    request = submit_for_approval(request)

    assert request["status"] == "pending_approval"

    request = decide_request(
        request,
        decision="approve",
    )

    assert request["status"] == "approved"


def test_invalid_state_transition_is_rejected():
    with pytest.raises(ValueError):
        next_request_status(
            "draft",
            "approve",
        )


def test_disabled_provider_blocks_dry_run():
    policy = evaluate_execution_policy(
        provider="google_ads",
        action_type="campaign.pause",
        request_status="approved",
        dry_run=True,
        provider_enabled=False,
        provider_dry_run_only=True,
        provider_human_approval_required=True,
        approved=True,
        provider_allowed_actions=[
            "campaign.pause",
        ],
    )

    assert policy["allowed"] is False
    assert "provider_execution_disabled" in policy["reasons"]


def test_action_must_be_explicitly_allowed():
    policy = evaluate_execution_policy(
        provider="google_ads",
        action_type="campaign.pause",
        request_status="approved",
        dry_run=True,
        provider_enabled=True,
        provider_dry_run_only=True,
        provider_human_approval_required=True,
        approved=True,
        provider_allowed_actions=[],
    )

    assert policy["allowed"] is False
    assert (
        "action_not_allowed_by_provider_policy"
        in policy["reasons"]
    )


def test_approved_allowed_dry_run_performs_no_external_write():
    request = prepare_execution_request(
        provider="microsoft_ads",
        action_type="campaign.pause",
        target_type="campaign",
        target_id="xyz",
        payload={"reason": "test"},
    )["request"]

    request = submit_for_approval(request)
    request = decide_request(
        request,
        decision="approve",
    )

    outcome = asyncio.run(
        perform_dry_run(
            request,
            provider_enabled=True,
            provider_dry_run_only=True,
            provider_human_approval_required=True,
            provider_allowed_actions=[
                "campaign.pause",
            ],
        )
    )

    assert outcome["allowed"] is True
    assert outcome["result"]["dry_run"] is True
    assert (
        outcome["result"]["external_write_performed"]
        is False
    )
    assert (
        outcome["result"]["live_execution_enabled"]
        is False
    )


def test_live_request_is_always_blocked():
    policy = evaluate_execution_policy(
        provider="google_ads",
        action_type="campaign.pause",
        request_status="approved",
        dry_run=False,
        provider_enabled=True,
        provider_dry_run_only=False,
        provider_human_approval_required=True,
        approved=True,
        provider_allowed_actions=[
            "campaign.pause",
        ],
    )

    assert policy["allowed"] is False
    assert "live_execution_not_enabled" in policy["reasons"]
    assert policy["live_execution_enabled"] is False


def test_adapter_execute_is_hard_disabled():
    adapter = get_provider_adapter("google_ads")

    async def call():
        await adapter.execute(
            action_type="campaign.pause",
            target_type="campaign",
            target_id="123",
            payload={},
        )

    with pytest.raises(
        AdapterError,
        match="live_execution_not_enabled",
    ):
        asyncio.run(call())
