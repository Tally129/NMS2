import os

from marketing_os.integrations.google_ads import (
    credential_readiness,
)


REQUIRED = (
    "GOOGLE_ADS_DEVELOPER_TOKEN",
    "GOOGLE_ADS_CLIENT_ID",
    "GOOGLE_ADS_CLIENT_SECRET",
    "GOOGLE_ADS_REFRESH_TOKEN",
)


def clear_google_env(monkeypatch):
    for name in REQUIRED:
        monkeypatch.delenv(
            name,
            raising=False,
        )

    monkeypatch.delenv(
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
        raising=False,
    )


def test_credential_readiness_reports_missing_without_values(
    monkeypatch,
):
    clear_google_env(monkeypatch)

    result = credential_readiness()

    assert result["required_configured"] is False

    assert set(
        result["missing_required"]
    ) == set(REQUIRED)

    assert (
        result["login_customer_id_configured"]
        is False
    )

    text = repr(result)

    assert "developer-secret-value" not in text
    assert "client-secret-value" not in text


def test_credential_readiness_reports_configured(
    monkeypatch,
):
    clear_google_env(monkeypatch)

    monkeypatch.setenv(
        "GOOGLE_ADS_DEVELOPER_TOKEN",
        "developer-secret-value",
    )

    monkeypatch.setenv(
        "GOOGLE_ADS_CLIENT_ID",
        "client-id-value",
    )

    monkeypatch.setenv(
        "GOOGLE_ADS_CLIENT_SECRET",
        "client-secret-value",
    )

    monkeypatch.setenv(
        "GOOGLE_ADS_REFRESH_TOKEN",
        "refresh-secret-value",
    )

    monkeypatch.setenv(
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
        "1234567890",
    )

    result = credential_readiness()

    assert result == {
        "required_configured": True,
        "missing_required": [],
        "login_customer_id_configured": True,
    }

    rendered = repr(result)

    assert "developer-secret-value" not in rendered
    assert "client-secret-value" not in rendered
    assert "refresh-secret-value" not in rendered


def test_readiness_helper_performs_no_google_import_or_call(
    monkeypatch,
):
    clear_google_env(monkeypatch)

    before_modules = set(
        name
        for name in os.sys.modules
        if name.startswith(
            "google.ads.googleads"
        )
    )

    credential_readiness()

    after_modules = set(
        name
        for name in os.sys.modules
        if name.startswith(
            "google.ads.googleads"
        )
    )

    assert after_modules == before_modules
