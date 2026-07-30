"""oauth — split from routers/auth.py during Session 1 of the PG migration.
Behaviour is unchanged. All helpers are shared via _common."""
from ._common import *  # noqa: F401,F403

# --------------------------------------------------------------------------- #
# Google SSO — Emergent-managed session exchange                              #
# (Slated to be replaced with direct Google OAuth for BAA compliance.)        #
# --------------------------------------------------------------------------- #
@api.post("/auth/google/session")
async def google_session_exchange(request: Request):
    """Exchange Emergent Auth session_id (header X-Session-ID) for our internal JWT."""
    session_id = request.headers.get("X-Session-ID") or request.headers.get("x-session-id")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing X-Session-ID header")
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            r = await client.get(
                "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
                headers={"X-Session-ID": session_id},
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Auth provider unreachable: {e}")
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid session")
    data = r.json()
    email = (data.get("email") or "").lower().strip()
    if not email:
        raise HTTPException(status_code=400, detail="No email returned by auth provider")

    user = await db.users.find_one({"email": email})
    if not user:
        # Auto-create new client account
        user = {
            "id": new_id(),
            "email": email,
            "full_name": data.get("name") or email.split("@")[0],
            "role": "client",
            "active": True,
            "auth_provider": "google",
            "picture_url": data.get("picture"),
            "created_at": datetime.now(timezone.utc),
        }
        await db.users.insert_one(user)
        # also create a Clients row so /clients/me works
        await db.clients.insert_one({
            "id": new_id(), "user_id": user["id"],
            "full_name": user["full_name"], "email": email,
            "intake_completed": False,
            "created_at": datetime.now(timezone.utc),
        })
    elif not user.get("active", True):
        raise HTTPException(status_code=403, detail="Account disabled")
    else:
        # Update profile picture / link google
        await db.users.update_one(
            {"id": user["id"]},
            {"$set": {"auth_provider": "google", "picture_url": data.get("picture")}},
        )

    # Google-authenticated workforce users can bypass the internal TOTP step
    # when the user's account carries `mfa_bypass=True` — Google's own 2FA
    # counts as the second factor. Non-workforce (clients) never need TOTP.
    google_trusts_mfa = bool(user.get("mfa_bypass")) or (user["role"] not in WORKFORCE_ROLES)
    sid, family_id, raw_refresh = await _create_session(user, request, mfa_satisfied=google_trusts_mfa)
    access = make_access_token(user["id"], user["role"], sid, session_version=user.get("session_version", 1))
    await log_audit(db, user["id"], user["email"], "auth.login_google",
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))
    resp = Response(content=json_dumps_body({
        "access_token": access,
        "user": {"id": user["id"], "email": user["email"], "full_name": user.get("full_name"),
                 "role": user["role"], "picture_url": user.get("picture_url")},
    }), media_type="application/json")
    _set_refresh_cookie(resp, raw_refresh)
    return resp


# --------------------------------------------------------------------------- #
# Direct Google OAuth (replaces Emergent-managed SSO once env vars are set)  #
#                                                                             #
# REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS.   #
# This breaks the auth. All URLs come from env only:                          #
#   GOOGLE_OAUTH_CLIENT_ID                                                    #
#   GOOGLE_OAUTH_CLIENT_SECRET                                                #
#   GOOGLE_OAUTH_REDIRECT_URI  (e.g. https://your.app/api/auth/google/callback)#
#   FRONTEND_ORIGIN            (where to bounce the user after callback)     #
# --------------------------------------------------------------------------- #

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


def _google_oauth_configured() -> bool:
    return bool(
        os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
        and os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
        and os.environ.get("GOOGLE_OAUTH_REDIRECT_URI")
    )


@api.get("/auth/google/oauth/authorize")
async def google_oauth_authorize():
    """Return the Google authorize URL the frontend should redirect the browser to.
    A one-time `state` value is generated and stored briefly in Mongo for CSRF protection."""
    if not _google_oauth_configured():
        raise HTTPException(
            status_code=503,
            detail="Direct Google OAuth not configured. Set GOOGLE_OAUTH_CLIENT_ID / "
                   "GOOGLE_OAUTH_CLIENT_SECRET / GOOGLE_OAUTH_REDIRECT_URI in backend/.env.",
        )
    state = secrets.token_urlsafe(32)
    await db.oauth_states.insert_one({
        "state": state,
        "created_at": datetime.now(timezone.utc),
    })
    params = {
        "client_id": os.environ["GOOGLE_OAUTH_CLIENT_ID"],
        "redirect_uri": os.environ["GOOGLE_OAUTH_REDIRECT_URI"],
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account",
        "state": state,
    }
    return {"authorize_url": f"{_GOOGLE_AUTH_URL}?{urlencode(params)}", "state": state}


@api.get("/auth/google/oauth/callback")
async def google_oauth_callback(request: Request, code: Optional[str] = None,
                                state: Optional[str] = None, error: Optional[str] = None):
    """Handle Google's redirect: exchange code for token, upsert the user, then
    bounce the browser to `${FRONTEND_ORIGIN}/oauth-complete?token=<jwt>&refresh=<jwt>`."""
    if not _google_oauth_configured():
        raise HTTPException(status_code=503, detail="Direct Google OAuth not configured")
    if error:
        raise HTTPException(status_code=400, detail=f"Google returned error: {error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    st = await db.oauth_states.find_one_and_delete({"state": state})
    if not st:
        raise HTTPException(status_code=400, detail="Invalid or expired state")

    # Exchange code for tokens
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            token_resp = await client.post(_GOOGLE_TOKEN_URL, data={
                "code": code,
                "client_id": os.environ["GOOGLE_OAUTH_CLIENT_ID"],
                "client_secret": os.environ["GOOGLE_OAUTH_CLIENT_SECRET"],
                "redirect_uri": os.environ["GOOGLE_OAUTH_REDIRECT_URI"],
                "grant_type": "authorization_code",
            })
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Google token endpoint unreachable: {e}")

    if token_resp.status_code != 200:
        raise HTTPException(status_code=401, detail=f"Token exchange failed: {token_resp.text}")
    tok = token_resp.json()
    access_google = tok.get("access_token")
    if not access_google:
        raise HTTPException(status_code=401, detail="No access token from Google")

    # Fetch userinfo
    async with httpx.AsyncClient(timeout=15.0) as client:
        ui_resp = await client.get(_GOOGLE_USERINFO_URL,
                                    headers={"Authorization": f"Bearer {access_google}"})
    if ui_resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Failed to fetch Google userinfo")
    ui = ui_resp.json()
    email = (ui.get("email") or "").lower().strip()
    if not email:
        raise HTTPException(status_code=400, detail="Google returned no email")
    if not ui.get("email_verified", True):
        raise HTTPException(status_code=403, detail="Email not verified with Google")

    # Upsert user + client
    user = await db.users.find_one({"email": email})
    if not user:
        user = {
            "id": new_id(),
            "email": email,
            "full_name": ui.get("name") or email.split("@")[0],
            "role": "client",
            "is_active": True,
            "auth_provider": "google_direct",
            "picture_url": ui.get("picture"),
            "created_at": datetime.now(timezone.utc),
        }
        await db.users.insert_one(user)
        await db.clients.insert_one({
            "id": new_id(), "user_id": user["id"],
            "full_name": user["full_name"], "email": email,
            "intake_completed": False,
            "created_at": datetime.now(timezone.utc),
        })
    elif not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account disabled")
    else:
        await db.users.update_one(
            {"id": user["id"]},
            {"$set": {
                "auth_provider": "google_direct",
                "picture_url": ui.get("picture"),
                "last_login_at": datetime.now(timezone.utc),
            }},
        )

    _direct_starts = (user["role"] not in WORKFORCE_ROLES) or bool(user.get("mfa_bypass"))
    sid, family_id, raw_refresh = await _create_session(user, request, mfa_satisfied=_direct_starts)
    access = make_access_token(user["id"], user["role"], sid, session_version=user.get("session_version", 1))
    # Store refresh + access under a one-time handoff id so nothing lands in the URL.
    handoff_id = secrets.token_urlsafe(24)
    await db.oauth_handoffs.insert_one({
        "handoff_id": handoff_id,
        "user_id": user["id"],
        "access_token": access,
        "refresh_cookie_value": raw_refresh,
        "created_at": datetime.now(timezone.utc),
        "consumed": False,
    })
    await log_audit(db, user["id"], user["email"], "auth.login_google_direct",
                    ip=get_client_ip(request), user_agent=request.headers.get("user-agent"))

    frontend_origin = os.environ.get("FRONTEND_ORIGIN")
    if not frontend_origin:
        raise HTTPException(status_code=500,
                            detail="FRONTEND_ORIGIN env var required for OAuth completion redirect")
    complete_url = f"{frontend_origin.rstrip('/')}/oauth-complete?handoff={handoff_id}"
    return RedirectResponse(url=complete_url, status_code=302)


@api.post("/auth/google/oauth/exchange")
async def google_oauth_exchange(payload: dict):
    """Redeem a one-time OAuth handoff id (from callback redirect) for the
    access token + user profile. The opaque refresh token is delivered ONLY via
    the `nms_rt` HttpOnly cookie (Sprint 2 policy). Handoff is single-use and
    expires after 5 minutes."""
    handoff_id = (payload or {}).get("handoff_id")
    if not handoff_id:
        raise HTTPException(status_code=400, detail="Missing handoff_id")
    row = await db.oauth_handoffs.find_one_and_update(
        {"handoff_id": handoff_id, "consumed": False},
        {"$set": {"consumed": True, "consumed_at": datetime.now(timezone.utc)}},
    )
    if not row:
        raise HTTPException(status_code=404, detail="Handoff already used or unknown")
    age = (datetime.now(timezone.utc) - row["created_at"].replace(tzinfo=timezone.utc)).total_seconds()
    if age > 300:
        raise HTTPException(status_code=410, detail="Handoff expired (5 min TTL)")
    user = await db.users.find_one({"id": row["user_id"]})
    if not user or not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="User inactive")

    resp = Response()
    _set_refresh_cookie(resp, row["refresh_cookie_value"])
    resp.body = json_dumps_body({
        "access_token": row["access_token"],
        "user": {
            "id": user["id"], "email": user["email"], "full_name": user.get("full_name"),
            "role": user.get("role"), "picture_url": user.get("picture_url"),
        },
    })
    resp.media_type = "application/json"
    resp.headers["content-length"] = str(len(resp.body))
    return resp
