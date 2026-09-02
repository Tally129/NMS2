# PostgreSQL Auth Migration — Status

_Last updated: Feb 28, 2026 (this session)_

## Where things stand

| Phase | Item | Status |
|---|---|---|
| 1 | Inventory + gap analysis | ✅ Done |
| 2 | SQLAlchemy models (12 tables) | ✅ Done |
| 3 | Alembic setup + initial migration + applied to local dev PG | ✅ Done |
| 4 | Repository layer | ✅ Done |
| 5 | `sessions.py` converted to PostgreSQL | ⏸ **Deferred** (see below) |
| 6 | `deps.py` converted to PostgreSQL | ⏸ **Deferred** (see below) |
| 7 | `routers/auth.py` (975 LOC) converted to PostgreSQL | ⏸ **Deferred** (see below) |
| 8 | `audit.py` converted to PostgreSQL | ⏸ **Deferred** (see below) |
| 9 | Staff-user migration script | ✅ Done (dry-run + idempotent + tested against 55 workforce users) |
| 10 | Foundation tests (12 passing) | ✅ Done |
| 11 | Mongo cleanup in the auth stack | ⏸ Depends on Phases 5–8 |

## Why Phases 5–8 were deferred in this session

The four auth files (`deps.py`, `sessions.py`, `audit.py`, `routers/auth.py`)
form a single tightly-coupled unit:

- `routers/auth.py` writes users/sessions to Mongo
- `sessions.py` reads/writes sessions + refresh tokens
- `deps.py` reads users/sessions for every authenticated request
- `audit.py` inserts audit rows (called by all of the above)

If any one of these switches to PostgreSQL while the others still use Mongo,
foreign keys break (a session pointing to a user that only exists in Mongo
can never satisfy `auth_user_sessions.user_id → auth_users.id`).

`routers/auth.py` is 975 lines with 15+ endpoints, transactional flows
(registration, login continuation, MFA setup/verify, OAuth), and cookie
handling. Converting it correctly requires the same session-carefully to
avoid regressing any current guarantee. This is the next PR.

The completed foundation is production-ready and can be committed and
reviewed independently. Nothing here changes runtime behavior — the app is
still 100% on Mongo for auth.

## What was delivered

### Files added

```
backend/postgres_models/user.py               (User + Client)
backend/postgres_models/user_session.py       (UserSession)
backend/postgres_models/refresh_token.py      (RefreshToken)
backend/postgres_models/login.py              (LoginHistory + LoginContinuation)
backend/postgres_models/password_reset.py     (PasswordResetAttempt + PasswordResetToken)
backend/postgres_models/oauth.py              (OAuthState + OAuthHandoff)
backend/postgres_models/audit.py              (AuditLog + SecurityEvent)
backend/postgres_models/__init__.py           (barrel re-export)

backend/repositories/__init__.py
backend/repositories/users.py
backend/repositories/user_sessions.py
backend/repositories/refresh_tokens.py
backend/repositories/audit.py
backend/repositories/login.py
backend/repositories/password_reset.py
backend/repositories/oauth.py

backend/alembic.ini
backend/alembic/env.py                        (rewritten to load Base.metadata)
backend/alembic/versions/2026_07_30_1925-557f2e586456_auth_stack_initial.py

backend/scripts/migrate_staff_users_to_postgres.py

backend/tests/test_pg_auth_foundation.py      (12 passing tests)

PG_MIGRATION_STATUS.md                        (this file)
```

### Packages added to `backend/requirements.txt`

- `sqlalchemy==2.0.51`
- `alembic==1.18.5`
- `psycopg==3.3.4` + `psycopg-binary==3.3.4`
- `asyncpg==0.31.0`
- (test) `pytest-asyncio` (already available via pytest ecosystem)

### Local dev database

- Server: PostgreSQL 15 (installed via `apt install postgresql-15`)
- Database: `nms_auth`
- User: `nms_dev` (password generated with `secrets.token_urlsafe(24)`;
  written only to `backend/.env`; never committed)
- Connection: `postgresql+psycopg://nms_dev:...@localhost:5432/nms_auth`

## Alembic revision

- Revision id: `557f2e586456`
- Filename: `backend/alembic/versions/2026_07_30_1925-557f2e586456_auth_stack_initial.py`
- Message: `auth stack initial`
- Result of `alembic upgrade head` locally: 13 tables created
  (12 auth tables + `alembic_version`).

## Test results

```
$ export $(grep DATABASE_URL backend/.env | xargs)
$ python -m pytest backend/tests/test_pg_auth_foundation.py -v
12 passed in 0.65s
```

All prior tests still pass (41/41 — Bedrock, features, staff handoffs).
Nothing in the running app changed behavior.

## Verifying no Mongo references in the PG-migrated code

```
$ grep -c "motor\|MongoDB" backend/postgres_db.py backend/postgres_models/*.py \
    backend/repositories/*.py backend/alembic/env.py
```

- `postgres_db.py`: 2 matches (comment only — describes the parallel
  migration state; no code path uses Motor)
- All other files: 0

The auth stack itself (`routers/auth.py`, `sessions.py`, `deps.py`,
`audit.py`) still references Mongo — that's Phase 5–8 work.

## Exact EC2 commands to run later

```bash
# 1. Add the same env var to production (source it from AWS Secrets Manager, NOT the repo):
export DATABASE_URL="postgresql+psycopg://<user>:<pw>@<rds-endpoint>:5432/<db>"

# 2. Install the new backend packages
pip install -r backend/requirements.txt

# 3. Apply the initial migration to RDS
cd backend && alembic upgrade head

# 4. Verify all 12 auth tables exist
psql "$DATABASE_URL" -c "\dt"

# 5. Dry-run the staff migration to see counts (never writes)
python -m scripts.migrate_staff_users_to_postgres --dry-run

# 6. Migrate workforce users
python -m scripts.migrate_staff_users_to_postgres

# 7. Confirm counts
psql "$DATABASE_URL" -c \
  "SELECT role, COUNT(*) FROM auth_users GROUP BY role ORDER BY role;"
```

**Do NOT cut over the running auth stack until Phases 5–8 land in a
subsequent PR.** After this PR is merged, `routers/auth.py`, `sessions.py`,
`deps.py`, and `audit.py` still read/write Mongo. Deploying this PR alone
is safe — it only adds parallel infrastructure.

## Assumptions and remaining risks

1. **Users won't be able to log in with the same session after cutover.** The
   staff migration script deliberately does NOT copy refresh tokens or
   active sessions — this forces re-login after cutover, which is a
   security-positive property.
2. **`Client` records with `user_id` are NOT migrated by this script.** Only
   users are migrated. `Client` records for portal patients live in the
   general Mongo `clients` collection and are still managed by the
   non-auth application code. A separate migration script may be needed
   if the client portal auth flow is later moved to PostgreSQL.
3. **JSONB metadata in `AuditLog`.** Old chain rows generated pre-migration
   use Mongo BSON. After Phase 8 cutover, `verify_audit_chain` operates
   only on PG rows; old Mongo audit rows become read-only history.
4. **PostgreSQL advisory lock (`pg_advisory_xact_lock`)** is transaction-
   scoped and released at COMMIT/ROLLBACK. It authoritatively serialises
   audit chain inserts across workers.
5. **Encrypted MFA secrets** are copied as ciphertext strings. The AES-GCM
   key in `auth_utils.py` must remain unchanged during migration or every
   TOTP will fail to decrypt.

## Ready-for-EC2 statement

The PostgreSQL foundation (models, migration, repositories, staff-user
migration script) is ready to be committed and applied to AWS RDS via
`alembic upgrade head`. **The auth stack itself is NOT yet ready for
PostgreSQL cutover** — Phases 5–8 must be completed in a subsequent PR
before flipping the runtime source of truth.
