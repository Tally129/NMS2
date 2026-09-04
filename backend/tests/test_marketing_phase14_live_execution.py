from datetime import datetime, timezone

import pytest

from marketing_os.services.execution_queue import (
    perform_live_execution,
)


def approved_request(
    *,
    dry_run=False,
    action_type="budget.update",
):
    return {
        "id": "request-1",
        "provider": "google_ads",
        "action_type": action_type,
        "target_type": "campaign",
        "target_id": "123",
        "request_payload": {
            "daily_budget": "35.00",
        },
        "dry_run": dry_run,
        "status": "approved",
        "approved_by": "admin-1",
        "approved_at": datetime.now(
            timezone.utc
        ),
    }


class FakeLiveAdapter:
    def __init__(
        self,
        *,
        external_write=True,
        verified=True,
    ):
        self.calls = []
        self.external_write = external_write
        self.verified = verified

    async def execute_action(
        self,
        *,
        action_type,
        target_type,
        target_id,
        payload,
    ):
        self.calls.append({
            "action_type": action_type,
            "target_type": target_type,
            "target_id": target_id,
            "payload": dict(payload),
        })

        return {
            "provider": "google_ads",
            "action_type": action_type,
            "external_write_performed":
                self.external_write,
            "verified": self.verified,
            "verification": {
                "campaign_id": target_id,
            },
        }


@pytest.mark.asyncio
async def test_live_execution_calls_adapter_after_approval():
    adapter = FakeLiveAdapter()

    result = await perform_live_execution(
        approved_request(),
        adapter=adapter,
        provider_enabled=True,
        provider_dry_run_only=False,
        provider_human_approval_required=True,
        provider_allowed_actions=[
            "budget.update",
        ],
    )

    assert result["allowed"] is True
    assert len(adapter.calls) == 1

    assert (
        adapter.calls[0]["action_type"]
        == "budget.update"
    )

    assert (
        result["result"][
            "external_write_performed"
        ]
        is True
    )

    assert result["result"]["verified"] is True

    # The live route consumes both confirmation flags from
    # the top-level outcome, not only from the nested provider
    # result. This is the contract that prevents a verified
    # provider write from being misclassified as uncertain.
    assert result["external_write_performed"] is True
    assert result["verified"] is True


@pytest.mark.asyncio
async def test_live_execution_blocks_dry_run_request():
    adapter = FakeLiveAdapter()

    result = await perform_live_execution(
        approved_request(dry_run=True),
        adapter=adapter,
        provider_enabled=True,
        provider_dry_run_only=False,
        provider_human_approval_required=True,
        provider_allowed_actions=[
            "budget.update",
        ],
    )

    assert result["allowed"] is False

    assert (
        "request_marked_dry_run"
        in result["policy"]["reasons"]
    )

    assert adapter.calls == []


@pytest.mark.asyncio
async def test_live_execution_blocks_disabled_provider():
    adapter = FakeLiveAdapter()

    result = await perform_live_execution(
        approved_request(),
        adapter=adapter,
        provider_enabled=False,
        provider_dry_run_only=False,
        provider_human_approval_required=True,
        provider_allowed_actions=[
            "budget.update",
        ],
    )

    assert result["allowed"] is False

    assert (
        "provider_disabled"
        in result["policy"]["reasons"]
    )

    assert adapter.calls == []


@pytest.mark.asyncio
async def test_live_execution_blocks_dry_run_only_provider():
    adapter = FakeLiveAdapter()

    result = await perform_live_execution(
        approved_request(),
        adapter=adapter,
        provider_enabled=True,
        provider_dry_run_only=True,
        provider_human_approval_required=True,
        provider_allowed_actions=[
            "budget.update",
        ],
    )

    assert result["allowed"] is False

    assert (
        "provider_dry_run_only"
        in result["policy"]["reasons"]
    )

    assert adapter.calls == []


@pytest.mark.asyncio
async def test_live_execution_blocks_unapproved_request():
    adapter = FakeLiveAdapter()

    request = approved_request()

    request["status"] = "pending_approval"
    request["approved_by"] = None
    request["approved_at"] = None

    result = await perform_live_execution(
        request,
        adapter=adapter,
        provider_enabled=True,
        provider_dry_run_only=False,
        provider_human_approval_required=True,
        provider_allowed_actions=[
            "budget.update",
        ],
    )

    assert result["allowed"] is False

    assert "request_not_approved" in (
        result["policy"]["reasons"]
    )

    assert adapter.calls == []


@pytest.mark.asyncio
async def test_live_execution_blocks_unallowed_action():
    adapter = FakeLiveAdapter()

    result = await perform_live_execution(
        approved_request(),
        adapter=adapter,
        provider_enabled=True,
        provider_dry_run_only=False,
        provider_human_approval_required=True,
        provider_allowed_actions=[
            "campaign.pause",
        ],
    )

    assert result["allowed"] is False

    assert (
        "action_not_allowed"
        in result["policy"]["reasons"]
    )

    assert adapter.calls == []


@pytest.mark.asyncio
async def test_live_execution_requires_write_confirmation():
    adapter = FakeLiveAdapter(
        external_write=False,
    )

    with pytest.raises(
        RuntimeError,
        match="provider_did_not_confirm_external_write",
    ):
        await perform_live_execution(
            approved_request(),
            adapter=adapter,
            provider_enabled=True,
            provider_dry_run_only=False,
            provider_human_approval_required=True,
            provider_allowed_actions=[
                "budget.update",
            ],
        )


@pytest.mark.asyncio
async def test_live_execution_requires_verification():
    adapter = FakeLiveAdapter(
        verified=False,
    )

    with pytest.raises(
        RuntimeError,
        match="provider_write_not_verified",
    ):
        await perform_live_execution(
            approved_request(),
            adapter=adapter,
            provider_enabled=True,
            provider_dry_run_only=False,
            provider_human_approval_required=True,
            provider_allowed_actions=[
                "budget.update",
            ],
        )
