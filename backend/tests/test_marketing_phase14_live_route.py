import pytest

from marketing_os.routers import core


def test_live_execute_route_is_registered():
    paths = []

    for route in core.api.routes:
        path = getattr(route, "path", "")

        if path.endswith(
            "/marketing-os/execution/requests/"
            "{request_id}/execute"
        ):
            paths.append(path)

    assert len(paths) == 1


@pytest.mark.asyncio
async def test_live_adapter_resolution_blocks_missing_credentials(
    monkeypatch,
):
    from marketing_os.integrations import google_ads

    monkeypatch.setattr(
        google_ads,
        "credential_readiness",
        lambda: {
            "required_configured": False,
            "missing_required": [
                "GOOGLE_ADS_DEVELOPER_TOKEN",
            ],
            "login_customer_id_configured": False,
        },
    )

    with pytest.raises(
        RuntimeError,
        match="google_ads_credentials_missing",
    ):
        await core._resolve_live_execution_adapter(
            provider="google_ads",
            request={
                "provider": "google_ads",
            },
        )


@pytest.mark.asyncio
async def test_live_adapter_resolution_blocks_unsupported_provider():
    # Meta/Microsoft are governed live providers now, but fail closed
    # without server-side credentials.
    with pytest.raises(RuntimeError, match="meta_ads_credentials_missing"):
        await core._resolve_live_execution_adapter(
            provider="meta_ads",
            request={"provider": "meta_ads"},
        )
    with pytest.raises(
        RuntimeError,
        match="live_provider_not_supported",
    ):
        await core._resolve_live_execution_adapter(
            provider="tiktok_ads",
            request={"provider": "tiktok_ads"},
        )


def test_google_ads_live_account_requirements_documented():
    source = open(
        "marketing_os/routers/core.py",
        encoding="utf-8",
    ).read()

    assert '"connected", "active"' in source
    assert 'read_enabled") is not True' in source
    assert 'write_enabled") is not True' in source
    assert "google_ads_credentials_missing" in source
    assert "google_ads_account_not_registered" in source
    assert "google_ads_write_account_not_enabled" in source
