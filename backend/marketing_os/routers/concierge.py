"""Marketing OS AI Concierge API.

Current release:
- internal health/capability endpoint only.

The anonymous public chat route is intentionally NOT enabled yet.
"""

from fastapi import Depends

from deps import api, require_roles

from marketing_os.concierge.service import (
    concierge_status,
)


CONCIERGE_ADMIN_ROLES = (
    "admin",
    "practitioner",
)


@api.get("/marketing-os/concierge/health")
async def concierge_health(
    user=Depends(
        require_roles(*CONCIERGE_ADMIN_ROLES)
    ),
):
    return concierge_status()


# ---------------------------------------------------------------------------
# Future browser-facing NMS AI Concierge route.
#
# IMPORTANT:
# The route exists at the application layer for security testing but remains
# fail-closed while DEFAULT_CONCIERGE_POLICY.public_enabled is False.
# ---------------------------------------------------------------------------

from fastapi import HTTPException, Request

from marketing_os.concierge.engine import (
    generate_concierge_response,
)
from marketing_os.concierge.public_boundary import (
    PublicBoundaryError,
    parse_public_appointment_body,
    parse_public_chat_body,
    public_appointment_enabled,
    public_chat_enabled,
    require_concierge_bff_key,
    require_allowed_origin,
)
from marketing_os.concierge.schemas import (
    ConciergeAppointmentAction,
    ConciergeChatResponse,
    ConciergePublicAppointmentResponse,
)
from marketing_os.concierge.appointment_handoff import (
    ConciergeAppointmentRequest,
    create_concierge_appointment_request,
)


@api.post(
    "/public/concierge/chat",
    response_model=ConciergeChatResponse,
)
async def public_concierge_chat(
    request: Request,
):
    if not public_chat_enabled():
        raise HTTPException(
            status_code=404,
            detail={
                "code":
                    "concierge_not_available",
            },
        )

    try:
        require_concierge_bff_key(
            request.headers.get(
                "x-nms-concierge-bff-key"
            )
        )

        require_allowed_origin(
            request.headers.get(
                "origin"
            )
        )

        raw_body = await request.body()

        payload = parse_public_chat_body(
            raw_body
        )

    except PublicBoundaryError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "code": exc.code,
            },
        ) from None

    result = await generate_concierge_response(
        payload.message,
        session_id=payload.session_id,
        page_url=payload.page_url,
        page_title=payload.page_title,
    )

    return ConciergeChatResponse(
        session_id=result.session_id,
        answer=result.answer,
        appointment_url=(
            result.appointment_url
        ),
        handoff_recommended=(
            result.handoff_recommended
        ),
        appointment_action=(
            ConciergeAppointmentAction(
                offered=(
                    result.appointment_action.offered
                ),
                inline_request_enabled=(
                    result.appointment_action
                    .inline_request_enabled
                ),
                appointment_url=(
                    result.appointment_action
                    .appointment_url
                ),
            )
        ),
        source_pages=list(
            result.source_pages
        ),
    )


async def _resolve_public_service_name(
    service_id: str | None,
) -> str | None:
    """Resolve only an active, explicitly public treatment."""

    if service_id is None:
        return None

    from marketing_os.concierge.app_knowledge import (
        load_public_treatments,
    )

    treatments = await load_public_treatments()

    for treatment in treatments:
        if str(
            treatment.get("id") or ""
        ) != service_id:
            continue

        name = str(
            treatment.get("name") or ""
        ).strip()

        if name:
            return name

    raise ValueError(
        "invalid public service"
    )


@api.post(
    "/public/concierge/appointment-request",
    response_model=ConciergePublicAppointmentResponse,
)
async def public_concierge_appointment_request(
    request: Request,
):
    # Use the same fail-closed Concierge publication gate.
    # While disabled, no browser body is parsed and no write path
    # can be reached.
    if not public_appointment_enabled():
        raise HTTPException(
            status_code=404,
            detail={
                "code":
                    "concierge_not_available",
            },
        )

    try:
        require_concierge_bff_key(
            request.headers.get(
                "x-nms-concierge-bff-key"
            )
        )

        require_allowed_origin(
            request.headers.get(
                "origin"
            )
        )

        raw_body = await request.body()

        payload = (
            parse_public_appointment_body(
                raw_body
            )
        )

    except PublicBoundaryError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "code": exc.code,
            },
        ) from None

    full_name = " ".join(
        (
            payload.first_name.strip(),
            payload.last_name.strip(),
        )
    ).strip()

    try:
        result = await (
            create_concierge_appointment_request(
                ConciergeAppointmentRequest(
                    full_name=full_name,
                    email=payload.email,
                    phone=payload.phone,
                    returning=payload.returning,
                    service=await _resolve_public_service_name(
                        payload.service_id
                    ),
                    date=payload.date,
                    time=payload.time,
                ),
                confirmed=payload.confirmed,
                idempotency_key=(
                    payload.idempotency_key
                ),
                client_ip=(
                    request.client.host
                    if request.client
                    else None
                ),
            )
        )
    except ValueError:
        # Do not expose detailed internal validation information.
        raise HTTPException(
            status_code=422,
            detail={
                "code":
                    "concierge_invalid_request",
            },
        ) from None

    request_id = str(
        result.appointment_request.get(
            "id",
            "",
        )
    ).strip()

    if not request_id:
        raise HTTPException(
            status_code=500,
            detail={
                "code":
                    "concierge_submission_failed",
            },
        )

    return ConciergePublicAppointmentResponse(
        request_id=request_id,
        replayed=result.replayed,
    )
