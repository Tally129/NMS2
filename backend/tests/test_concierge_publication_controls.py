import pytest

from marketing_os.concierge import public_boundary as boundary


CHAT = boundary.PUBLIC_CHAT_ENV
APPOINTMENT = boundary.PUBLIC_APPOINTMENT_ENV


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "false",
        "False",
        "FALSE",
        "0",
        "1",
        "yes",
        "on",
        "TRUE",
        "true ",
        " true",
        "True",
    ],
)
def test_chat_fails_closed(monkeypatch, value):
    if value is None:
        monkeypatch.delenv(CHAT, raising=False)
    else:
        monkeypatch.setenv(CHAT, value)

    assert boundary.public_chat_enabled() is False


def test_chat_exact_true(monkeypatch):
    monkeypatch.setenv(CHAT, "true")

    assert boundary.public_chat_enabled() is True


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "false",
        "False",
        "FALSE",
        "0",
        "1",
        "yes",
        "on",
        "TRUE",
        "true ",
        " true",
        "True",
    ],
)
def test_appointment_fails_closed(
    monkeypatch,
    value,
):
    if value is None:
        monkeypatch.delenv(
            APPOINTMENT,
            raising=False,
        )
    else:
        monkeypatch.setenv(
            APPOINTMENT,
            value,
        )

    assert (
        boundary.public_appointment_enabled()
        is False
    )


def test_appointment_exact_true(monkeypatch):
    monkeypatch.setenv(
        APPOINTMENT,
        "true",
    )

    assert (
        boundary.public_appointment_enabled()
        is True
    )


def test_controls_are_independent(monkeypatch):
    monkeypatch.setenv(CHAT, "true")
    monkeypatch.setenv(APPOINTMENT, "false")

    assert boundary.public_chat_enabled() is True
    assert (
        boundary.public_appointment_enabled()
        is False
    )

    monkeypatch.setenv(CHAT, "false")
    monkeypatch.setenv(APPOINTMENT, "true")

    assert boundary.public_chat_enabled() is False
    assert (
        boundary.public_appointment_enabled()
        is True
    )
