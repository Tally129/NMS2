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


def test_provider_policy_cannot_bypass_human_approval():
    policy = evaluate_execution_policy(
        provider="google_ads",
        action_type="campaign.pause",
        request_status="pending_approval",
        dry_run=True,
        provider_enabled=True,
        provider_dry_run_only=True,
        provider_human_approval_required=False,
        approved=False,
        provider_allowed_actions=[
            "campaign.pause",
        ],
    )

    assert policy["allowed"] is False
    assert "human_approval_required" in policy["reasons"]
    assert policy["human_approval_required"] is True


def test_execution_payload_rejects_direct_phi_field():
    prepared = prepare_execution_request(
        provider="google_ads",
        action_type="campaign.pause",
        target_type="campaign",
        target_id="123",
        payload={
            "reason": "review",
            "email": "person@example.com",
        },
    )

    assert prepared["valid"] is False
    assert (
        "prohibited_marketing_fields"
        in prepared["errors"]
    )
    assert (
        "email"
        in prepared["payload_policy"]["prohibited_fields"]
    )


def test_execution_payload_rejects_nested_phi_field():
    prepared = prepare_execution_request(
        provider="meta_ads",
        action_type="campaign.create",
        target_type="campaign",
        target_id=None,
        payload={
            "name": "September campaign",
            "reason": "test",
            "metadata": {
                "diagnosis": "prohibited-value",
            },
        },
    )

    assert prepared["valid"] is False
    assert (
        "prohibited_marketing_fields"
        in prepared["errors"]
    )
    assert (
        "metadata.diagnosis"
        in prepared["payload_policy"]["prohibited_fields"]
    )


def test_execution_payload_rejects_credentials():
    prepared = prepare_execution_request(
        provider="microsoft_ads",
        action_type="campaign.pause",
        target_type="campaign",
        target_id="xyz",
        payload={
            "reason": "test",
            "access_token": "never-store-this",
        },
    )

    assert prepared["valid"] is False
    assert (
        "credential_fields_prohibited"
        in prepared["errors"]
    )
    assert (
        "access_token"
        in prepared["payload_policy"]["credential_fields"]
    )


def test_execution_payload_rejects_unexpected_field():
    prepared = prepare_execution_request(
        provider="google_ads",
        action_type="campaign.pause",
        target_type="campaign",
        target_id="123",
        payload={
            "reason": "review",
            "arbitrary_blob": {
                "anything": "value",
            },
        },
    )

    assert prepared["valid"] is False
    assert (
        "unexpected_payload_fields"
        in prepared["errors"]
    )
    assert (
        "arbitrary_blob"
        in prepared["payload_policy"]["unexpected_fields"]
    )


def test_pause_payload_accepts_marketing_safe_reason():
    prepared = prepare_execution_request(
        provider="google_ads",
        action_type="campaign.pause",
        target_type="campaign",
        target_id="123",
        payload={
            "reason": "performance review",
        },
    )

    assert prepared["valid"] is True


def test_budget_update_accepts_bounded_safe_fields():
    prepared = prepare_execution_request(
        provider="meta_ads",
        action_type="budget.update",
        target_type="campaign",
        target_id="abc",
        payload={
            "daily_budget": 125,
            "currency": "USD",
            "reason": "approved planning scenario",
        },
    )

    assert prepared["valid"] is True


def test_pause_requires_campaign_target():
    prepared = prepare_execution_request(
        provider="google_ads",
        action_type="campaign.pause",
        target_type="ad",
        target_id="123",
        payload={"reason": "review"},
    )

    assert prepared["valid"] is False
    assert (
        "invalid_target_type_for_action"
        in prepared["errors"]
    )


def test_pause_requires_target_id():
    prepared = prepare_execution_request(
        provider="google_ads",
        action_type="campaign.pause",
        target_type="campaign",
        target_id=None,
        payload={"reason": "review"},
    )

    assert prepared["valid"] is False
    assert (
        "target_id_required_for_action"
        in prepared["errors"]
    )


def test_campaign_create_allows_missing_target_id():
    prepared = prepare_execution_request(
        provider="google_ads",
        action_type="campaign.create",
        target_type="campaign",
        target_id=None,
        payload={
            "name": "September Campaign",
            "currency": "USD",
            "daily_budget": 50,
        },
    )

    assert prepared["valid"] is True


def test_budget_rejects_negative_value():
    prepared = prepare_execution_request(
        provider="meta_ads",
        action_type="budget.update",
        target_type="campaign",
        target_id="abc",
        payload={
            "daily_budget": -1,
            "currency": "USD",
        },
    )

    assert prepared["valid"] is False
    assert "invalid_payload_values" in prepared["errors"]
    assert (
        "daily_budget_must_be_nonnegative"
        in prepared["payload_policy"]["value_errors"]
    )


def test_budget_rejects_nonfinite_value():
    prepared = prepare_execution_request(
        provider="meta_ads",
        action_type="budget.update",
        target_type="campaign",
        target_id="abc",
        payload={
            "daily_budget": float("inf"),
            "currency": "USD",
        },
    )

    assert prepared["valid"] is False
    assert (
        "daily_budget_must_be_finite"
        in prepared["payload_policy"]["value_errors"]
    )


def test_budget_rejects_boolean_as_number():
    prepared = prepare_execution_request(
        provider="meta_ads",
        action_type="budget.update",
        target_type="campaign",
        target_id="abc",
        payload={
            "daily_budget": True,
            "currency": "USD",
        },
    )

    assert prepared["valid"] is False
    assert (
        "daily_budget_must_be_number"
        in prepared["payload_policy"]["value_errors"]
    )


def test_currency_requires_three_letters():
    prepared = prepare_execution_request(
        provider="meta_ads",
        action_type="budget.update",
        target_type="campaign",
        target_id="abc",
        payload={
            "daily_budget": 25,
            "currency": "US",
        },
    )

    assert prepared["valid"] is False
    assert (
        "currency_must_be_three_letters"
        in prepared["payload_policy"]["value_errors"]
    )


def test_ad_destination_requires_http_url():
    prepared = prepare_execution_request(
        provider="google_ads",
        action_type="ad.create",
        target_type="ad",
        target_id=None,
        payload={
            "name": "Test Ad",
            "headline": "Wellness",
            "destination_url": "javascript:alert(1)",
        },
    )

    assert prepared["valid"] is False
    assert (
        "destination_url_must_be_http_url"
        in prepared["payload_policy"]["value_errors"]
    )


def test_campaign_dates_must_be_ordered():
    prepared = prepare_execution_request(
        provider="google_ads",
        action_type="campaign.create",
        target_type="campaign",
        target_id=None,
        payload={
            "name": "Test",
            "start_date": "2026-09-30",
            "end_date": "2026-09-01",
        },
    )

    assert prepared["valid"] is False
    assert (
        "end_date_before_start_date"
        in prepared["payload_policy"]["value_errors"]
    )


def test_nested_allowed_field_value_is_rejected():
    prepared = prepare_execution_request(
        provider="google_ads",
        action_type="campaign.create",
        target_type="campaign",
        target_id=None,
        payload={
            "name": {
                "unexpected": "nested",
            },
        },
    )

    assert prepared["valid"] is False
    assert (
        "name_must_be_scalar"
        in prepared["payload_policy"]["value_errors"]
    )


def test_execution_payload_size_is_bounded():
    prepared = prepare_execution_request(
        provider="google_ads",
        action_type="ad.create",
        target_type="ad",
        target_id=None,
        payload={
            "description": "x" * 40000,
        },
    )

    assert prepared["valid"] is False
    assert (
        "payload_too_large"
        in prepared["payload_policy"]["value_errors"]
    )


def test_ad_update_requires_ad_target_id():
    prepared = prepare_execution_request(
        provider="google_ads",
        action_type="ad.update",
        target_type="ad",
        target_id=None,
        payload={
            "headline": "Updated headline",
        },
    )

    assert prepared["valid"] is False
    assert (
        "target_id_required_for_action"
        in prepared["errors"]
    )


def test_safe_ad_payload_remains_valid():
    prepared = prepare_execution_request(
        provider="google_ads",
        action_type="ad.create",
        target_type="ad",
        target_id=None,
        payload={
            "name": "Wellness Ad",
            "headline": "Explore Wellness Care",
            "description": "Learn more about our wellness services.",
            "destination_url": "https://natmedsol.com/",
            "status": "paused",
        },
    )

    assert prepared["valid"] is True
