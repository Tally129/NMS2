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
async def test_live_adapter_resolution_is_disabled_by_default():
    with pytest.raises(
        RuntimeError,
        match="live_provider_resolution_not_configured",
    ):
        await core._resolve_live_execution_adapter(
            provider="google_ads",
            request={
                "provider": "google_ads",
            },
        )
