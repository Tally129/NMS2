"""Authentication + Account routes — public entry point.

This file was 975 lines pre-refactor. During Session 1 of the PostgreSQL
migration it was split into topical submodules under
`routers/auth_impl/` to make the atomic runtime cutover (Session 2)
tractable. Behaviour is 100% preserved:

  * every route path, request/response schema, and cookie is unchanged
  * every helper still lives in the same-named function
  * MongoDB is still the auth persistence backend (Session 2 replaces it)

Server-wide code continues to `from routers import auth` and gets the same
FastAPI router registrations because importing this module imports the
`auth_impl` package, which in turn triggers each submodule's `@api.route`
decorators.
"""
from routers import auth_impl  # noqa: F401  side-effect import registers all routes

# Re-export the helpers that other backend modules import directly from
# `routers.auth` so those import paths keep working without touching the
# rest of the codebase.
from routers.auth_impl._common import (  # noqa: F401
    SESSION_TTL,
    RESET_TOKEN_TTL_MIN,
    _hipaa_mode,
    _email_hash,
    _hash_token,
    _create_session,
    _set_refresh_cookie,
    _clear_refresh_cookie,
    _revoke_all_sessions,
    _revoke_session,
)
