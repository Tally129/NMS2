"""
Canonical Natural Medical Solutions appointment-request workflow.

This module owns appointment-request application orchestration so all
entry points use the same persistence, Marketing OS attribution,
staff notification, integration logging, and audit behavior.

It does not expose an HTTP route.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from audit import log_audit
from deps import db, logger
from models import AppointmentRequestIn, new_id
from postgres_db import AsyncSessionLocal
from repositories import scheduling as sched_repo


async def create_appointment_request_workflow(
    payload: AppointmentRequestIn,
    *,
    client_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    marketing_attribution: Optional[str] = None,
    concierge_idempotency_key: Optional[str] = None,
):
    doc = payload.model_dump()
    doc["id"] = new_id()
    doc["status"] = "new"
    doc["ip"] = client_ip

    if concierge_idempotency_key:
        doc["concierge_idempotency_key"] = (
            concierge_idempotency_key
        )

    async with AsyncSessionLocal() as pg:
        async with pg.begin():
            doc = await sched_repo.create_appointment_request(pg, doc)

    # ---------------------------------------------------------------
    # First-party Marketing OS attribution bridge.
    #
    # Marketing metadata arrives separately from the appointment
    # payload so contact/clinical fields never enter Marketing OS.
    #
    # Attribution is best-effort: a marketing measurement failure
    # must never cause a successfully stored appointment request to
    # fail.
    # ---------------------------------------------------------------
    marketing_header = marketing_attribution

    if marketing_header:
        try:
            import json as _json

            from marketing_os.services.persistence import (
                persist_conversion_and_attribution,
            )

            raw_marketing = _json.loads(marketing_header)

            if not isinstance(raw_marketing, dict):
                raise ValueError(
                    "marketing attribution must be an object"
                )

            allowed = {
                "session_id",
                "external_click_id",
                "source",
                "medium",
                "campaign",
                "content",
                "term",
                "click_id_type",
            }

            marketing = {
                key: value
                for key, value in raw_marketing.items()
                if key in allowed
            }

            properties = {}

            click_id_type = marketing.pop(
                "click_id_type",
                None,
            )

            if click_id_type:
                properties["click_id_type"] = (
                    str(click_id_type)[:32]
                )

            conversion_payload = {
                "event_type": "lead_submit",
                **marketing,
                "properties": properties,
            }

            async with AsyncSessionLocal() as marketing_pg:
                async with marketing_pg.begin():
                    await persist_conversion_and_attribution(
                        marketing_pg,
                        payload=conversion_payload,
                        idempotency_key=(
                            "appointment-request:"
                            + str(doc["id"])
                        ),
                        provider="first_party",
                    )

        except Exception as exc:
            # Do not log appointment/contact payload values.
            logger.warning(
                "Marketing attribution capture failed for "
                "appointment request %s: %s",
                doc.get("id"),
                type(exc).__name__,
            )

    # Appointment storage has already committed above. Operational follow-up
    # must not make a successfully stored request appear failed to the visitor.
    try:
        from notifiers import send_email as _send_email

        notification_email = os.environ.get(
            "APPOINTMENT_REQUEST_NOTIFICATION_EMAIL",
            ""
        ).strip()

        if not notification_email:
            logger.error(
                "Appointment request notification email is not configured"
            )
            _delivery = "not_configured"
        else:
            _delivery = await _send_email(
                db=db,
                to=notification_email,
                subject=(
                    "New Appointment Request | "
                    "Natural Medical Solutions"
                ),
                html="""
    <!doctype html>
    <html lang="en">
    <head>
      <meta charset="utf-8">
      <meta
        name="viewport"
        content="width=device-width, initial-scale=1"
      >
      <title>New Appointment Request</title>
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
          <td
            align="center"
            style="padding:40px 16px;"
          >

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

              <!-- NMS BRAND HEADER -->
              <tr>
                <td
                  align="center"
                  style="
                    padding:30px 28px 26px;
                    background:#66705a;
                  "
                >

                  <img
                    src="https://preview.natmedsol.org/nms-logo.png"
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

              <!-- GOLD ACCENT -->
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

              <!-- MAIN MESSAGE -->
              <tr>
                <td
                  style="
                    padding:40px 38px 34px;
                  "
                >

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
                    Appointment Notification
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
                    New Appointment Request
                  </h1>

                  <p
                    style="
                      margin:0 0 18px;
                      font-size:16px;
                      line-height:26px;
                      color:#55584f;
                    "
                  >
                    A new appointment request has been submitted
                    through the Natural Medical Solutions
                    appointment portal.
                  </p>

                  <p
                    style="
                      margin:0 0 28px;
                      font-size:16px;
                      line-height:26px;
                      color:#55584f;
                    "
                  >
                    Please sign in to the secure staff portal to
                    review and process the request.
                  </p>

                  <!-- CTA BUTTON -->
                  <table
                    role="presentation"
                    cellspacing="0"
                    cellpadding="0"
                    border="0"
                    style="margin:0 0 30px;"
                  >
                    <tr>
                      <td
                        align="center"
                        style="
                          background:#66705a;
                          border-radius:999px;
                        "
                      >
                        <a
                          href="https://app.natmedsol.org/"
                          style="
                            display:inline-block;
                            padding:15px 28px;
                            font-size:15px;
                            line-height:20px;
                            font-weight:bold;
                            color:#ffffff;
                            text-decoration:none;
                          "
                        >
                          Review Appointment Requests
                        </a>
                      </td>
                    </tr>
                  </table>

                  <!-- PRIVACY CARD -->
                  <table
                    role="presentation"
                    width="100%"
                    cellspacing="0"
                    cellpadding="0"
                    border="0"
                    style="
                      background:#f8f6ef;
                      border-left:4px solid #c6a968;
                      border-radius:8px;
                    "
                  >
                    <tr>
                      <td
                        style="
                          padding:18px 20px;
                          font-size:13px;
                          line-height:21px;
                          color:#68695f;
                        "
                      >
                        <strong
                          style="color:#4f5248;"
                        >
                          Privacy &amp; Security
                        </strong>

                        <br>

                        For patient privacy, personal information
                        and appointment details are not included
                        in this notification. Review request
                        information only through the secure
                        staff portal.
                      </td>
                    </tr>
                  </table>

                </td>
              </tr>

              <!-- FOOTER -->
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
                  <strong
                    style="color:#62665a;"
                  >
                    Natural Medical Solutions Wellness Center
                  </strong>

                  <br>

                  Automated staff appointment notification
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
              This operational notification was generated by
              the Natural Medical Solutions secure appointment
              system.
            </div>

          </td>
        </tr>
      </table>
    </body>
    </html>
    """,
                action="appointment_request.new",
            )

    except Exception as exc:
        # Appointment storage has already succeeded. Notification
        # failure must not affect the visitor response or suppress
        # subsequent operational logging/audit attempts.
        logger.error(
            "Appointment request notification failed for "
            "request %s: %s",
            doc.get("id"),
            type(exc).__name__,
        )
        _delivery = "failed"

    # Explicit operational notification record. This is deliberately
    # independent from SendGrid/notifier behavior.
    try:
        await db.integration_log.insert_one({
            "id": new_id(),
            "service": "sendgrid",
            "action": "appointment_request_notification",
            # Operational record deliberately excludes recipient/contact
            # addresses. The appointment request itself remains the
            # authoritative record for visitor contact information.
            "payload": {
                "request_id": doc["id"],
            },
            "_stubbed": _delivery == "sent_stub",
            "delivery_status": _delivery,
            "ts": datetime.now(timezone.utc),
        })
    except Exception as exc:
        # Do not log appointment/contact payload values.
        logger.error(
            "Appointment request integration log failed for "
            "request %s: %s",
            doc.get("id"),
            type(exc).__name__,
        )

    # Audit is also independent. A notification or integration-log
    # failure must never prevent this attempt.
    try:
        await log_audit(
            db,
            None,
            None,
            "appointment_request.create",
            resource_type="appointment_request",
            resource_id=doc["id"],
            # Do not duplicate visitor name/email into the audit trail.
            # The resource_id links this event to the authoritative
            # appointment-request record when operational review is needed.
            metadata={"source": "public_appointment_request"},
            ip=client_ip,
            user_agent=user_agent,
        )
    except Exception as exc:
        # Do not log appointment/contact payload values.
        logger.error(
            "Appointment request audit failed for "
            "request %s: %s",
            doc.get("id"),
            type(exc).__name__,
        )

    return {"ok": True, "id": doc["id"]}


# =================== STAFF REVIEW WORKFLOW ===================
