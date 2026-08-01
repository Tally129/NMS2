"""Privacy-safe email templates for the SendGrid production wiring.

Rules for every template rendered here:

* No PHI. No diagnoses, treatment details, lab values, note bodies,
  message bodies, appointment reasons, medications, or attachment titles.
* Only the recipient's first name (if already collected) is used for
  personalization.
* All CTAs point to the secure portal; sensitive content is not embedded.
* Subjects are neutral — they may appear on lock screens / previews.
* Every template emits BOTH HTML and plain-text bodies. Consumers that
  only take an HTML body will still work; SendGrid uses the plain-text
  as the fallback part.

Helpers in this module return `(subject, html, plain_text)` tuples.
"""
from __future__ import annotations

import html as _html
import os
from datetime import datetime, timezone
from typing import Optional

APP_NAME = "Natural Medical Solutions"


def _origin() -> str:
    return (os.environ.get("FRONTEND_ORIGIN") or "").rstrip("/")


def _support_email() -> str:
    return os.environ.get("SUPPORT_EMAIL") or ""


def _footer_html() -> str:
    support = _support_email()
    support_html = (
        f' Questions? Contact <a href="mailto:{_html.escape(support)}">'
        f'{_html.escape(support)}</a>.' if support else ""
    )
    return (
        '<hr style="border:none;border-top:1px solid #e6dfcf;margin:24px 0"/>'
        f'<p style="font-size:12px;color:#8a7a4c">'
        f'{_html.escape(APP_NAME)} — This is an automated message. Please do '
        f'not reply.{support_html}'
        '</p>'
    )


def _footer_text() -> str:
    support = _support_email()
    tail = f" Questions? Contact {support}." if support else ""
    return f"\n\n-- \n{APP_NAME} — Automated message.{tail}\n"


def _greeting(first_name: Optional[str]) -> tuple[str, str]:
    """Return (html-greeting, plain-greeting). Falls back to a neutral form."""
    safe = (first_name or "").strip().split()[0] if first_name else ""
    if safe:
        return (f"<p>Hi {_html.escape(safe)},</p>", f"Hi {safe},\n")
    return ("<p>Hi,</p>", "Hi,\n")


# --------------------------------------------------------------------------- #
# 1. Account setup (new workforce account created)                             #
# --------------------------------------------------------------------------- #
def account_setup(*, first_name: Optional[str], setup_url: str,
                   expires_in_hours: int) -> tuple[str, str, str]:
    subject = f"Set up your {APP_NAME} account"
    g_html, g_text = _greeting(first_name)
    body_html = (
        f'{g_html}'
        '<p>An administrator invited you to join the secure staff portal. '
        'Use the one-time setup link below to create your password and '
        'enroll multi-factor authentication:</p>'
        f'<p><a href="{_html.escape(setup_url)}" '
        'style="display:inline-block;padding:12px 20px;background:#8b7226;'
        'color:#fff;text-decoration:none;border-radius:6px;">'
        'Set up your account</a></p>'
        f'<p style="font-size:13px;color:#665">This link expires in '
        f'{int(expires_in_hours)} hours. If you did not expect this invite, '
        'you can safely ignore this email.</p>'
        f'{_footer_html()}'
    )
    body_text = (
        f"{g_text}\n"
        f"An administrator invited you to join the secure {APP_NAME} staff portal.\n"
        f"Set up your account within {int(expires_in_hours)} hours using this one-time link:\n\n"
        f"{setup_url}\n\n"
        "If you did not expect this invite, you can safely ignore this email."
        f"{_footer_text()}"
    )
    return subject, body_html, body_text


# --------------------------------------------------------------------------- #
# 2. Password reset request                                                    #
# --------------------------------------------------------------------------- #
def password_reset(*, first_name: Optional[str], reset_url: str,
                    expires_in_minutes: int) -> tuple[str, str, str]:
    subject = f"Reset your {APP_NAME} password"
    g_html, g_text = _greeting(first_name)
    body_html = (
        f'{g_html}'
        '<p>Someone (hopefully you) asked to reset the password on your account. '
        f'Use this one-time link within {int(expires_in_minutes)} minutes:</p>'
        f'<p><a href="{_html.escape(reset_url)}">{_html.escape(reset_url)}</a></p>'
        '<p style="font-size:13px;color:#665">If you did not request this, you '
        'can safely ignore this email — your password has not changed.</p>'
        f'{_footer_html()}'
    )
    body_text = (
        f"{g_text}\n"
        "Someone (hopefully you) asked to reset the password on your account.\n"
        f"Use this one-time link within {int(expires_in_minutes)} minutes:\n\n"
        f"{reset_url}\n\n"
        "If you did not request this, you can safely ignore this email — "
        "your password has not changed."
        f"{_footer_text()}"
    )
    return subject, body_html, body_text


# --------------------------------------------------------------------------- #
# 3. Password changed / MFA enabled / recovery-code used / generic security   #
# --------------------------------------------------------------------------- #
def _security_notice(*, subject: str, headline_html: str, headline_text: str,
                       when: Optional[datetime],
                       first_name: Optional[str]) -> tuple[str, str, str]:
    g_html, g_text = _greeting(first_name)
    when_str = (when or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
    origin = _origin()
    portal_link = (f'<p><a href="{_html.escape(origin)}/login">Open the secure '
                    'portal</a></p>') if origin else ""
    portal_text = f"\nOpen the secure portal: {origin}/login\n" if origin else ""
    body_html = (
        f'{g_html}'
        f'<p>{headline_html} at <strong>{when_str}</strong>.</p>'
        '<p>If this was you, no action is needed. If you did not do this, '
        'sign in immediately, change your password, and contact support.</p>'
        f'{portal_link}'
        f'{_footer_html()}'
    )
    body_text = (
        f"{g_text}\n{headline_text} at {when_str}.\n\n"
        "If this was you, no action is needed. If you did not do this, "
        "sign in immediately, change your password, and contact support."
        f"{portal_text}"
        f"{_footer_text()}"
    )
    return subject, body_html, body_text


def password_changed(*, first_name: Optional[str],
                      when: Optional[datetime] = None) -> tuple[str, str, str]:
    return _security_notice(
        subject="Your password was changed",
        headline_html="Your account password was changed",
        headline_text="Your account password was changed",
        when=when, first_name=first_name,
    )


def mfa_enabled(*, first_name: Optional[str],
                 when: Optional[datetime] = None) -> tuple[str, str, str]:
    return _security_notice(
        subject="Multi-factor authentication was enabled",
        headline_html="Multi-factor authentication was enabled on your account",
        headline_text="Multi-factor authentication was enabled on your account",
        when=when, first_name=first_name,
    )


def recovery_code_used(*, first_name: Optional[str],
                        when: Optional[datetime] = None) -> tuple[str, str, str]:
    return _security_notice(
        subject="A recovery code was used to access your account",
        headline_html="A recovery code was used to sign in to your account",
        headline_text="A recovery code was used to sign in to your account",
        when=when, first_name=first_name,
    )


def security_alert(*, first_name: Optional[str], event_label: str,
                    when: Optional[datetime] = None) -> tuple[str, str, str]:
    """Generic security-event notification with a neutral label. No PHI."""
    safe = _html.escape(event_label)[:80]
    return _security_notice(
        subject=f"Security alert: {safe}",
        headline_html=f"A security event occurred on your account ({safe})",
        headline_text=f"A security event occurred on your account ({safe})",
        when=when, first_name=first_name,
    )


# --------------------------------------------------------------------------- #
# 4. Generic portal notification (secure message, form ready, lab ready, …)   #
# --------------------------------------------------------------------------- #
def portal_notification(*, first_name: Optional[str],
                          headline: str = "You have a new notification"
                          ) -> tuple[str, str, str]:
    subject = "You have a new notification in your secure portal"
    g_html, g_text = _greeting(first_name)
    safe_headline = _html.escape(headline)[:120]
    origin = _origin()
    link = f"{origin}/login" if origin else "the secure portal"
    body_html = (
        f'{g_html}'
        f'<p>{safe_headline}. Sign in to your secure {APP_NAME} portal to '
        'review the details.</p>'
        + (f'<p><a href="{_html.escape(link)}">Open the secure portal</a></p>'
            if origin else '<p>Open the secure portal to review it.</p>')
        + f'{_footer_html()}'
    )
    body_text = (
        f"{g_text}\n"
        f"{headline}. Sign in to your secure {APP_NAME} portal to review the details."
        + (f"\n\n{link}" if origin else "")
        + _footer_text()
    )
    return subject, body_html, body_text


# --------------------------------------------------------------------------- #
# 5. Campaign wrapper — the router supplies subject + safe HTML already;      #
#    this helper only appends the standard footer + a plain-text fallback.    #
# --------------------------------------------------------------------------- #
def wrap_campaign(*, subject: str, safe_html: str,
                    plain_text: Optional[str]) -> tuple[str, str, str]:
    footer = _footer_html()
    html_body = f'{safe_html}{footer}'
    if not plain_text:
        # A neutral plain-text fallback (routers should provide their own,
        # but if they don't we keep it privacy-safe).
        plain_text = f"Open the secure {APP_NAME} portal to view this message."
    return subject, html_body, plain_text + _footer_text()
