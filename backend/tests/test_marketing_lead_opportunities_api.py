from __future__ import annotations

import inspect

from marketing_os.routers import core


def route_source() -> str:
    return inspect.getsource(
        core.list_marketing_lead_opportunities
    )


def test_lead_opportunity_handler_exists():
    source = route_source()

    assert (
        "marketing_conversion_events"
        in source
    )

    assert (
        "derive_lead_opportunities"
        in source
    )


def test_lead_opportunity_handler_is_read_only():
    source = route_source().lower()

    forbidden = (
        "insert into",
        "update ",
        "delete from",
        ".commit(",
        ".add(",
        ".flush(",
    )

    for token in forbidden:
        assert token not in source


def test_lead_opportunity_handler_filters_missing_subjects():
    source = route_source()

    assert (
        "marketing_subject_id IS NOT NULL"
        in source
    )

    assert (
        "BTRIM(marketing_subject_id)"
        in source
    )


def test_lead_opportunity_handler_uses_marketing_role_gate():
    source = route_source()

    assert (
        "require_roles(*MARKETING_ROLES)"
        in source
    )


def test_lead_opportunity_handler_does_not_select_contact_fields():
    source = route_source().lower()

    forbidden = (
        "email",
        "phone",
        "patient_name",
        "first_name",
        "last_name",
        "diagnosis",
        "medication",
        "clinical_note",
    )

    for field in forbidden:
        assert field not in source
