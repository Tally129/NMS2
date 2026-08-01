"""Admin/dev-only real-send validation for SendGrid wiring.

Sends ONE generic account-setup-style email to a recipient supplied via
the SENDGRID_TEST_RECIPIENT environment variable (or --to). The message
never contains PHI or any real credential.

Usage:
    SENDGRID_TEST_RECIPIENT="ops@example.com" \
      python -m scripts.send_test_email

or

    python -m scripts.send_test_email --to "ops@example.com"
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from notifiers import _redact_secrets, email_status, send_account_setup_email


def _resolve_recipient(cli_to: str | None) -> str:
    return (cli_to or os.environ.get("SENDGRID_TEST_RECIPIENT") or "").strip()


async def _run(recipient: str) -> int:
    if not recipient:
        print("ERROR: recipient required via --to or SENDGRID_TEST_RECIPIENT")
        return 2
    status_hint = email_status()
    if status_hint != "live":
        print("ERROR: SendGrid is not configured (SENDGRID_API_KEY + "
              "SENDGRID_FROM_EMAIL must be set). Refusing to fake-send.")
        return 3

    # Route through the app db handle so audit rows land in emr_integration_log.
    from deps import db
    origin = (os.environ.get("FRONTEND_ORIGIN") or "").rstrip("/") or "https://example.invalid"
    setup_url = f"{origin}/reset-password?token=SAMPLE_TOKEN_NOT_A_REAL_ONE"

    status = await send_account_setup_email(
        db, recipient,
        first_name=None,
        setup_url=setup_url,
        expires_in_hours=24,
    )
    # Never print the API key or the raw setup link body.
    print(f"provider_status={status}")
    print(f"recipient=<redacted>")
    print(f"summary={_redact_secrets(f'sent generic account-setup email to {recipient} (status={status})')}")
    return 0 if status in ("sent", "sent_stub") else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--to", default=None,
                     help="Recipient email (falls back to SENDGRID_TEST_RECIPIENT).")
    args = ap.parse_args()
    rc = asyncio.run(_run(_resolve_recipient(args.to)))
    sys.exit(rc)


if __name__ == "__main__":
    main()
