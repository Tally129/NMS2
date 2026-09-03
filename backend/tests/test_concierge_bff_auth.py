import os

import pytest

from marketing_os.concierge.public_boundary import (
    CONCIERGE_BFF_KEY_ENV,
    PublicBoundaryError,
    require_concierge_bff_key,
)


GOOD_KEY = "A" * 64


def test_missing_configuration_fails_closed(monkeypatch):
    monkeypatch.delenv(
        CONCIERGE_BFF_KEY_ENV,
        raising=False,
    )

    with pytest.raises(PublicBoundaryError) as exc:
        require_concierge_bff_key(GOOD_KEY)

    assert exc.value.status_code == 404
    assert exc.value.code == "concierge_not_available"


@pytest.mark.parametrize(
    "configured",
    [
        "",
        "short",
        "A" * 31,
    ],
)
def test_weak_configuration_fails_closed(
    monkeypatch,
    configured,
):
    monkeypatch.setenv(
        CONCIERGE_BFF_KEY_ENV,
        configured,
    )

    with pytest.raises(PublicBoundaryError):
        require_concierge_bff_key(GOOD_KEY)


@pytest.mark.parametrize(
    "supplied",
    [
        None,
        "",
        "wrong",
        "B" * 64,
    ],
)
def test_missing_or_wrong_key_rejected(
    monkeypatch,
    supplied,
):
    monkeypatch.setenv(
        CONCIERGE_BFF_KEY_ENV,
        GOOD_KEY,
    )

    with pytest.raises(PublicBoundaryError) as exc:
        require_concierge_bff_key(supplied)

    assert exc.value.status_code == 404
    assert exc.value.code == "concierge_not_available"


def test_exact_key_accepted(monkeypatch):
    monkeypatch.setenv(
        CONCIERGE_BFF_KEY_ENV,
        GOOD_KEY,
    )

    assert require_concierge_bff_key(
        GOOD_KEY
    ) is None


def test_comparison_uses_hmac_compare_digest():
    import inspect
    import marketing_os.concierge.public_boundary as boundary

    source = inspect.getsource(
        boundary.require_concierge_bff_key
    )

    assert "hmac.compare_digest" in source
