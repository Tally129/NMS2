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


NMS_LOGO_URL = (
    "https://preview.natmedsol.org/nms-logo.png"
)


def branded_email(
    *,
    eyebrow: str,
    headline: str,
    body_html: str,
    body_text: str,
    cta_label: Optional[str] = None,
    cta_url: Optional[str] = None,
    privacy_notice: Optional[str] = None,
) -> tuple[str, str]:
    """Wrap privacy-safe transactional content in the NMS email design."""

    safe_eyebrow = _html.escape(eyebrow)
    safe_headline = _html.escape(headline)

    cta_html = ""

    if cta_label and cta_url:
        cta_html = (
            '<table role="presentation" cellspacing="0" cellpadding="0" '
            'border="0" style="margin:28px 0 30px;">'
            '<tr><td align="center" '
            'style="background:#66705a;border-radius:999px;">'
            f'<a href="{_html.escape(cta_url)}" '
            'style="display:inline-block;padding:15px 28px;'
            'font-size:15px;line-height:20px;font-weight:bold;'
            'color:#ffffff;text-decoration:none;">'
            f'{_html.escape(cta_label)}</a>'
            '</td></tr></table>'
        )

    privacy_html = ""

    if privacy_notice:
        privacy_html = (
            '<table role="presentation" width="100%" cellspacing="0" '
            'cellpadding="0" border="0" '
            'style="background:#f8f6ef;border-left:4px solid #c6a968;'
            'border-radius:8px;">'
            '<tr><td style="padding:18px 20px;font-size:13px;'
            'line-height:21px;color:#68695f;">'
            '<strong style="color:#4f5248;">Privacy &amp; Security</strong>'
            '<br>'
            f'{_html.escape(privacy_notice)}'
            '</td></tr></table>'
        )

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta
    name="viewport"
    content="width=device-width, initial-scale=1"
  >
  <title>{safe_headline}</title>
</head>

<body
  style="
    margin:0;
    padding:0;
    background:#f4f1e8;
    font-family:Arial,Helvetica,sans-serif;
    color:#34382f;
  "
>
<table
  role="presentation"
  width="100%"
  cellspacing="0"
  cellpadding="0"
  border="0"
  style="background:#f4f1e8;"
>
<tr>
<td align="center" style="padding:40px 16px;">

<table
  role="presentation"
  width="100%"
  cellspacing="0"
  cellpadding="0"
  border="0"
  style="
    max-width:620px;
    background:#ffffff;
    border:1px solid #e4dfd2;
    border-radius:18px;
    overflow:hidden;
  "
>

<tr>
<td
  align="center"
  style="
    padding:30px 28px 26px;
    background:#66705a;
  "
>
<img
  src="{NMS_LOGO_URL}"
  width="155"
  alt="Natural Medical Solutions"
  style="
    display:block;
    width:155px;
    max-width:100%;
    height:auto;
    margin:0 auto 18px;
    border:0;
    outline:none;
    text-decoration:none;
  "
>

<div
  style="
    font-size:11px;
    line-height:18px;
    letter-spacing:2.7px;
    text-transform:uppercase;
    color:#eee6c7;
    font-weight:bold;
  "
>
Natural Medical Solutions
</div>

<div
  style="
    margin-top:5px;
    font-family:Georgia,'Times New Roman',serif;
    font-size:22px;
    line-height:30px;
    color:#ffffff;
  "
>
Wellness Center
</div>
</td>
</tr>

<tr>
<td
  style="
    height:5px;
    background:#c6a968;
    font-size:0;
    line-height:0;
  "
>
&nbsp;
</td>
</tr>

<tr>
<td style="padding:40px 38px 34px;">

<div
  style="
    margin-bottom:9px;
    font-size:11px;
    line-height:18px;
    font-weight:bold;
    letter-spacing:1.8px;
    text-transform:uppercase;
    color:#9a8149;
  "
>
{safe_eyebrow}
</div>

<h1
  style="
    margin:0 0 20px;
    font-family:Georgia,'Times New Roman',serif;
    font-size:30px;
    line-height:38px;
    font-weight:normal;
    color:#34382f;
  "
>
{safe_headline}
</h1>

<div
  style="
    font-size:16px;
    line-height:26px;
    color:#55584f;
  "
>
{body_html}
</div>

{cta_html}

{privacy_html}

</td>
</tr>

<tr>
<td
  align="center"
  style="
    padding:24px 30px 28px;
    border-top:1px solid #eee9dd;
    font-size:12px;
    line-height:20px;
    color:#89897f;
  "
>
<strong style="color:#62665a;">
Natural Medical Solutions Wellness Center
</strong>
<br>
Automated secure notification
</td>
</tr>

</table>

<div
  style="
    max-width:620px;
    padding:17px 20px 0;
    font-size:11px;
    line-height:18px;
    color:#99988f;
    text-align:center;
  "
>
This operational notification was generated by the
Natural Medical Solutions secure system.
</div>

</td>
</tr>
</table>
</body>
</html>
"""

    text_parts = [
        APP_NAME,
        headline,
        "",
        body_text.strip(),
    ]

    if cta_label and cta_url:
        text_parts.extend([
            "",
            f"{cta_label}: {cta_url}",
        ])

    if privacy_notice:
        text_parts.extend([
            "",
            "Privacy & Security",
            privacy_notice,
        ])

    text_parts.extend([
        "",
        "--",
        "Natural Medical Solutions Wellness Center",
        "Automated secure notification",
    ])

    return html, "\n".join(text_parts).strip()



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
# 1. Account setup                                                            #
# --------------------------------------------------------------------------- #
def account_setup(
    *,
    first_name: Optional[str],
    setup_url: str,
    expires_in_hours: int,
) -> tuple[str, str, str]:
    subject = f"Set up your {APP_NAME} account"

    safe_name = (
        _html.escape(
            (first_name or "").strip().split()[0]
        )
        if first_name
        else ""
    )

    greeting_html = (
        f"<p>Hi {safe_name},</p>"
        if safe_name
        else "<p>Hi,</p>"
    )

    greeting_text = (
        f"Hi {first_name.strip().split()[0]},\n\n"
        if first_name
        else "Hi,\n\n"
    )

    body_html = (
        greeting_html
        + "<p>An administrator has invited you to join the "
        "Natural Medical Solutions secure staff portal.</p>"
        "<p>Use the button below to create your password and "
        "complete your account setup.</p>"
        f'<p style="font-size:13px;color:#777;">'
        f'This one-time link expires in '
        f'{int(expires_in_hours)} hours.</p>'
    )

    body_text = (
        greeting_text
        + "An administrator has invited you to join the "
        "Natural Medical Solutions secure staff portal.\n\n"
        + "Use the secure account setup link to create your "
        "password and complete your account setup.\n\n"
        + f"This one-time link expires in "
        f"{int(expires_in_hours)} hours."
    )

    html, plain = branded_email(
        eyebrow="Account Setup",
        headline="Welcome to Natural Medical Solutions",
        body_html=body_html,
        body_text=body_text,
        cta_label="Set Up Your Account",
        cta_url=setup_url,
        privacy_notice=(
            "This is a secure account notification. "
            "Do not forward your one-time setup link."
        ),
    )

    return subject, html, plain


# --------------------------------------------------------------------------- #
# 2. Password reset                                                           #
# --------------------------------------------------------------------------- #
def password_reset(
    *,
    first_name: Optional[str],
    reset_url: str,
    expires_in_minutes: int,
) -> tuple[str, str, str]:
    subject = f"Reset your {APP_NAME} password"

    safe_name = (
        _html.escape(
            (first_name or "").strip().split()[0]
        )
        if first_name
        else ""
    )

    greeting_html = (
        f"<p>Hi {safe_name},</p>"
        if safe_name
        else "<p>Hi,</p>"
    )

    greeting_text = (
        f"Hi {first_name.strip().split()[0]},\n\n"
        if first_name
        else "Hi,\n\n"
    )

    body_html = (
        greeting_html
        + "<p>We received a request to reset the password "
        "for your Natural Medical Solutions account.</p>"
        "<p>If you made this request, use the secure button "
        "below to choose a new password.</p>"
        f'<p style="font-size:13px;color:#777;">'
        f'This one-time link expires in '
        f'{int(expires_in_minutes)} minutes.</p>'
        "<p>If you did not request a password reset, "
        "you can safely ignore this email.</p>"
    )

    body_text = (
        greeting_text
        + "We received a request to reset the password "
        "for your Natural Medical Solutions account.\n\n"
        + "If you made this request, use the secure link "
        "below to choose a new password.\n\n"
        + f"This one-time link expires in "
        f"{int(expires_in_minutes)} minutes.\n\n"
        + "If you did not request a password reset, "
        "you can safely ignore this email."
    )

    html, plain = branded_email(
        eyebrow="Account Security",
        headline="Reset Your Password",
        body_html=body_html,
        body_text=body_text,
        cta_label="Reset Password",
        cta_url=reset_url,
        privacy_notice=(
            "Natural Medical Solutions will never ask you "
            "to send your password by email."
        ),
    )

    return subject, html, plain


# --------------------------------------------------------------------------- #
# 3. Security notices                                                         #
# --------------------------------------------------------------------------- #
def _security_notice(
    *,
    subject: str,
    headline_html: str,
    headline_text: str,
    when: Optional[datetime],
    first_name: Optional[str],
) -> tuple[str, str, str]:
    safe_name = (
        _html.escape(
            (first_name or "").strip().split()[0]
        )
        if first_name
        else ""
    )

    greeting_html = (
        f"<p>Hi {safe_name},</p>"
        if safe_name
        else "<p>Hi,</p>"
    )

    greeting_text = (
        f"Hi {first_name.strip().split()[0]},\n\n"
        if first_name
        else "Hi,\n\n"
    )

    when_str = (
        when or datetime.now(timezone.utc)
    ).strftime("%Y-%m-%d %H:%M UTC")

    origin = _origin()
    portal_url = (
        f"{origin}/login"
        if origin
        else None
    )

    body_html = (
        greeting_html
        + f"<p>{headline_html} at "
        f"<strong>{_html.escape(when_str)}</strong>.</p>"
        "<p>If this was you, no action is required.</p>"
        "<p>If you do not recognize this activity, "
        "sign in immediately, change your password, "
        "and contact Natural Medical Solutions.</p>"
    )

    body_text = (
        greeting_text
        + f"{headline_text} at {when_str}.\n\n"
        + "If this was you, no action is required.\n\n"
        + "If you do not recognize this activity, sign in "
        "immediately, change your password, and contact "
        "Natural Medical Solutions."
    )

    html, plain = branded_email(
        eyebrow="Security Notification",
        headline="Account Security Notice",
        body_html=body_html,
        body_text=body_text,
        cta_label=(
            "Open Secure Portal"
            if portal_url
            else None
        ),
        cta_url=portal_url,
        privacy_notice=(
            "This notification intentionally contains "
            "limited account information for your security."
        ),
    )

    return subject, html, plain


def password_changed(
    *,
    first_name: Optional[str],
    when: Optional[datetime] = None,
) -> tuple[str, str, str]:
    return _security_notice(
        subject="Your password was changed",
        headline_html=(
            "Your account password was changed"
        ),
        headline_text=(
            "Your account password was changed"
        ),
        when=when,
        first_name=first_name,
    )


def mfa_enabled(
    *,
    first_name: Optional[str],
    when: Optional[datetime] = None,
) -> tuple[str, str, str]:
    return _security_notice(
        subject="Multi-factor authentication was enabled",
        headline_html=(
            "Multi-factor authentication was enabled "
            "on your account"
        ),
        headline_text=(
            "Multi-factor authentication was enabled "
            "on your account"
        ),
        when=when,
        first_name=first_name,
    )


def recovery_code_used(
    *,
    first_name: Optional[str],
    when: Optional[datetime] = None,
) -> tuple[str, str, str]:
    return _security_notice(
        subject=(
            "A recovery code was used to access your account"
        ),
        headline_html=(
            "A recovery code was used to sign in "
            "to your account"
        ),
        headline_text=(
            "A recovery code was used to sign in "
            "to your account"
        ),
        when=when,
        first_name=first_name,
    )


def security_alert(
    *,
    first_name: Optional[str],
    event_label: str,
    when: Optional[datetime] = None,
) -> tuple[str, str, str]:
    safe = _html.escape(event_label)[:80]

    return _security_notice(
        subject=f"Security alert: {safe}",
        headline_html=(
            f"A security event occurred on your account "
            f"({_html.escape(safe)})"
        ),
        headline_text=(
            f"A security event occurred on your account "
            f"({safe})"
        ),
        when=when,
        first_name=first_name,
    )


# --------------------------------------------------------------------------- #
# 4. Generic portal notification                                              #
# --------------------------------------------------------------------------- #
def portal_notification(
    *,
    first_name: Optional[str],
    headline: str = "You have a new notification",
) -> tuple[str, str, str]:
    subject = (
        "You have a new notification in your secure portal"
    )

    safe_name = (
        _html.escape(
            (first_name or "").strip().split()[0]
        )
        if first_name
        else ""
    )

    greeting_html = (
        f"<p>Hi {safe_name},</p>"
        if safe_name
        else "<p>Hi,</p>"
    )

    greeting_text = (
        f"Hi {first_name.strip().split()[0]},\n\n"
        if first_name
        else "Hi,\n\n"
    )

    safe_headline = _html.escape(headline)[:120]

    origin = _origin()
    portal_url = (
        f"{origin}/login"
        if origin
        else None
    )

    body_html = (
        greeting_html
        + f"<p>{safe_headline}.</p>"
        "<p>For your privacy, details are available only "
        "inside the secure Natural Medical Solutions "
        "portal.</p>"
    )

    body_text = (
        greeting_text
        + f"{headline}.\n\n"
        + "For your privacy, details are available only "
        "inside the secure Natural Medical Solutions portal."
    )

    html, plain = branded_email(
        eyebrow="Secure Portal",
        headline="You Have a New Notification",
        body_html=body_html,
        body_text=body_text,
        cta_label=(
            "Open Secure Portal"
            if portal_url
            else None
        ),
        cta_url=portal_url,
        privacy_notice=(
            "Sensitive information is not included in "
            "this email. Sign in to the secure portal "
            "to review details."
        ),
    )

    return subject, html, plain



# --------------------------------------------------------------------------- #
# Transactional / portal notifications                                       #
# --------------------------------------------------------------------------- #

def secure_message_notification(
    *,
    portal_url: str,
    sender_label: str = "your care team",
) -> tuple[str, str, str]:
    """Privacy-safe notification that a secure message is waiting."""

    subject = "New secure message available"

    safe_sender = _html.escape(
        (sender_label or "your care team")[:80]
    )

    body_html = (
        f"<p>You have a new secure message from {safe_sender}.</p>"
        "<p>For your privacy, the message itself is not included "
        "in this email.</p>"
        "<p>Sign in to the secure portal to read and respond.</p>"
        "<p style=\"font-size:13px;color:#777;\">"
        "This inbox is not monitored for emergencies. "
        "Call 911 for an emergency.</p>"
    )

    body_text = (
        f"You have a new secure message from {sender_label}.\n\n"
        "For your privacy, the message itself is not included "
        "in this email.\n\n"
        "Sign in to the secure portal to read and respond.\n\n"
        "This inbox is not monitored for emergencies. "
        "Call 911 for an emergency."
    )

    html, plain = branded_email(
        eyebrow="Secure Message",
        headline="You Have a New Secure Message",
        body_html=body_html,
        body_text=body_text,
        cta_label="Read Secure Message",
        cta_url=portal_url,
        privacy_notice=(
            "Message contents and other sensitive information "
            "are available only after signing in to the secure portal."
        ),
    )

    return subject, html, plain


def portal_update_notification(
    *,
    first_name: Optional[str],
    subject: str,
    heading: str,
    message: str,
    portal_url: str,
) -> tuple[str, str, str]:
    """Generic privacy-safe patient portal update."""

    safe_name = (
        _html.escape(
            (first_name or "").strip().split()[0]
        )
        if first_name
        else ""
    )

    greeting_html = (
        f"<p>Hi {safe_name},</p>"
        if safe_name
        else "<p>Hi,</p>"
    )

    greeting_text = (
        f"Hi {(first_name or '').strip().split()[0]},\n\n"
        if first_name
        else "Hi,\n\n"
    )

    safe_message = _html.escape(message)

    body_html = (
        greeting_html
        + f"<p>{safe_message}</p>"
        "<p>Sign in to your secure patient portal to review "
        "the information.</p>"
    )

    body_text = (
        greeting_text
        + message
        + "\n\nSign in to your secure patient portal "
        "to review the information."
    )

    html, plain = branded_email(
        eyebrow="Patient Portal",
        headline=heading,
        body_html=body_html,
        body_text=body_text,
        cta_label="Open Patient Portal",
        cta_url=portal_url,
        privacy_notice=(
            "Clinical details, results, and other sensitive "
            "information are not included in this email."
        ),
    )

    return subject, html, plain


def appointment_status_notification(
    *,
    action: str,
    suggested_time: Optional[str] = None,
) -> tuple[str, str, str]:
    """Patient-facing appointment request status email."""

    if action == "approve":
        subject = "Your appointment request has been approved"
        eyebrow = "Appointment Request"
        headline = "Your Request Has Been Approved"
        message = (
            "Good news — your appointment request has been approved. "
            "Our staff will contact you with any additional "
            "confirmation details."
        )
        cta_label = "Open Patient Portal"

    elif action == "decline":
        subject = "Update on your appointment request"
        eyebrow = "Appointment Request"
        headline = "An Update on Your Request"
        message = (
            "We are unable to accommodate the requested appointment "
            "at this time. Please contact Natural Medical Solutions "
            "or submit another appointment request so we can help "
            "find an alternative."
        )
        cta_label = "Request Another Appointment"

    elif action == "reschedule":
        subject = "Alternative time for your appointment"
        eyebrow = "Appointment Request"
        headline = "A Different Appointment Time Is Available"

        if suggested_time:
            message = (
                "Our team would like to propose a different "
                f"appointment time: {suggested_time}."
            )
        else:
            message = (
                "Our team would like to propose a different "
                "appointment time. Please review the update "
                "and contact us if you have questions."
            )

        cta_label = "Open Patient Portal"

    else:
        subject = "Update on your appointment request"
        eyebrow = "Appointment Request"
        headline = "Your Appointment Request Was Updated"
        message = (
            "There is an update regarding your appointment request."
        )
        cta_label = "Open Patient Portal"

    if action == "decline":
        cta_url = (
            "https://app.natmedsol.org/request-appointment"
        )
    else:
        cta_url = "https://app.natmedsol.org/"

    safe_message = _html.escape(message)

    body_html = (
        f"<p>{safe_message}</p>"
        "<p>Thank you for choosing Natural Medical Solutions.</p>"
    )

    body_text = (
        message
        + "\n\nThank you for choosing "
        "Natural Medical Solutions."
    )

    html, plain = branded_email(
        eyebrow=eyebrow,
        headline=headline,
        body_html=body_html,
        body_text=body_text,
        cta_label=cta_label,
        cta_url=cta_url,
        privacy_notice=(
            "For your privacy, this email contains only limited "
            "appointment information."
        ),
    )

    return subject, html, plain


# --------------------------------------------------------------------------- #
# 5. Campaign wrapper — the router supplies subject + safe HTML already;      #
#    this helper only appends the standard footer + a plain-text fallback.    #
# --------------------------------------------------------------------------- #

def form_request_notification(
    *,
    first_name: Optional[str],
    form_title: str,
    submit_url: str,
) -> tuple[str, str, str]:
    """Branded patient form request."""

    safe_title = _html.escape(
        (form_title or "requested form").strip()
    )

    safe_name = (
        _html.escape(
            (first_name or "").strip().split()[0]
        )
        if first_name
        else ""
    )

    greeting_html = (
        f"<p>Hi {safe_name},</p>"
        if safe_name
        else "<p>Hi,</p>"
    )

    greeting_text = (
        f"Hi {(first_name or '').strip().split()[0]},\n\n"
        if first_name
        else "Hi,\n\n"
    )

    subject = f"Action requested: {form_title}"

    body_html = (
        greeting_html
        + "<p>Natural Medical Solutions has sent you "
          "a secure form to complete.</p>"
        + f"<p><strong>{safe_title}</strong></p>"
        + "<p>Please use the secure button below to "
          "open and complete the form.</p>"
    )

    body_text = (
        greeting_text
        + "Natural Medical Solutions has sent you "
          "a secure form to complete.\n\n"
        + f"{form_title}\n\n"
        + "Use the secure link below to open and "
          "complete the form."
    )

    html, plain = branded_email(
        eyebrow="Secure Form",
        headline="A Form Is Ready for You",
        body_html=body_html,
        body_text=body_text,
        cta_label="Open Secure Form",
        cta_url=submit_url,
        privacy_notice=(
            "For your privacy, sensitive information "
            "is not included in this email."
        ),
    )

    return subject, html, plain


def invoice_notification(
    *,
    first_name: Optional[str],
    invoice_number: str,
    total: float,
    note: Optional[str] = None,
) -> tuple[str, str, str]:
    """Branded transactional invoice email."""

    safe_name = (
        _html.escape(
            (first_name or "").strip().split()[0]
        )
        if first_name
        else ""
    )

    safe_invoice = _html.escape(
        str(invoice_number)
    )

    greeting_html = (
        f"<p>Hi {safe_name},</p>"
        if safe_name
        else "<p>Hi,</p>"
    )

    greeting_text = (
        f"Hi {(first_name or '').strip().split()[0]},\n\n"
        if first_name
        else "Hi,\n\n"
    )

    amount = f"${float(total or 0):,.2f}"

    note_html = ""
    note_text = ""

    if note:
        safe_note = _html.escape(str(note))
        note_html = f"<p>{safe_note}</p>"
        note_text = f"\n\n{note}"

    subject = (
        f"Invoice {invoice_number} | "
        "Natural Medical Solutions"
    )

    body_html = (
        greeting_html
        + "<p>Your invoice from Natural Medical "
          "Solutions is attached to this email.</p>"
        + f"<p>Invoice: <strong>{safe_invoice}</strong><br>"
          f"Total: <strong>{amount}</strong></p>"
        + note_html
        + "<p>Thank you for choosing "
          "Natural Medical Solutions.</p>"
    )

    body_text = (
        greeting_text
        + "Your invoice from Natural Medical Solutions "
          "is attached to this email.\n\n"
        + f"Invoice: {invoice_number}\n"
        + f"Total: {amount}"
        + note_text
        + "\n\nThank you for choosing "
          "Natural Medical Solutions."
    )

    html, plain = branded_email(
        eyebrow="Billing",
        headline="Your Invoice Is Attached",
        body_html=body_html,
        body_text=body_text,
        privacy_notice=(
            "This message was sent regarding billing "
            "activity with Natural Medical Solutions."
        ),
    )

    return subject, html, plain



def wrap_campaign(*, subject: str, safe_html: str,
                    plain_text: Optional[str]) -> tuple[str, str, str]:
    footer = _footer_html()
    html_body = f'{safe_html}{footer}'
    if not plain_text:
        # A neutral plain-text fallback (routers should provide their own,
        # but if they don't we keep it privacy-safe).
        plain_text = f"Open the secure {APP_NAME} portal to view this message."
    return subject, html_body, plain_text + _footer_text()
