"""
Email + web-push delivery.

SMS was removed as a product surface in 2026-08. SendGrid is the only
transactional-email backend; secure in-app messaging + web push cover the
notification cases that were previously duplicated over SMS.

Behavior:
- `SENDGRID_API_KEY` + `SENDGRID_FROM_EMAIL` set  → send real email via SendGrid
- Missing either                                   → write `_stubbed: True` doc to
                                                     `integration_log` and return
                                                     status `"sent_stub"`

Every call also writes to `integration_log` so admins can audit outbound messages.
"""
from __future__ import annotations

import re
from html import unescape

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("nms.notify")


def email_status() -> str:
    """Return "live" or "sent_stub" — for /api/health + admin dashboards."""
    if os.environ.get("SENDGRID_API_KEY") and os.environ.get("SENDGRID_FROM_EMAIL"):
        return "live"
    return "sent_stub"


# --------------------------------------------------------------------------- #
# Email                                                                        #
# --------------------------------------------------------------------------- #

def _email_plain_text(html: str) -> str:
    """Create a readable plain-text alternative from transactional HTML."""

    value = html or ""

    value = re.sub(
        r"(?i)<\s*br\s*/?\s*>",
        "\n",
        value,
    )

    value = re.sub(
        r"(?i)</\s*(p|div|h[1-6]|li|tr)\s*>",
        "\n",
        value,
    )

    value = re.sub(
        r"(?is)<(style|script)\b[^>]*>.*?</\1>",
        "",
        value,
    )

    value = re.sub(
        r"(?s)<[^>]+>",
        "",
        value,
    )

    value = unescape(value)
    value = value.replace("\xa0", " ")

    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n[ \t]+", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)

    return value.strip()


async def send_email(
    db,
    to: str,
    subject: str,
    html: str,
    *,
    plain_text: Optional[str] = None,
    action: str = "email.generic",
    payload_metadata: Optional[dict] = None,
    redact_recipient: bool = False,
) -> str:
    """Send transactional email. Returns 'sent' | 'sent_stub' | 'failed'.

    `redact_recipient=True` writes only a SHA-256 hash prefix + subject to the audit trail
    (used for password-reset dispatch so the email address does not appear in integration_log).
    The HTML body is never logged regardless.
    """
    import hashlib
    now = datetime.now(timezone.utc)

    audit_to = to
    if redact_recipient:
        audit_to = "sha256:" + hashlib.sha256(to.lower().encode()).hexdigest()[:16]

    log_doc = {
        "service": "sendgrid",
        "action": action,
        "payload": {"to": audit_to, "subject": subject, **(payload_metadata or {})},
        "ts": now,
    }
    if email_status() != "live":
        log_doc["_stubbed"] = True
        await db.integration_log.insert_one(log_doc)
        return "sent_stub"

    api_key = os.environ["SENDGRID_API_KEY"]
    from_email = os.environ["SENDGRID_FROM_EMAIL"]
    reply_to = os.environ.get("SENDGRID_REPLY_TO") or None

    def _blocking_send() -> int:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import (
            Mail,
            ReplyTo,
            TrackingSettings,
            ClickTracking,
            OpenTracking,
        )

        # Always provide a legitimate text/plain MIME alternative.
        # Templates may supply their own plain-text body; otherwise
        # derive one from the HTML content.
        effective_plain_text = (
            plain_text.strip()
            if plain_text and plain_text.strip()
            else _email_plain_text(html)
        )

        mail_kwargs = {
            "from_email": from_email,
            "to_emails": to,
            "subject": subject,
            "plain_text_content": effective_plain_text,
            "html_content": html,
        }

        msg = Mail(**mail_kwargs)

        if reply_to:
            msg.reply_to = ReplyTo(reply_to)

        # Transactional operational notifications do not need
        # invisible open pixels or rewritten click-tracking URLs.
        tracking = TrackingSettings()
        tracking.open_tracking = OpenTracking(enable=False)
        tracking.click_tracking = ClickTracking(
            enable=False,
            enable_text=False,
        )
        msg.tracking_settings = tracking

        sg = SendGridAPIClient(api_key)
        r = sg.send(msg)
        return r.status_code

    try:
        code = await asyncio.to_thread(_blocking_send)
        log_doc.update({"status_code": code, "_stubbed": False})
        await db.integration_log.insert_one(log_doc)
        return "sent" if 200 <= code < 300 else "failed"
    except Exception as e:
        # `str(e)` from the SendGrid SDK includes only the HTTP status
        # and a redacted body — the API key is never in the exception.
        # Even so, we strip anything that looks like a bearer token.
        safe_err = _redact_secrets(str(e))
        log_doc.update({"error": safe_err, "_stubbed": False, "failed": True})
        await db.integration_log.insert_one(log_doc)
        logger.warning("SendGrid send failed: %s", safe_err)
        return "failed"


# --------------------------------------------------------------------------- #
# High-level typed helpers — every call site uses these instead of send_email  #
# so the templates + redaction rules apply consistently.                       #
# --------------------------------------------------------------------------- #
async def send_account_setup_email(db, to: str, *, first_name: Optional[str],
                                     setup_url: str, expires_in_hours: int) -> str:
    from email_templates import account_setup
    subject, html, text = account_setup(
        first_name=first_name, setup_url=setup_url,
        expires_in_hours=expires_in_hours,
    )
    return await send_email(db, to, subject, html, plain_text=text,
                             action="auth.account_setup", redact_recipient=True)


async def send_password_reset_email(db, to: str, *, first_name: Optional[str],
                                      reset_url: str, expires_in_minutes: int) -> str:
    from email_templates import password_reset
    subject, html, text = password_reset(
        first_name=first_name, reset_url=reset_url,
        expires_in_minutes=expires_in_minutes,
    )
    return await send_email(db, to, subject, html, plain_text=text,
                             action="auth.password_reset_dispatch",
                             redact_recipient=True)


async def send_password_changed_email(db, to: str, *,
                                        first_name: Optional[str]) -> str:
    from email_templates import password_changed
    subject, html, text = password_changed(first_name=first_name)
    return await send_email(db, to, subject, html, plain_text=text,
                             action="auth.password_changed",
                             redact_recipient=True)


async def send_mfa_enabled_email(db, to: str, *,
                                   first_name: Optional[str]) -> str:
    from email_templates import mfa_enabled
    subject, html, text = mfa_enabled(first_name=first_name)
    return await send_email(db, to, subject, html, plain_text=text,
                             action="auth.mfa_enabled",
                             redact_recipient=True)


async def send_recovery_code_used_email(db, to: str, *,
                                          first_name: Optional[str]) -> str:
    from email_templates import recovery_code_used
    subject, html, text = recovery_code_used(first_name=first_name)
    return await send_email(db, to, subject, html, plain_text=text,
                             action="auth.recovery_code_used",
                             redact_recipient=True)


async def send_security_alert_email(db, to: str, *, first_name: Optional[str],
                                      event_label: str) -> str:
    from email_templates import security_alert
    subject, html, text = security_alert(first_name=first_name,
                                          event_label=event_label)
    return await send_email(db, to, subject, html, plain_text=text,
                             action=f"security.{event_label[:32]}",
                             redact_recipient=True)


async def send_generic_portal_notification(db, to: str, *,
                                             first_name: Optional[str],
                                             headline: str = "You have a new notification"
                                             ) -> str:
    from email_templates import portal_notification
    subject, html, text = portal_notification(first_name=first_name,
                                                 headline=headline)
    return await send_email(db, to, subject, html, plain_text=text,
                             action="notify.portal",
                             redact_recipient=True)


async def send_campaign_email(db, to: str, *, subject: str,
                                safe_html: str, plain_text: Optional[str],
                                campaign_id: str) -> str:
    from email_templates import wrap_campaign
    subj, html, text = wrap_campaign(subject=subject, safe_html=safe_html,
                                       plain_text=plain_text)
    return await send_email(
        db, to, subj, html, plain_text=text,
        action="campaign.email",
        payload_metadata={"campaign_id": campaign_id},
        redact_recipient=True,
    )


# --------------------------------------------------------------------------- #
# Secret + PII redaction for log lines.                                        #
# --------------------------------------------------------------------------- #
import re as _re

_BEARER_RE = _re.compile(r"(SG\.[A-Za-z0-9._\-]+|Bearer\s+[A-Za-z0-9._\-]+)")
_EMAIL_RE = _re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


def _redact_secrets(text: str) -> str:
    """Redact SendGrid keys, bearer tokens, and full email addresses from
    strings before writing to logs or audit records."""
    if not text:
        return text
    text = _BEARER_RE.sub("<redacted-token>", text)
    text = _EMAIL_RE.sub("<redacted-email>", text)
    return text



# --------------------------------------------------------------------------- #
# Web-push (VAPID) — relocated from server.py so routers can call it without   #
# a circular import.                                                           #
# --------------------------------------------------------------------------- #
import json as _push_json


def _send_push_to_user(sub_doc, payload):
    try:
        from pywebpush import webpush
        webpush(
            subscription_info={
                "endpoint": sub_doc["endpoint"],
                "keys": sub_doc.get("keys", {}),
            },
            data=_push_json.dumps(payload),
            vapid_private_key=os.environ.get("VAPID_PRIVATE_KEY", ""),
            vapid_claims={"sub": os.environ.get("VAPID_CONTACT", "mailto:admin@natmedsol.local")},
            ttl=60 * 60 * 24,
        )
        return True
    except Exception as e:
        logger.info("push send failed for %s: %s", sub_doc.get("endpoint", "?")[:40], e)
        return False


async def push_to_user(user_id, title, body, url="/portal", tag=None):
    """Best-effort push to all active subscriptions for a user."""
    if not os.environ.get("VAPID_PRIVATE_KEY"):
        return 0
    from postgres_db import AsyncSessionLocal
    from repositories import clinical_and_messaging as cm_repo
    async with AsyncSessionLocal() as pg:
        subs = await cm_repo.list_push_subscriptions(pg, user_id)
    sent = 0
    payload = {"title": title, "body": body, "url": url, "tag": tag or title}
    dead = []
    for s in subs:
        ok = _send_push_to_user(s, payload)
        if ok:
            sent += 1
        else:
            dead.append(s["endpoint"])
    if dead:
        async with AsyncSessionLocal() as pg:
            async with pg.begin():
                for ep in dead:
                    await cm_repo.delete_push_subscription(pg, ep)
    return sent
