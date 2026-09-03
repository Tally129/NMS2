import json

import pytest

from marketing_os.concierge.public_boundary import (
    ALLOWED_CONCIERGE_ORIGINS,
    MAX_PUBLIC_CHAT_BODY_BYTES,
    PublicBoundaryError,
    normalize_origin,
    parse_public_chat_body,
    public_chat_enabled,
    require_allowed_origin,
)


def test_public_chat_is_disabled_by_default():
    assert public_chat_enabled() is False


@pytest.mark.parametrize(
    "origin",
    (
        "https://preview.natmedsol.org",
        "https://www.natmedsol.com",
        "https://natmedsol.com",
    ),
)
def test_exact_approved_origins_are_allowed(
    origin,
):
    assert (
        require_allowed_origin(origin)
        == origin
    )


@pytest.mark.parametrize(
    "origin",
    (
        None,
        "",
        "null",
        "http://preview.natmedsol.org",
        "https://evil.example",
        "https://preview.natmedsol.org.evil.example",
        "https://evil.example@preview.natmedsol.org",
        "https://preview.natmedsol.org:443",
        "https://preview.natmedsol.org:444",
        "https://preview.natmedsol.org/path",
        "https://preview.natmedsol.org?x=1",
        "https://preview.natmedsol.org#fragment",
    ),
)
def test_unapproved_origin_forms_fail_closed(
    origin,
):
    with pytest.raises(
        PublicBoundaryError
    ) as exc:
        require_allowed_origin(
            origin
        )

    assert exc.value.status_code == 403
    assert (
        exc.value.code
        == "concierge_origin_not_allowed"
    )


def test_origin_normalization_is_case_safe():
    assert (
        normalize_origin(
            "https://PREVIEW.NATMEDSOL.ORG"
        )
        == "https://preview.natmedsol.org"
    )


def test_origin_allowlist_is_exact():
    assert ALLOWED_CONCIERGE_ORIGINS == {
        "https://preview.natmedsol.org",
        "https://www.natmedsol.com",
        "https://natmedsol.com",
    }


def test_valid_public_chat_body_parses():
    payload = parse_public_chat_body(
        json.dumps(
            {
                "message":
                    "Do you offer telehealth?",
                "session_id":
                    "public-test-session",
                "page_url":
                    "https://preview.natmedsol.org/telehealth/",
            }
        ).encode()
    )

    assert (
        payload.message
        == "Do you offer telehealth?"
    )


def test_extra_fields_are_rejected():
    raw = json.dumps(
        {
            "message": "Hello",
            "unexpected": "value",
        }
    ).encode()

    with pytest.raises(
        PublicBoundaryError
    ) as exc:
        parse_public_chat_body(
            raw
        )

    assert exc.value.status_code == 422
    assert (
        exc.value.code
        == "concierge_invalid_request"
    )


@pytest.mark.parametrize(
    "raw,code",
    (
        (
            b"",
            "concierge_request_body_required",
        ),
        (
            b"{not-json",
            "concierge_invalid_json",
        ),
        (
            b'["not","object"]',
            "concierge_json_object_required",
        ),
    ),
)
def test_malformed_bodies_fail_closed(
    raw,
    code,
):
    with pytest.raises(
        PublicBoundaryError
    ) as exc:
        parse_public_chat_body(
            raw
        )

    assert exc.value.code == code


def test_body_limit_is_enforced_before_parsing():
    raw = (
        b"x"
        * (
            MAX_PUBLIC_CHAT_BODY_BYTES
            + 1
        )
    )

    with pytest.raises(
        PublicBoundaryError
    ) as exc:
        parse_public_chat_body(
            raw
        )

    assert exc.value.status_code == 413
    assert (
        exc.value.code
        == "concierge_request_too_large"
    )
