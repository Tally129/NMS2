import pytest

from marketing_os.services.execution_policy import (
    validate_live_request_creation_policy,
)


def _request(
    *,
    dry_run=False,
    action_type="campaign.pause",
):
    return {
        "provider": "google_ads",
        "action_type": action_type,
        "target_type": "campaign",
        "target_id": "123",
        "dry_run": dry_run,
        "request_payload": {},
    }


def _policy(
    *,
    enabled=True,
    dry_run_only=False,
    human_approval_required=True,
    allowed_actions=None,
):
    return {
        "provider": "google_ads",
        "enabled": enabled,
        "dry_run_only": dry_run_only,
        "human_approval_required":
            human_approval_required,
        "allowed_actions": (
            allowed_actions
            if allowed_actions is not None
            else [
                "campaign.create",
                "campaign.pause",
                "campaign.resume",
            ]
        ),
    }


def test_dry_run_creation_skips_live_policy_gate():
    result = validate_live_request_creation_policy(
        request=_request(
            dry_run=True,
        ),
        provider_policy=None,
    )

    assert result == {
        "live_request": False,
        "policy_validated": False,
    }


def test_live_pause_creation_allowed():
    result = validate_live_request_creation_policy(
        request=_request(
            action_type="campaign.pause",
        ),
        provider_policy=_policy(),
    )

    assert result["live_request"] is True
    assert result["policy_validated"] is True


def test_live_resume_creation_allowed():
    result = validate_live_request_creation_policy(
        request=_request(
            action_type="campaign.resume",
        ),
        provider_policy=_policy(),
    )

    assert result["live_request"] is True


@pytest.mark.parametrize(
    "policy,expected",
    [
        (
            None,
            "provider_policy_missing",
        ),
        (
            _policy(
                enabled=False,
            ),
            "provider_disabled",
        ),
        (
            _policy(
                dry_run_only=True,
            ),
            "provider_dry_run_only",
        ),
        (
            _policy(
                human_approval_required=False,
            ),
            "live_request_requires_human_approval",
        ),
        (
            _policy(
                allowed_actions=[
                    "campaign.create",
                ],
            ),
            "action_not_allowlisted",
        ),
    ],
)
def test_live_creation_fails_closed(
    policy,
    expected,
):
    with pytest.raises(
        ValueError,
        match=f"^{expected}$",
    ):
        validate_live_request_creation_policy(
            request=_request(),
            provider_policy=policy,
        )
