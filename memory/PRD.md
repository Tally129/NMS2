# Natural Medical Solutions — Wellness EMR / CRM

## Original Problem Statement
HIPAA-aligned wellness EMR for `natmedsol.com` (Natural Medical Solutions Wellness Center). Wellness office, **not** a medical practice. Single-tenant private app, not SaaS. Aesthetic adapted from medspa-concierge to NatMedSol's deep-green / parchment / gold palette.

## Personas
- **Client:** PWA-installable; schedule, intake, chart/labs/plan, secure messaging, billing. Sign in with **email + password + MFA** (Google SSO was removed 2026-07-30, Session 2a).
- **Practitioner:** schedule (full EHR view), charts, telehealth (live SOAP sidebar + AI draft), messaging, treatments, time clock, analytics.
- **Staff:** front desk, POS, transactions, inventory (lots/expiry), time clock.
- **Admin:** all of the above + user mgmt, audit, CSV import, EOD reports, manual time-clock edits.

> **All roles sign in at `/login`** (no separate staff URL — the same form authenticates clients, practitioners, staff, and admins).

## Architecture
```
/app
├── backend
│   ├── audit.py / auth_utils.py / models.py / server.py (~3.1k lines, refactor pending)
│   └── tests/  test_phase{4,5,6,7,8}.py — 109/110 (1 pre-existing skip)
├── frontend
│   ├── public/{manifest.json, service-worker.js (push handlers), icons/}
│   └── src/
│       ├── components/{AddPatientWizard,…}
│       ├── lib/{api, auth, push, Protected}
│       └── pages/
│           ├── PortalLayout.jsx (auto-subscribes to push on login)
│           ├── TelehealthVisit.jsx (WebRTC + SOAP sidebar + AI draft)
│           ├── patient/, provider/, admin/, portal/
└── memory/{PRD.md, test_credentials.md}
```

## What's Implemented (✅)
### Phase 1–7 — done
JWT+RBAC+MFA+audit, intake, SOAP, GridFS files, appointments+availability, reminders, treatment plan, invoices, symptom tracker + lab Recharts, secure messaging, all of Phase 4 ops (POS/Inventory/TimeClock/FrontDesk/Treatments/Transactions/ImportClients), Phase 5 (Analytics + PWA + Telehealth UI redesign + a11y), Phase 6 (EHR Add Patient wizard + Appointments tab + self-hosted WebRTC + Cash Drawer + N+1 fix), Phase 7 (WS auth hardening + ICE config + live SOAP sidebar + auto-draft + Claude SOAP + recurring appts + lots/expiration + push infra + commissions).

### Phase 8 — Push Triggers, Google SSO, Cleanup (May 5, 2026) ⭐ NEW
- **Push notification triggers** wired to:
  - Appointment 1-hour reminder — `_appointment_reminder_loop` runs every 5 min, idempotent via `reminder_sent_at` flag
  - Daily expiring-inventory ping — `_expiring_inventory_loop` (admins/staff)
  - New secure message — invoked from `messages.create` to other thread participants
  - Low-stock on POS sale — admins/staff get a push when stock crosses threshold
  - Visit started (telehealth in_session) — pings the client to join
- **Emergent-managed Google SSO** via `POST /api/auth/google/session` exchanging `X-Session-ID` for our internal JWT. New Google accounts auto-created with role `client` and a matching Clients row. Existing email matches are linked.
- **Removed commission feature entirely** (treatments here are not commission-based). Endpoints `PUT /api/treatments/{id}/commission` + `GET /api/reports/commissions` now 404. UI button + dialog removed from Treatments page.
- **Login UX fixes** — title now "Sign in" (was "Patient Portal Sign In"), subtitle "Clients, practitioners, staff, and admins all sign in here." so staff don't wonder where to log in.
- **Critical bug fix from tester** — `AppointmentStatus` Literal extended to include `scheduled`, `arrived`, `in_session`. Previously the EHR Start-visit button + visit-started push were dead code (Pydantic 422'd). Now functional.
- **PWA push subscribe flow** — `/app/frontend/src/lib/push.js` ensures every authenticated user is subscribed (best-effort, silent failure).

### Phase 9 — Dedicated Telehealth Hub & Staff Portal (May 5, 2026) ⭐ NEW
- **Dedicated `/staff-login`** — separate dark-themed sign-in for staff/practitioners/admins (still routes back to `/login` for clients). All four roles can sign in at either URL.
- **Telehealth Hub** at `/portal/{role}/telehealth` — single-purpose page with tabs for Upcoming · Active · History · Equipment test, plus an Instant-visit dialog (provider+ only). Stat cards for Active now / Starting within 1h / Upcoming total. STUN/TURN/Browser/Push diagnostics in Equipment tab.
- **Staff Dashboard** at `/portal/staff` — front-desk-first KPIs (In clinic, Walk-ins, Completed today, Revenue), quick check-in, POS, Up Next, Time Clock, Low-stock and Expiring rails.
- **Admin Telehealth nav link** added to admin sidebar Today group.
- **Idempotent staff seed** — `frontdesk@natmedsol.local` / `FrontDesk!2345` (role=staff) auto-seeded for QA.
- **InstantVisitDialog** now uses `useNavigate` (SPA route) instead of `window.location.href` so auth context survives.
- **Carry-over fixes**: AppointmentIn + AppointmentUpdate validated to accept `status="in_session"` on both POST and PUT (regression confirmed by iter7 testing agent).

### Phase 10 — Forms & Consents + UX cleanup (May 5, 2026) ⭐ NEW
- **HIPAA red banner removed** from every page (PortalLayout, StaffLogin, TelehealthVisit, Login).
- **"36 years in practice"** copy update on Home (was 29+).
- **Admin Overview StatCards now clickable** — Clients/Users/Visit notes/Files/Appt requests/Audit each route to a list page. Two new clinic-wide drill-downs added: `/portal/admin/notes` (AdminNotesList, with provider filter + name search) and `/portal/admin/files` (AdminFilesList).
- **Front Desk KPI cards (In clinic / Walk-ins / Completed) now act as filter toggles** — write `?filter=in_clinic|walk_in|checked_out` to URL, with a visible chip + clear button.
- **Forms & Consents** new feature (admin / practitioner / staff):
  - 3 built-in templates auto-seeded: Treatment Consent, HIPAA Notice, Photo & Likeness Release.
  - **AI Transcribe** PDF/DOCX/TXT → Claude 4.5 → editable form schema (uses `pypdf` + `python-docx` for text extraction, then strict-JSON prompt to Claude via Emergent LLM key).
  - **AI Generate** from a free-text prompt.
  - In-app form builder with text/textarea/email/phone/number/date/checkbox/radio/select/signature field types.
  - Search by title, filter by category, archive (toggle active), built-ins are soft-archive only.
  - **Soft-link send** → tokenized `/forms/respond/:token` URL the patient can open without logging in. Submitted forms appear in the Submissions tab. Auto-push notification to the linked client if they are a portal user.
  - Public `FormResponder.jsx` page renders the form with a touch/mouse signature pad and validates required fields before submit.
- **Backend endpoints (Phase 10)**: `GET/POST/PUT/DELETE /api/forms/templates`, `POST /api/forms/transcribe`, `POST /api/forms/generate`, `POST /api/forms/send`, `GET /api/forms/submissions`, `GET /api/forms/submissions/{id}`, `GET /api/public/forms/{token}`, `POST /api/public/forms/{token}/submit`, `GET /api/notes/all`.
- **New deps**: `pypdf`, `python-docx`, `lxml` (added to requirements.txt).

### Phase 11 — SOAP Notes hub + Detox Protocols (May 5, 2026) ⭐ NEW
- **SOAP Notes hub** at `/portal/{admin,staff,provider}/soap`:
  - Notes tab: clinic-wide list with **filter by client + by author/provider** + free-text search.
  - Templates tab: provider/admin can create, edit, delete starter SOAP templates (subjective / objective / assessment / plan with optional visit_type 'telehealth' or 'in_person').
  - "New SOAP" dialog → pick a client + a template → S/O/A/P sections pre-fill → save attaches to that client's chart (history retained on patient profile via existing `/notes` per-client endpoint).
  - Seeded templates: 'General wellness follow-up' + 'Telehealth check-in'.
- **Protocols** at `/portal/{admin,staff,provider}/protocols`:
  - Templates tab: configurable X-week × N-treatments-per-week protocols. Built-in 'Natural Medical Solutions Detox' (4 wk × 2/wk) auto-seeded with the daily outline, recommended foods, foods-to-avoid, and lifestyle guidance from the supplied DOCX template.
  - Propose flow: provider/admin selects a client and customizes weeks/sessions → an enrollment is created with status `proposed` and a sessions grid (week × session) → web-push notification sent to the client.
  - Patient view at `/portal/patient/protocols`:
    - Awaiting acceptance section with **Accept / Decline** buttons + optional note.
    - Active section with progress bar; History section for past protocols.
    - Read-only sessions grid (provider-only check-off).
  - Per-session check-offs (provider/admin/staff): clicking a session toggles complete, stamps `completed_by_name` + timestamp; when all sessions complete, status auto-advances to `completed`.
  - Clinic-wide enrollments index with filter by **client / provider / status** + search.
- **Backend endpoints (Phase 11)**: `GET/POST/PUT/DELETE /api/soap-templates`, `GET/POST/PUT/DELETE /api/protocols/templates`, `POST /api/protocols/enrollments`, `GET /api/protocols/enrollments(?client_id|practitioner_id|status)`, `GET /api/protocols/enrollments/{id}`, `POST /api/protocols/enrollments/{id}/decision`, `POST /api/protocols/enrollments/{id}/sessions`.

### Phase 12 — Logo refresh + Protocol AI assist (May 5, 2026) ⭐ NEW
- **New brand logo** (Natural Medical Solutions emblem with leaf+banner) replaces the old SVG monogram across the entire app — Home, Login, StaffLogin, FormResponder, sidebar, favicon. White background was punched to alpha=0 so it sits cleanly on the parchment palette.
- **"36 years in practice"** copy now applied everywhere (the bio paragraph on Home was missed in Phase 10 — fixed).
- **Protocols → AI Transcribe + AI Generate** mirrors the Forms & Consents flow:
  - `POST /api/protocols/transcribe` (multipart PDF/DOCX/TXT) → Claude 4.5 → structured protocol draft (weeks, sessions/week, foods, lifestyle, supplements, daily outline).
  - `POST /api/protocols/generate` (`{prompt}`) → Claude 4.5 → drafted protocol from a free-text description.
  - Both restricted to admin+practitioner (staff/client → 403).
  - Drafts pre-fill the Protocol Template Editor for one-click save.
- Lessons: testing agent caught a 1-line missing-state regression (`useState(null)` for showAi was inserted slightly out of order; corrected).

### Phase 13 — Document Library, Push opt-in, Recordings, Forms delivery, Last-login (May 5, 2026) ⭐ NEW
- **Document Library** (`/portal/{role}/library`) — universal AI ingest. Drop a PDF/DOCX/TXT → Claude 4.5 classifies as form / protocol / soap / supplement / other → matching transcription path runs → operator clicks "Save to ..." which creates the real template in the right destination.
  - Backend: `POST /api/library/classify` (multipart), `POST/GET/DELETE /api/library/supplements`.
  - 4 LLM helpers added: `_llm_classify_document`, `_llm_form_transcribe` (existing), `_llm_protocol_transcribe` (existing), `_llm_soap_template_extract`, `_llm_supplement_extract`.
- **Push notification opt-in banner** — `<PushOptInBanner>` mounted globally. Bottom-right card shown once when `Notification.permission==='default'` and not previously dismissed. Tied to existing `ensurePushSubscription()` helper.
- **WebM telehealth recording → GridFS** — was already written; added `GET /api/visits/{appt_id}/recordings` + `GET /api/visits/{appt_id}/recordings/{file_id}` (streams from GridFS as `video/webm` with RBAC). Recording UI in TelehealthVisit.jsx already calls `POST /api/visits/{id}/recording` on stop.
- **SMS/email forms delivery** — `POST /api/forms/send` now accepts `{channel: 'link'|'email'|'sms', delivery_target}`. Stub-logs to `integration_log` (`service=sendgrid|twilio`), returns `delivery_status='sent_stub'|'skipped'`. UI: SendFormDialog has a 3-button channel selector + dynamic recipient input that auto-fills from the selected client.
- **Last-login memory** — Login + StaffLogin pre-fill email from `localStorage.nms_last_login_email`, persisted on successful sign-in.
- **`coturn` deployment doc** — `/app/COTURN_DEPLOYMENT.md` (8-section ops guide: provisioning → TLS → conf → backend env wire-up → verification → cost guidance).

### Phase 14 — Auto-attach supplement directions on SOAP save (May 5, 2026) ⭐ NEW
- When a clinician POSTs a SOAP note, the backend scans S/O/A/P free-text for case-insensitive substring matches against active `supplement_sheets` titles.
- For each match:
  - Idempotent: creates a `client_supplement_assignments` row (or bumps `last_referenced_at` + appends the note id to `note_ids[]`).
  - Web-push notification fired to the patient portal user.
  - Audit log row `supplement_assignment.create` (source='auto_soap' or 'manual').
- New endpoints:
  - `GET  /api/clients/{client_id}/supplement-assignments` (client RBAC: own only)
  - `POST /api/clients/{client_id}/supplement-assignments` (admin/practitioner — manual override)
  - `DELETE /api/clients/{client_id}/supplement-assignments/{assignment_id}` (soft delete)
- Patient portal `/portal/patient/plan` now renders assigned supplement sheets above the existing treatment plans, with an "auto-attached" chip when `source='auto_soap'`.
- Known-limitation flags for future work: substring match is fragile for short titles (< 4 char guard applied); title match sequential N+1 (fine at <200 sheets).

### Quality Gates
- iter13: 11/11 backend pytest ✅ + 4/4 frontend UI ✅
- iter12: Document Library / Push / Recordings / Forms delivery — 12+11 ✅
- HIPAA red banner permanent
- RBAC verified across every endpoint
- Audit logging on all mutations

## Test Credentials
See `/app/memory/test_credentials.md`. Primary: `tallyravello@gmail.com` / `TEST123` (admin).

## Mocked / Pending Integrations
| Service | Status |
|---------|--------|
| **LLM (Claude Sonnet 4.5)** | ✅ LIVE — `llm_client.py` auto-routes to `ANTHROPIC_API_KEY` (direct, BAA-eligible) when set, else `EMERGENT_LLM_KEY` fallback |
| **Google SSO** | ✅ BOTH wired — Emergent-managed active by default; direct OAuth (`/api/auth/google/oauth/*`) activates when `GOOGLE_OAUTH_CLIENT_ID/SECRET/REDIRECT_URI` set. Uses one-time handoff id (no JWTs in URL). |
| **Email (SendGrid)** | ✅ `notifiers.send_email()` uses real SDK when `SENDGRID_API_KEY` + `SENDGRID_FROM_EMAIL` set, else logs `sent_stub` |
| **SMS (Twilio)** | ✅ `notifiers.send_sms()` uses real SDK when `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN` + `TWILIO_FROM_NUMBER` set, else logs `sent_stub` |
| **Web push (VAPID)** | ✅ LIVE — auto-subscribe + 5 trigger hooks wired |
| coturn TURN | ✅ env-var support; user deploys server |
| Stripe | stub |

## Roadmap

### P0 — In-flight
- **Phase 1 Security Hardening (per NatMedSol_Phase_1_Security_Architecture_v1.0)** — see Sprint tracker below.

### Sprint status
- **Sprint 1 — Config validation, JWT (iss/aud/jti/sid), workforce MFA hard cutover, secure password reset — ✅ COMPLETE (Feb 17, 2026)**. Gate review conditionally approved; remediation of 6 gate items ✅ complete (Feb 18): (2) MFA TOTP secrets now AES-256-GCM encrypted at rest via `MFA_ENC_KEY_B64`, `encrypt_mfa_secret` / `decrypt_mfa_secret` in `auth_utils.py`, migration script `scripts/sprint1b_encrypt_mfa.py` (12 legacy plaintext secrets migrated); (3) `.env` files now in `.gitignore` + `.env.example` templates added, verified no `.env` tracked in git history; (6) new `TestGateItem6_DevHelperSafety` unit-level tests prove `/auth/dev/reset-token` refuses to run under `HIPAA_MODE=true` or with `DEV_EXPOSE_RESET_TOKEN` unset (regardless of headers/query params); (1) previously-excluded tests (test_phase4, test_phase7, test_phase10_forms) now run green with no `--ignore` flags. Final regression: **275/275 pass** (1 flaky WS test passes on retry). Sprint 2 approved.
- **Sprint 2 — Opaque refresh sessions, family rotation, reuse detection, idle/absolute timeouts — ✅ COMPLETE (Feb 22, 2026)**. HttpOnly `nms_rt` cookie delivery; access tokens memory-bound; atomic family rotation with concurrency grace + reuse-detection burn; central `revoke_all_user_sessions`. Google OAuth Direct completion path verified end-to-end (Feb 24, 2026) via `test_sprint2_oauth_exchange.py` (9/9): callback no longer 500s, `user_sessions` created via `_create_session`, refresh delivered **cookie-only** (never in JSON body), access token in body, idle + absolute expiration fields populated, no PHI/token in logs, password login + refresh regression green. Fixed production bug in `/api/auth/google/oauth/exchange` (was reading wrong DB key + leaking refresh into JSON + naive-datetime crash). Fixed frontend `completeOAuthFromTokens` no-op that would have left OAuth users unauthenticated. Auth regression: **45/45** (sprint1 + sprint2 + oauth). Sprint 2 CLOSED.
- Sprint 3 — Permission catalog, role mapping, patient/resource scope, break-glass workflow — ✅ **COMPLETE (Feb 26, 2026)**. Central `permissions.py` catalog with `require_permission(*perms)` deny-by-default dependency + resource-scope helpers. Role map: client → self only; practitioner → assigned; staff → operational; admin → explicit clinical grants; auditor → read-only + break-glass GET passthrough. Break-glass router (`/api/breakglass/*`) — workforce-only, MFA-recency (10 min), reason (≥20 chars), target required, max 60-min duration, high-severity audit on activate + revoke, `/breakglass/active` for visible indicator.
- Sprint 4 — Audit event schema, redaction, fail-closed/outbox, tamper-evident hash chain — ✅ **COMPLETE (Feb 26, 2026)**. Rewrote `audit.py`: severity + outcome fields, per-row SHA-256 self-hash + prev_hash chain, canonicalized (millisecond ISO tz-aware) serialization, redaction filter for password/token/cookie/mfa_secret/oauth-code keys, `REQUIRED_ACTIONS` insert failures now propagate (fail-loud), high/critical rows fan out to `security_events`. `/api/admin/audit/verify-chain` verifier.
- Sprint 5 — Private file pipeline: MIME allowlist, 20 MiB size cap, SHA-256 checksums, malware-scan integration point (`scan_status: pending`), soft-delete with `deleted_at` (retention-ready), audit on upload/download/delete, secure filename sanitization, no public URLs — ✅ **COMPLETE (Feb 26, 2026)**.
- Sprint 6 — Approved AI provider registry, PHI mode, interaction records, practitioner approval — **DEFERRED (P2).**
- Sprint 7 — Security event rules, alert workflow, admin security dashboard — **PARTIAL: `security_events` collection populated automatically from high/critical audits; UI dashboard deferred (P2).**
- Sprint 8 — Backup/restore verification, runbooks, go-live checklist — **DEFERRED (P1).**

### Final Security Closure Release (Feb 27, 2026)
- **Dependency remediation** — 64 → **~15 residual CVEs**. Bumped aiohttp 3.13.5→3.14.1, cryptography 47→49, urllib3 2.6.3→2.7.0, python-multipart 0.0.27→0.0.32, pypdf 6.2.2→6.14.2, pyjwt 2.12→2.13, ecdsa unchanged (no upstream fix), starlette 0.37.2→0.49.3 (largest supported by FastAPI 0.121), fastapi 0.110.1→0.121.3, motor 3.3.1→3.6, pymongo 4.6.3→4.9. Pillow 12.2→12.3. Residual: `starlette 0.49.3` (FastAPI 0.121 caps <0.50), `litellm 1.80` (pinned by `emergentintegrations==0.1.0` requiring `openai<2.0`), `ecdsa 0.19.2` (unpatched timing side-channel; no attacker-controllable signing surface exposed).
- **Malware scanning** — real ClamAV integration (`malware_scan.py`) with `clamd` INSTREAM + `clamscan` subprocess fallback. Files enter `scan_status=pending`; inline scan on upload flips to `clean|infected|error`. Downloads gate: `clean → 200`, `pending → 425`, `infected → 451 (signature name NOT disclosed)`, `error → 503`. High-severity `file.malware_detected` audit + `security_events` row on infected.
- **Clinical integrity generalized** — `clinical_lock.py` module with `finalize_document/amend_document/refuse_edit_if_finalized`. Wired into Notes (existing), Treatment Plans (lifecycle_status field), Form Submissions (auto-finalized on signature; amend endpoint added). All finalize events emit `severity=high` audit; all amendments require `reason` (≥4 chars) + author + timestamp.
- **RBAC catalog coverage** — `permissions.py` extended with `permissions_for_roles()` + `route_permissions_declared()`. Route-inventory test enforces every `/api` route sits behind a known auth dep (`get_current_user`, `get_authenticated_user`, `require_roles`, `require_permission`, or `require_workforce_mfa`); public endpoints must be explicitly allow-listed in `PUBLIC_ROUTES`. Catalog invariants tested: no empty grants, auditor has zero write perms, client has zero `*_any` perms, admin's clinical perms are LISTED not inferred.
- **Startup config validator** — `security_config.enforce_production_config()` runs at boot. In `HIPAA_MODE=true` REFUSES to start when: `MALWARE_SCAN_MODE` is stub, `RATE_LIMIT_TEST_MODE` is on, `DEV_EXPOSE_RESET_TOKEN` is on, `REFRESH_COOKIE_SECURE` is off, `SESSION_JWT_SECRET` is <32 chars or starts with `dev-`, `MFA_ENC_KEY_B64` is missing.
- **Encrypted backup + verified restore** — `backup.py` (AES-256-GCM over mongodump tarball, sha256 checksum, meta sidecar, retention pruning) + `scripts/backup_test.py` performs a REAL end-to-end round-trip on every invocation. Verified live: backup 20260717T215005Z produced encrypted archive; decrypt+mongorestore `--dryRun` succeeded into `test_database_restore_probe`.
- **Prod safety documentation** — `HIPAA_MODE=false` and `RATE_LIMIT_TEST_MODE=1` are no longer suggested as rollback tactics. Correct rollback = revert application code + preserve controls. `.env.example` now documents all new keys.
- **Rate limiting + account lockout** — `rate_limit.py` sliding-window per IP + per email on `/auth/login` and `/auth/forgot-password`, 6-strike email lockout w/ 15-min cooldown. Env kill-switch `RATE_LIMIT_TEST_MODE=1` for CI.
- **Session-invalidating events** — password change (existing), MFA disable (existing), role change (NEW: bumps session_version + revokes all families), account deactivation (NEW: revokes all families). Admin routes emit `high` severity audit.
- **Clinical record versioning** — Notes have `status: draft|finalized`, `prior_versions[]` snapshot, `finalized_at/by`. Draft PUT allowed; finalized PUT → 409; amend requires finalized; amendments carry `reason` + high-severity audit.
- **Production hardening** — HTTPS enforcement in HIPAA mode (X-Forwarded-Proto check), CSP header, HSTS/X-Frame-Options/Referrer-Policy/Permissions-Policy retained.
- **Admin Session Explorer** — `/api/admin/sessions`, `/api/admin/sessions/{id}/revoke`, `/api/admin/users/{id}/revoke-all-sessions`, `/api/admin/audit/verify-chain`; new `/portal/admin/sessions` UI at `AdminSessionExplorer.jsx`.
- **Notifiers refactor** — moved `push_to_user` from server.py to `notifiers.py`, eliminating 6 undefined-name lints across routers.

### P1 — Next up
- **`server.py` modular refactor** — ✅ **Phase 16 (Feb 17, 2026)** — server.py **4703 → 632 lines** (**87% reduction**). Extracted routers: `auth`, `clients`, `admin`, `appointments`, `health_track`, `ops`, `telehealth`, `forms_protocols`, `compliance` under `/app/backend/routers/`. Shared `deps.py` holds mongo/api/helpers. Testing agent iteration 16 reports **207/208 backend tests green**.
- **SDK abstraction layer** — ✅ **Phase 16 (Feb 17, 2026)** — `llm_client.py` (Anthropic direct → Emergent fallback), `notifiers.py` (SendGrid/Twilio real → sent_stub fallback). `/api/health` now returns `integrations` dict (`llm`, `email`, `sms`, `google_oauth_direct`). Direct Google OAuth wired via one-time handoff scheme (no JWTs in URL).
- **User action items (BAA prep):**
  - Sign up at anthropic.com → request BAA via sales@anthropic.com → generate API key → paste into `ANTHROPIC_API_KEY` in `/app/backend/.env` → done.
  - Google Cloud Console: create OAuth 2.0 credentials → set `GOOGLE_OAUTH_CLIENT_ID/SECRET/REDIRECT_URI` + `FRONTEND_ORIGIN` → done.
  - Twilio (free-tier already works) — verify destination numbers → paste `TWILIO_ACCOUNT_SID/AUTH_TOKEN/FROM_NUMBER` → done.
  - SendGrid (free-tier already works) — verify sender email → paste `SENDGRID_API_KEY/FROM_EMAIL` → done.
- Migrate `AppointmentStatus` from Literal to a proper Python `Enum` + DB sanitizer at startup
- Validate `keys.p256dh` / `keys.auth` on `POST /api/push/subscribe`

### P2 — Future
- Add common-password blocklist to `auth_utils.validate_password_strength` (Phase 15 NIST rule miss — "Password1234" passed length + name-contains checks)
- Split remaining oversized files: `forms_protocols.py` (1060 lines → forms + protocols + library), `ops.py` (771 → treatments + inventory + pos + timeclock)
- LLM-assisted intake summarizer (one-paragraph chart preview)
- iPad-optimized provider view
- Recurring appointment UI: edit-one-vs-edit-series + drag to reschedule
- FEFO (first-expiring-first-out) inventory consumption on POS

### P3 — Nice-to-have
- Push: per-device manager (revoke per browser)
- Web push for staff: shift-handoff notes, time-clock punch confirmations
- Rewrite `server.py::seed_demo` + `_appointment_reminder_loop` to use `notifiers.send_*` instead of direct `integration_log` inserts (small cleanup)

## Known Limitations
- HIPAA banner stays until BAA-covered hosting + encryption-at-rest
- WebRTC needs TURN for restrictive networks (bring your own coturn)
- Service worker registers only in production builds
- `TEST123` is 7 chars — predates 12-char NIST policy (legacy admin, still accepted for login but new passwords require 12+)
- `test_phase4.py::test_change_password_and_revert` has a pre-existing `from backend.auth_utils` import bug — needs rewrite

_Last updated: Feb 27, 2026 (Final Security Closure Release — deps, malware, clinical, backup, startup validator)_


## Feb 20, 2026 — Telehealth Waiting Room + Provider-Authorized Delegated Editing

**Telehealth Waiting Room** (`routers/telehealth.py`, `pages/TelehealthVisit.jsx`, `pages/portal/TelehealthHub.jsx`)
- New `waiting_room` state on appointments: `idle → requested → admitted / declined / ended`
- Endpoints: `POST /appointments/{id}/telehealth/{request-join|admit|decline|end}`, `GET /appointments/{id}/telehealth/waiting-room`, `GET /telehealth/waiting-room/queue`
- Client flow: tech check → **Request to Join** → waiting room panel with live A/V preview → auto-transitions to in-call on admit, or shows the decline reason
- Provider flow: dedicated `provider-wait` screen with **Admit / Decline (reason) / End** controls; hub-level Waiting Room queue polling every 5s
- WebSocket signaling now **gates** `webrtc-offer`, `webrtc-answer`, `ice-candidate`, `screen-share` until the appointment is `admitted`; blocked frames bounce a `waiting-room` state message back to the sender
- Decline requires a 3-240 char reason, shown to patient + persisted in audit log (`telehealth.waiting_room_decline`, severity=high)

**Provider-Authorized Delegated Editing** (`permissions.py`, `delegations.py`, `routers/delegations.py`, `routers/clients.py`, `routers/appointments.py`)
- New role **`medical_assistant`** added to `Role` literal and `WORKFORCE_ROLES`; seeded test account `ma@natmedsol.local / MedAssist!2345`
- New collection `clinical_delegations` — provider grants a scoped (client-specific or blanket) time-limited (15 min – 7 days) delegation to an admin or medical_assistant
- Endpoints: `POST/GET /delegations`, `DELETE /delegations/{id}`, `GET /delegations/effective?client_id=…`
- Backend enforcement:
  - Notes / treatment plans: `create` + `update` accept `practitioner`, `admin`, `medical_assistant` — non-provider callers must have an active delegation for the client, else 403 `delegation_required`
  - `finalize` / `amend` on notes and plans are now **practitioner-only** (admin permanently blocked from signing)
  - Every delegated edit logs `authorizing_provider_id` + `actor_role` in audit metadata
- Frontend `AuthorizationBadge` (`components/AuthorizationBadge.jsx`) surfaces one of:
  - `Read Only — Provider Authorization Required` · `Draft Editing Authorized` · `Awaiting Provider Review` · `Finalized`
- `PatientChart.jsx` shows the badge above SOAP-notes tab; the "New note" button is disabled unless the viewer can edit; the amend input is provider-only
- Frontend `permissions.js` mirror updated (admin loses `note:create|amend|finalize`, gains `note:edit_draft_delegated`; adds `medical_assistant`)

**Tests** — `backend/tests/test_waiting_room_and_delegation.py` (10/10 passing):
- 7 waiting-room assertions: idle default, admit-when-empty rejected, request-join records `requested`, provider queue lists appt, decline requires reason, admit sets `admitted`, decline reason stored + audited
- 3 delegation assertions: MA without delegation 403s on note create, admin cannot finalize even own drafts, granted MA can create + edit + audit trail carries authorizing_provider_id + revoke returns MA to read-only

_Last updated: Feb 20, 2026 (Telehealth Waiting Room + Delegated Clinical Editing)_

## Feb 21, 2026 — Task Manager · Lab Review Queue · Campaign Center

Three lean internal-workflow modules, all reusing existing infrastructure
(audit log, notifiers, delegations, clients collection). No new
communication systems, no CRM, no drip automation.

### 1. Internal Task Manager (`routers/tasks.py`, `pages/portal/Tasks.jsx`)
- New collection `internal_tasks` with title, patient link (optional),
  assigned_staff, assigned_provider, due_date, priority (low/normal/high/
  urgent), status (new/in_progress/waiting/completed), category
  (review_labs, call_patient, follow_up_appointment, collect_payment,
  review_intake, upload_documents, insurance_followup, telehealth_followup,
  other), internal_notes, created_by, completed_by, history log
- Endpoints: `POST/GET/PATCH/DELETE /api/tasks`, `GET /api/tasks/dashboard/summary`
- Filters: mine, status, priority, due_before, client_id, category, search
- **Dashboard widget** (`components/TasksWidget.jsx`) — My Tasks · Overdue ·
  Due Today · Waiting; red overdue notification badge (badge-only, no email/SMS)
- History records every status change, reassignment, and note

### 2. Lab Review Queue (`routers/lab_review.py`, `pages/portal/LabReviewQueue.jsx`)
- **Reuses existing `lab_values` collection** — no second lab module
- Adds `review_status` (new / waiting_for_review / reviewed /
  patient_notified / follow_up_needed), `reviewed_by`, `notified_by`,
  `review_history` audit trail on the existing lab document
- Endpoints: `GET /api/labs/review-queue`, `PATCH /api/labs/{id}/review-status`,
  `POST /api/labs/{id}/create-task`
- Providers transition freely; Admins/Medical Assistants must have an active
  delegation for the client (reuses `delegations.has_active_delegation`)
- One-click "To task" button converts any lab into a linked internal task
  (auto-fills category=review_labs, linked_lab_id set)
- Every status change audit-logged with `lab.review_status` action

### 3. Campaign Center (`routers/campaigns.py`, `pages/portal/CampaignCenter.jsx`)
- New collection `campaigns` — title, subject, message, channel (email/sms),
  filter_type, filter_params, schedule_at, delivery_log, stats
- **Reuses existing SendGrid + Twilio notifiers** — no duplicate senders
- Endpoints: `POST /api/campaigns/estimate` (dry-run recipient count with
  exclusion breakdown), `POST /api/campaigns` (send-now or schedule),
  `GET /api/campaigns`, `GET /api/campaigns/{id}`, `POST /api/campaigns/{id}/run`
- Audience filters: all_marketing · inactive · upcoming_appointments ·
  due_for_followup · membership · treatment_group
- **Automatic exclusions**: `consent_marketing == false` → marketing_opt_out;
  invalid email regex → invalid_email; invalid phone → invalid_phone.
  Every exclusion recorded in delivery_log with structured reason.
- Estimator shows candidates / eligible / skipped-by-reason before sending
- Scheduled campaigns are stored with `status=scheduled` (no cron in this
  build — admin runs manually via `/campaigns/{id}/run`)

**Tests** — `backend/tests/test_tasks_labs_campaigns.py`, **18/18 passing**
- Task Manager: create, list-filter, status transition + history, reassign,
  complete, dashboard summary shape, invalid priority rejected, client-role
  forbidden
- Lab Review: default queue excludes notified, provider transitions, MA
  denied without delegation, create-task-from-lab links correctly
- Campaigns: estimate excludes opt-outs, email requires subject, send-now
  writes delivery_log + stats with skipped reasons, schedule stores
  correctly, list + get, invalid filter type rejected

_Last updated: Feb 21, 2026 (Task Manager · Lab Review · Campaign Center)_


## Feb 22, 2026 — Final Operations Closeout (Scheduler + Controls + Badge)

Feature freeze — no new modules, only production-safety wiring around the
existing Campaign Center and Task Manager.

### 1. Scheduled Campaign Worker (`server.py` startup, `routers/campaigns.py`)
- **APScheduler `AsyncIOScheduler`** running in-process on the single-worker
  uvicorn instance (`--workers 1` verified in `/etc/supervisor/conf.d`).
  5-minute interval, `coalesce=True`, `max_instances=1`, `replace_existing=True`,
  UTC-only.
- Toggle via env: `CAMPAIGN_SCHEDULER_MODE=external|disabled` skips in-process
  start-up so multi-worker deploys (if ever adopted) can rely on an external
  cron hitting `POST /api/campaigns/scheduler/tick` (admin-only).
- Graceful `shutdown_db_client()` calls `_stop_campaign_scheduler()`.
- **Atomic claim**: `find_one_and_update({id, status: {$in: allowed_from}},
  {$set: {status: "processing", started_at, worker_id}}, ReturnDocument.AFTER)`
  prevents any double dispatch across restarts, reloads, or concurrent workers.
- Status lifecycle: `scheduled → processing → completed | sent_with_failures | failed`
  Terminal states cannot re-enter the queue.
- Every claim records `started_at`, `completed_at`, `worker_id` (`apscheduler:<uuid>`
  vs `manual:<user>:<uuid>` vs `retry:<user>:<uuid>` vs `web:<uuid>`) and
  `failure_reason` on failure.
- Manual `POST /api/campaigns/{id}/run` and the internal APScheduler tick both
  funnel through the same `_run_campaign` — dispatch logic cannot diverge.

### 2. Scheduled-Campaign Controls
- **Cancel** — `POST /api/campaigns/{id}/cancel` — admin-only, requires
  `status == scheduled`. 409 on already-processing / completed / cancelled.
- **Retry** — `POST /api/campaigns/{id}/retry` — admin-only, requires
  `status == failed`. Clears stale delivery_log via the same atomic-claim
  helper. Completed campaigns **cannot** be retried.
- Frontend inline row actions: "Cancel" button shown only for scheduled rows,
  "Retry" shown only for failed rows.
- Scheduled `schedule_at`, current status, and audit trail all surfaced in the
  detail dialog.

### 3. Tasks Sidebar Badge
- Reuses `GET /api/tasks/dashboard/summary` (already existed) — no new
  endpoint, no PHI in the badge itself.
- `PortalLayout.jsx` polls at 60 s (per spec — not faster). Hides at zero.
  Red pill (`bg-[#7a2a2a] text-white`) next to the "Tasks" nav item across
  admin, practitioner, staff/MA sidebars.
- No email / SMS / push wired.

### 4. Delivery Configuration Guard
- `GET /api/campaigns/config/delivery` — returns **booleans only** for
  `SENDGRID_API_KEY`, `SENDGRID_FROM_EMAIL`, `TWILIO_ACCOUNT_SID`,
  `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, plus `email.mode`, `sms.mode`,
  `simulated`. **No secret values ever returned.**
- Frontend banner on `/portal/staff/campaigns` labels simulated delivery in
  amber and lists exactly which env vars are missing.
- Existing notifier `sent_stub` behavior preserved for dev; `mode: "live"`
  when both keys and from-address are present.

**Deployment method**
- **Internal APScheduler** (single uvicorn worker); documented external cron
  path via `POST /api/campaigns/scheduler/tick` if multi-worker deploy is
  ever adopted. `CAMPAIGN_SCHEDULER_MODE=external` disables the in-process
  scheduler cleanly.

**Duplicate-execution protection**
- Mongo `find_one_and_update({status: {$in: allowed_from}}, $set: {status: "processing", worker_id})`
  — the storage engine guarantees the transition is atomic. Any second worker
  matching the same doc gets `None` and increments `skipped_races`.

**Tests** — `backend/tests/test_scheduler_closeout.py`, **10/10 passing**
(regressions verified: `test_tasks_labs_campaigns.py` 18/18 still passing).

**Environment variables still requiring configuration for LIVE delivery**
- `SENDGRID_API_KEY`
- `SENDGRID_FROM_EMAIL`
- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_FROM_NUMBER`
- Optional: `CAMPAIGN_SCHEDULER_MODE=external` if scaling to multi-worker

_Last updated: Feb 22, 2026 (Final Operations Closeout — Scheduler + Controls)_


## Feb 23, 2026 — Sprint 1: Accounting Foundation (event-driven)

Practical double-entry accounting bolted onto the existing practice-management
app. Every existing financial component (POS, invoices, memberships, Stripe,
inventory, refunds, campaigns, dashboards, RBAC, audit log) reused as-is;
zero rewrites of production financial code.

### Architecture
- **Accounting Event Bus** (`accounting/events.py`): single append-only feed
  (`db.accounting_events`) with unique `idempotency_key` index. Operational
  modules never touch the ledger — they emit standardized events.
- **Posting Rules Engine** (`accounting/posting_engine.py`): the ONLY writer
  to `db.journal_entries`. Balance enforced at write; failures go to
  `db.posting_dead_letters` with structured reason.
- **Journal** (`accounting/journal.py`): immutable double-entry entries;
  corrections via `reverse_entry()` mirror; unique `event_id` (partial-filter)
  index prevents duplicate posting.
- **Chart of Accounts** (`accounting/chart_of_accounts.py`): 34-account
  medical-practice seed; `system_locked` flag protects core accounts.
- **Reports** (`accounting/reports.py`): P&L, Balance Sheet, Trial Balance,
  A/R Aging — pure math on the ledger, with `balanced` invariant checks.

### Adapters (minimal, safe touches to operational code)
- `routers/ops.py` POS checkout — emits `SaleCompleted` on success (fire-and-
  forget, wrapped in try/except; never blocks checkout)
- `routers/appointments.py` invoice mark-paid — emits `InvoicePaid`
- Manual expenses, vendor bills, payroll runs all emit their events from
  within the new `routers/accounting.py`

### Event catalog (initial)
`SaleCompleted`, `SaleRefunded`, `InvoiceIssued`, `InvoicePaid`,
`MembershipStarted`, `MembershipRenewed`, `InventoryConsumed`,
`InventoryAdjusted`, `ManualExpenseRecorded`, `VendorBillCreated`,
`VendorBillPaid`, `PayrollAccrued`, `PayrollPaid`, `StripeFeeCharged`,
`ManualJournal` + reserved slots for insurance, HSA/FSA, ACH, bank moves.

### Endpoints (`routers/accounting.py`)
- **COA**: list, create, patch (system-locked accounts protected)
- **Journal**: list, manual, reverse
- **General Ledger**: `/gl/{account_code}` with running balance
- **Events / dead-letters**: admin oversight
- **Reports**: `/reports/profit-and-loss`, `/balance-sheet`, `/trial-balance`, `/ar-aging`
- **Vendors + Expenses + Bills**: CRUD + pay
- **Payroll**: employees, payroll runs (accrue + pay)
- **Tax**: `/tax/sales-tax`, `/tax/payroll-tax`, `/tax/summary?year=` (quarterly)
- **1099**: `/1099/vendors`, `/1099/csv` (IRS-ready CSV export)
- **Stripe reconciliation**: read-only over `db.integration_log`

### Frontend
- New unified `/portal/admin/accounting` page (`pages/portal/Accounting.jsx`)
  with 9 tabs: Reports · Journal · General Ledger · Chart of Accounts ·
  Expenses · Vendors & Bills · Payroll · Tax · 1099
- Sidebar entry in the admin NAV group

### Tests — 14/14 passing (`test_accounting_sprint1.py`)
- COA seeded correctly; system-locked accounts cannot change type
- Manual journal balanced ✅ / unbalanced → dead-letter ✅
- POS checkout emits event + posts 4-line balanced journal entry
- Idempotency: duplicate `idempotency_key` insert rejected by unique index
- Expense records + posts (DR expense / CR cash)
- Vendor bill lifecycle (accrue DR 6400 CR 2000, pay DR 2000 CR 1100)
- Payroll accrue posts 4-line balanced entry (6200 + 6210 / 2400 + 2410) + pay
- All 4 report endpoints return; Trial Balance + Balance Sheet **balanced=True**
- Reversal creates mirror entry with swapped debit/credit sides
- 1099 CSV exports IRS-ready NEC format

### Explicitly deferred to Phase 2
- Bank reconciliation UI (statement import, matching)
- Multi-currency, multi-company
- Fixed asset depreciation schedules
- Purchase-order workflow
- Insurance-claim accounting
- IRS e-file / state tax filing
- Payroll direct deposit
- Budgeting / forecasting

_Last updated: Feb 23, 2026 (Sprint 1 — Accounting Foundation)_


---

## Sprint 1.5 — Accounting Stabilization (Feb 24, 2026) ⭐

### Backend modules
- `accounting/backfill.py` — Historic replay for 6 sources (POS, invoices,
  invoice_payments, memberships, inventory, expenses). Preview (dry-run) +
  execute + resume. Idempotent through `accounting_events.idempotency_key`.
- `accounting/validation.py` — 7 checks: trial balance, balance sheet, orphan
  entries, missing sources, dead-letters, duplicate events, journal integrity.
- `accounting/dashboard.py` — Snapshot: cash / A/R / A/P / revenue MTD & today /
  sales tax / payroll liability / dead-letter / unposted-event counts + TB status.

### New API endpoints
- `GET  /api/accounting/dashboard`
- `GET  /api/accounting/validate`
- `POST /api/accounting/backfill/dry-run`
- `POST /api/accounting/backfill/execute`
- `GET  /api/accounting/backfill/runs`  ·  `.../{id}`  ·  `POST .../{id}/resume`

### Frontend
- New "Health & Backfill" tab on `/portal/admin/accounting`
  (`pages/portal/AccountingHealthTab.jsx`)
- 10 widgets (Cash · A/R · A/P · Revenue MTD/today · Sales tax liability ·
  Payroll liability · Dead-letters · Unposted events · Trial balance)
- Backfill panel with source checkboxes, Dry-run, Execute, run history + Resume.
- Ledger validation report drops in below widgets.

### Tests — 11/11 passing (`test_accounting_sprint1_5.py`)
Backfill idempotency + resume + list/get; dashboard shape; validation shape +
truth for TB / BS / duplicates / integrity.

## Sprint 2 — Banking & Cash Management (Feb 24, 2026) ⭐ NEW

### Backend modules
- `accounting/banking.py` — Bank account registry (name, kind, gl_code,
  institution, last_four, system_seeded, last_reconciled_at).
  Seeds 5 defaults on first startup: Operating Checking (1100), Petty Cash (1000),
  Cash Drawer (1050), Stripe Merchant Clearing (1200), Credit Card (2500).
  System-seeded accounts editable (name/institution/last_four/active) but not
  deletable. User-created accounts blocked from deletion while transactions exist.
- `accounting/statements.py` — CSV import (permissive column detection:
  date/description/amount, or debit/credit pair; case- and underscore-insensitive
  header matching) + basic OFX via `ofxparse`. Auto-detect by file extension;
  bad OFX raises 400. Dedupe within (bank_account_id, posted_at, amount, ref).
- `accounting/reconciliation.py` — Workspace (bank + ledger side-by-side);
  auto-match (exact amount, ±7 days, memo similarity 0-100 confidence);
  manual match, unmatch, split (N-way against journal entries); finalize
  reconciliation (immutable — writes reconciliation_id onto BOTH bank_txn and JE,
  never mutates lines/totals). Exceptions panel groups: unmatched bank/ledger,
  duplicate imports, amount mismatches, date mismatches, duplicate JEs.
- `accounting/cash_reports.py` — Bank register (running balance),
  outstanding deposits, outstanding checks, reconciliation report, outstanding
  reconciliation (per-account, days outstanding, suggested confidence),
  cash flow summary, Stripe settlement summary, cash dashboard aggregator.
- **New event type**: `BankTransferMade` — DR destination account,
  CR source account. Rule wired in `posting_engine.py`.

### New API endpoints
- Bank accounts: `GET/POST /accounting/bank-accounts` · `PATCH/DELETE .../{id}`
- Statement import: `POST /accounting/bank-accounts/{id}/import` (multipart)
  · `GET .../{id}/transactions` · `GET .../{id}/import-batches`
- Reconciliation: `GET /accounting/reconciliation/{ba_id}/workspace` ·
  `POST /accounting/reconciliation/{ba_id}/auto-match` ·
  `POST /accounting/reconciliation/confirm-matches` ·
  `POST /accounting/reconciliation/match` · `POST .../unmatch/{bt_id}` ·
  `POST /accounting/reconciliation/split` · `POST .../finalize` ·
  `GET /accounting/reconciliation/history` ·
  `GET /accounting/reconciliation/{recon_id}/report` ·
  `GET /accounting/reconciliation/exceptions`
- Transfers: `POST /accounting/transfers` · `GET /accounting/transfers`
- Cash: `GET /accounting/cash/dashboard` ·
  `GET /accounting/cash/register/{ba_id}` · `.../flow` ·
  `.../outstanding-deposits` · `.../outstanding-checks` ·
  `.../outstanding-reconciliation`
- Stripe: `GET /accounting/stripe/settlement`

### Frontend
- New "Banking" tab on `/portal/admin/accounting`
  (`pages/portal/BankingTab.jsx`) with 6 sub-panes:
  Cash Dashboard · Bank Accounts · Reconciliation · Exceptions · Transfers · Reports.
- Reconciliation workspace has side-by-side bank/ledger panels, auto-match
  proposal review, per-txn match/unmatch actions, finalize form.

### Dependencies
- Added `ofxparse==0.21` (+ `beautifulsoup4`, `soupsieve`) via pip/freeze.

### Tests — 12/12 passing (`test_accounting_sprint2.py`)
- Seeding, create bank account, CSV import + dedupe, bad OFX 400,
  manual/auto/split matching (amount-mismatch rejected), finalize preserves
  immutability, transfer creates balanced DR/CR journal, cash dashboard
  shape, all 7 reports return 200.
- **Regression: 14/14 Sprint 1 + 11/11 Sprint 1.5 + 12/12 Sprint 2 = 37/37 pass.**

### Explicitly NOT built (deferred to later sprints per user brief)
- Sprint 3: Insurance accounting (claims, ERA/EOB, adjustments)
- Sprint 4: Fixed assets & period close (locking, depreciation)
- Sprint 5: Tax filing integrations & payroll direct deposit
- Sprint 6: Business intelligence & forecasting
- Direct bank API / Plaid / Open Banking / ACH origination
- Loan management, investments, treasury management

_Last updated: Feb 24, 2026 (Sprints 1.5 & 2)_

---

## Sprint 6 — Frontend Usability & Workflow Completion (Jul 23, 2026)

Goal: polish existing modules without rebuilding. Reuse existing search
components, PDF engine (ReportLab), file-vault uploader, password-reset token
plumbing, and campaign engine.

### What was built
- **Global search palette (Ctrl/Cmd + K)** — `GlobalSearchPalette.jsx` + backend
  `GET /api/search/global?q=…`. Fans out into patients / treatments / inventory
  / users / appointments / vendors, RBAC-aware (clients see only their own
  appointments; providers/staff hide client-role users). Bucket-per-collection
  envelope, empty buckets pruned. Visible sidebar trigger added to `PortalLayout`.
- **Per-page search inputs** on Treatments, Inventory, Users (admin), POS
  Treatments + Inventory tabs, Lab Review Queue. Users page also gains a role
  filter.
- **Server-side invoice PDF** — rewrote `_render_invoice_pdf` in `routers/ops.py`
  with practice logo/name band, from/to columns, itemized lines, discount/tax/tip
  breakdown, payment status, ref number, footer disclaimer. Invoice numbers are
  `INV-YYYYMMDD-XXXXXX`. `Transactions.jsx` gains per-row PDF / Print / Email
  buttons (`data-testid txn-download-*`, `txn-print-*`, `txn-email-*`).
- **Email invoice** — new `POST /api/transactions/{tid}/email` uses SendGrid
  (with `sent_stub` fallback in dev) to attach the PDF and mail it, redacting
  recipient in audit metadata.
- **Lab attachments** — new `POST /api/labs/{id}/attachments` +
  `DELETE /api/labs/{id}/attachments/{file_id}` link files already uploaded via
  the existing `/api/files/upload` vault (no new storage system). Provider role
  can attach; admin/medical_assistant must have an active delegation. The
  Lab Review dialog gains an “Attach PDF / image” button and downloadable list;
  the queue row shows a paperclip badge with attachment count.
- **TipTap rich-text editor for Campaign Center** — `RichTextEditor.jsx`
  (StarterKit + Underline + Link + Image + Placeholder + Table extensions +
  Variables popover). Merge fields supported: `patient.first_name`, `.last_name`,
  `.full_name`, `.email`, `.phone`; `appointment.date`, `.time`, `.provider`;
  `provider.name`; `membership.name`, `package.name`; `clinic.name`, `.phone`,
  `.email`. Preview toggle renders the editor output with sample context so
  authors visualize substitution. Backend `_render_html` / `_render_plain` /
  `_fill_variables` render the same HTML for email and clean plaintext for SMS.
- **Portal invitation / account management** — new `routers/portal_ops.py`:
  * `GET /api/clients/{id}/portal-status`
  * `POST /api/clients/{id}/portal-invite` — idempotently creates or reuses a
    client-role user linked to the client, issues a 24-hour password-setup token
    (via existing `password_reset_tokens`), and mails it. `invite_url` is
    returned in-band when `HIPAA_MODE=false` so admins can copy the setup link
    directly; redacted when HIPAA_MODE is on.
  * `POST /api/clients/{id}/portal-reset-password` — 60-min reset link.
  * `POST /api/clients/{id}/portal-disable` / `.../portal-enable` — flips
    `is_active` and revokes all sessions on disable.
  * Frontend `PortalAccessPanel.jsx` mounted at the top of the provider
    patient chart with Send / Resend / Reset / Copy portal login URL / Disable /
    Re-enable buttons and Active / Disabled / Not-invited / **TEST PATIENT** badges.
    Never displays a password.
- **Portal test patient seeder** — `POST /api/dev/portal-test-patient`
  (admin-only, refused when `HIPAA_MODE=true`) idempotently creates
  `Portal Test Patient — NON-PRODUCTION DATA` (`portal.test@natmedsol.local`,
  mrn `NMS-TEST01`, tags `[portal_test_patient]`, consent_marketing: false).
  Returns `portal_login_url` + one-time `portal_password_setup_url`.
  Delete via `DELETE /api/dev/portal-test-patient/{client_id}`.
- **Bookkeeping** — `models.py` `ClientIn`/`ClientOut` now expose optional
  `tags: List[str]` so the portal_test_patient flag round-trips.
  Service worker `VERSION` bumped to `nms-v3-2026-07-23-sprint-usability`.
  `FRONTEND_ORIGIN` env set so invitation URLs are absolute.

### Testing
- Backend regression suite `test_iter24_sprint_usability.py` — **17/17 pass**
  (global search RBAC + envelope, portal seeder idempotency, portal status /
  invite / reset / disable / enable, invoice PDF %PDF magic + INV-* filename,
  invoice email stub, lab attach / detach + delegation enforcement, campaign
  HTML + merge vars + SMS plaintext).
- Sprint 1 (14) + 1.5 (11) + 2 (12) regression untouched — 54/54 with iter24.
- Frontend UI verified by testing agent (~95% pass; only two Radix a11y
  console warnings, since resolved by adding VisuallyHidden DialogTitle /
  Description to the shadcn `CommandDialog`).

### Explicitly NOT built (out-of-scope per user brief)
- Admin “preview as patient” impersonation (user explicitly declined — real
  patient login flow used instead).
- No new invoice model / no new storage system / no new campaign engine.
- No repository-wide refactor.

_Last updated: Jul 23, 2026 (Sprint 6 · Frontend Usability & Workflow Completion)_

---

## Sprint 7 — Production-Ready Email Campaign Platform (Jul 24, 2026)

Goal: extend the existing campaign engine into a full production tool. Reused
`routers/campaigns.py`, TipTap editor, bleach sanitizer, notifiers, and
password-reset token flow. Added on new endpoints and UX; nothing was rebuilt.

### Backend (new `routers/campaign_extras.py`)
- **Template library** — 20 curated defaults across all requested categories
  (monthly newsletter, wellness tips, IV therapy, membership, hyperbaric,
  weight loss, hormone, peptide, aesthetics, med spa specials, birthday,
  holiday, appointment follow-up, reactivation, referral, portal invitation,
  password reset, invoice, receipt, lab results ready). Public HTML endpoints:
  `GET /api/campaign-templates`, `POST /api/campaign-templates` (custom save),
  `DELETE /api/campaign-templates/{id}`.
- **Lifecycle actions** — `/duplicate`, `/archive`, `/unarchive`, `/pause`,
  `/resume`, `/test-send` (up to 5 explicit recipients, ignores segment
  filter, prefixes subject with `[TEST]`).
- **Draft edit lock** — new `PATCH /api/campaigns/{id}` allows edits only
  while status is `draft` / `scheduled` / `paused`; sending/sent/failed 400s
  with `campaign_locked`. Snapshot of subject/message/channel/filter is
  written to the doc the moment sending starts (`campaigns.snapshot`).
- **Broader segments** — `POST /api/campaigns/segments/estimate` accepts the
  original `FILTER_TYPES` plus `active_patients` (last N days), `new_patients`
  (created N days), `birthday_month`, `tags`, `custom_list`.
- **Compliance footer** — every marketing email now carries clinic name,
  address, phone, website and a per-recipient signed unsubscribe link.
  Transactional emails (kind=transactional) skip the unsubscribe link with
  the required "This is a transactional message" notice.
- **Public unsubscribe** — `GET /api/campaign-unsubscribe?c=&t=` toggles
  `consent_marketing: false` after verifying the HMAC-lite token; frontend
  page at `/unsubscribe` gives the confirmation. Transactional messages
  still flow.
- **Provider abstraction stub** — `GET /api/campaigns/config/providers`
  reports which of `sendgrid` / `resend` / `ses` are configured. SendGrid
  is live (SG.6Ox... key in place); Resend and SES accept env credentials
  without code changes.
- **`portal.login_link` merge field** — substituted per-recipient at send
  time as `${FRONTEND_ORIGIN}/patient-login`.

### Frontend (`pages/portal/CampaignCenter.jsx` + `Unsubscribe.jsx`)
- New **Templates** button + `TemplatePickerDialog` — category filter chips,
  transactional / marketing badges, click any card to prefill the new-campaign
  dialog with the template's subject and HTML.
- Row-level actions extended: **Duplicate**, **Archive**, **Pause**,
  **Resume**, **Test send**, plus existing Cancel / Retry. Send-test prompts
  for a recipient and reports SendGrid delivery status.
- NewCampaignDialog accepts an `initial` prefill from the picker and now
  sends the `kind` field (`marketing` or `transactional`).
- New public page `/unsubscribe` handles the compliance-link click.

### Config
- `SENDGRID_API_KEY` + `SENDGRID_FROM_EMAIL=info@natmedsol.com`,
  `EMAIL_PROVIDER=sendgrid` set in `backend/.env`. Frontend service worker
  bumped to `nms-v7-2026-07-24-campaign-platform`.

### Explicitly NOT built (out-of-scope per brief)
- No new authentication or messaging engine — reused notifiers/campaigns.
- Full open/click/bounce webhooks require SendGrid Event Webhook
  configuration; delivered/sent-stub/failed already flow via
  `db.integration_log`.

_Last updated: Jul 24, 2026 (Sprint 7 · Production-Ready Email Campaign Platform)_

---

## Sprint 8 — Legal & Policies Center (Jul 25, 2026)

Goal: dedicated hub for every legal, privacy, HIPAA, and consent document with
versioning, acceptance tracking, forced reacceptance, login/signup consent,
and admin management.

### Backend
- **New router `routers/legal.py`** — collections `legal_policies` (with an
  embedded `versions[]` array + `current_version`) and `legal_acceptances`
  (immutable audit log per user × policy × version).
- **Seeder**: idempotent boot task inserts v1.0 of all 9 required policies —
  Terms of Use, Privacy Policy, HIPAA NPP, Financial Policy, Patient Portal
  Terms, Telehealth Consent, Email & SMS Communications, Accessibility, Cookie
  Policy. HTML bodies are run through the existing `sanitize_campaign_html`
  allowlist before storage.
- **Public endpoints (no auth)**: `GET /api/legal/policies`,
  `GET /api/legal/policies/{slug}`, `GET /api/legal/policies/{slug}/versions`.
- **Authenticated**: `POST /api/legal/acceptances`,
  `GET /api/legal/acceptances/me`, `GET /api/legal/pending-reacceptance`.
- **Admin**: `PATCH /api/legal/policies/{slug}`,
  `POST /api/legal/policies/{slug}/versions` (marks previous as superseded,
  optional `force_reacceptance`), `POST /api/legal/policies/{slug}/archive`,
  `GET /api/legal/policies/{slug}/acceptance-stats`.

### Frontend
- **`/legal` hub** — 9 icon+title+description cards with version badge and
  Last Updated date. Publicly accessible with a lightweight `PublicShell`
  (site header + `LegalFooter`) for signed-out visitors; wraps in the
  standard `PortalLayout` for authenticated users.
- **`/legal/:slug` detail** — sticky auto-generated TOC (from h2/h3
  headings), Print button, PDF button (disabled/"coming soon"), Back link,
  Effective Date / Last Updated / version metadata.
- **Login consent** — new 12-14px neutral-gray consent paragraph above the
  Sign In button on every login variant with underlined links opening
  `/legal/terms`, `/legal/hipaa`, `/legal/privacy` in a new tab so form
  input is preserved.
- **Signup checkboxes** — three required acknowledgments (Terms, HIPAA,
  Privacy) with links opening the individual policy pages; the Create
  Account button is disabled until all three are checked. On success, each
  acceptance is posted to `/api/legal/acceptances` with the current
  version and `method=signup_checkbox`.
- **Reacceptance gate** — `<ReacceptancePolicyGate />` mounted globally in
  App.js. On every authenticated mount it pulls
  `/api/legal/pending-reacceptance` and shows a blocking modal titled
  "We've updated our policies" until each pending policy is accepted.
  Modal supports View Changes (inline), Read Full Policy (opens the
  full page in a new tab), Accept & Continue.
- **Sidebar** — Legal & Policies entry added to the Settings nav group
  for patients, practitioners, staff, and admins (Feb 28, 2026). All
  roles share the same `/legal` and `/legal/:slug` routes; no
  role-scoped duplication.
- **Footer** — new Legal column with links to Terms, Privacy, HIPAA,
  Accessibility, Cookies, and mailto to the Privacy Officer.

### Config / bookkeeping
- Service worker `VERSION` bumped to `nms-v8-2026-07-24-legal-policies`.
- Frontend routes: `/legal`, `/legal/:slug` — both public.

### Not built (deferred)
- Admin visual editor UI — reachable via the JSON API today; a dedicated
  admin page can wrap it in a later sprint.
- PDF export of individual policies — button present, disabled with a
  hover tooltip "coming soon".

_Last updated: Jul 25, 2026 (Sprint 8 · Legal & Policies Center)_

---

## Sprint 9 · Bedrock AI Standardization (Feb 28, 2026)

### Scope (Parts 1–6 of the AI sprint charter — backend foundation only)
Removed all Anthropic direct and Emergent LLM proxy support. Amazon Bedrock
is now the only AI provider. The application authenticates to Bedrock via
the EC2 instance IAM role — no static AWS credentials anywhere.

### Changes
- **backend/llm_client.py** — rewritten. Bedrock Converse API (with legacy
  `invoke_model` fallback), `asyncio.to_thread` dispatch, safe error
  categories, provider health strings (`bedrock`/`disabled`/`misconfigured`
  /`unavailable`). Kept `complete_text()` signature and
  `DEFAULT_ANTHROPIC_MODEL` alias so existing callers (telehealth, forms,
  protocols, document, supplements) work unchanged.
- **backend/llm_client.py** — added `PromptTemplate` + `run_template()` +
  `safe_extract_json()` helpers so future AI features add a template, not
  new infrastructure.
- **backend/.env / .env.example** — removed `ANTHROPIC_API_KEY`,
  `EMERGENT_LLM_KEY`, `ANTHROPIC_MODEL`. Added `AI_ENABLED`,
  `AI_PROVIDER=bedrock`, `AWS_REGION`, `BEDROCK_MODEL_ID`,
  `AI_REQUEST_TIMEOUT_SECONDS`.
- **backend/BEDROCK_SETUP.md** — new. Least-privilege IAM policy
  (`bedrock:InvokeModel` + `bedrock:Converse` scoped to model ARN), manual
  AWS steps (model access approval), verification curl.
- **backend/routers/telehealth.py** — safe 503 error code on AI failure.
- **backend/routers/forms_protocols.py** — safe 503 error code on AI
  failure (5 occurrences).
- **backend/routers/compliance.py** — BAA checklist now lists Amazon
  Bedrock instead of Anthropic; Emergent migration row demoted to optional.
- **backend/tests/test_bedrock_ai.py** — new. 18 focused hermetic tests
  covering provider reporting, complete_text signature, fail-closed on
  disabled/misconfigured/wrong provider, event-loop non-blocking, safe
  error mapping, absence of legacy providers, no static-cred requirement,
  safe logging (no PHI in log records), fence-aware JSON extraction, and
  the `PromptTemplate` helper.
- **backend/tests/test_iter16_phase16.py** and **test_phase7.py** —
  updated to skip live-AI tests when Bedrock is not configured, and to
  accept the new health status values.

### IAM / manual AWS work required
Attach the IAM policy in `BEDROCK_SETUP.md` to the EC2 instance profile,
enable Bedrock model access for the target region/model, then set
`BEDROCK_MODEL_ID` in `backend/.env`.

### Not built (out of scope for this task per user)
- Lab Review AI endpoint / UI
- Marketing Assistant endpoint / UI
- Frontend AI health panel

_Last updated: Feb 28, 2026 (Sprint 9 · Bedrock AI Standardization)_

---

## Sprint 9.1 · Bedrock AI Features (Feb 28, 2026)

### Scope (Parts 8–9 of the AI sprint charter — backend endpoints only)
Added two AI features that reuse the Bedrock foundation. **No new AI
infrastructure was created** — both endpoints call `run_template()` in
`llm_client.py`, which routes through the single `complete_text()` entry
point. All future AI features will plug in the same way: define a
`PromptTemplate`, validate the JSON envelope, done.

### New endpoints (draft-only — never save/publish/send)
- **`POST /api/labs/{lab_id}/ai-review`** in `routers/lab_review.py`.
  Central auth helper `_ai_lab_reviewer()` (currently all workforce roles;
  future tightening is one-line). Sends minimum-necessary context only:
  the selected lab + up to five prior values of the same test + client's
  allergies, current supplements, age, and sex. Pseudonymises the patient
  with their internal id — no name, phone, email, address, insurance, or
  billing. Strict JSON envelope with mandatory disclaimer and
  `provider_review_required=True` (force-set regardless of what the model
  returns). Audit action `lab.ai_draft_generated` records feature id,
  latency, and lab metadata — never the prompt or response.
- **`POST /api/campaigns/ai-draft`** in `routers/campaigns.py`.
  Central auth helper `_ai_marketing_drafter()`. Accepts business-only
  input (`AiMarketingDraftIn`); no DB reads of patient / recipient /
  message data occur inside the endpoint. Whitelist of 16 supported
  `content_type` values; unsupported types return a safe 400. Strict JSON
  envelope with `human_review_required=True` (force-set) and content-type
  specific extensions for `content_calendar`. Audit action
  `campaign.ai_draft_generated` records feature id, content type, and
  latency — never the copy.

### Files changed
- `backend/routers/lab_review.py` — appended AI section (~280 lines).
- `backend/routers/campaigns.py` — appended AI section (~230 lines).
- `backend/tests/test_bedrock_features.py` — 18 new hermetic tests.

### Guardrails verified by tests
- PHI never enters the lab prompt (full name, email, phone, address,
  unrelated notes all excluded even when present on the client doc).
- `provider_review_required` and `human_review_required` are forced True
  even when the model tries to disable them.
- Extraneous top-level keys from the model (`auto_publish`,
  `recipient_email`, `hidden_diagnosis`, etc.) are stripped from the
  response envelope.
- Lab AI does not add save/status endpoints; the existing review-note
  workflow performs any persistence.
- Marketing AI does not add publish/send endpoints.
- Both features call `run_template()` in `llm_client.py` — no per-feature
  Bedrock client, no per-feature service class.

_Last updated: Feb 28, 2026 (Sprint 9.1 · Bedrock AI Features)_

---

## Sprint 10A · AI Frontend Integration (Feb 28, 2026)

### Scope (frontend only — no backend changes)
Wired the Sprint 9.1 AI endpoints into the existing Lab Review Queue and
Campaign Center. Zero new pages, zero new navigation, zero chat interfaces.
Built a tiny set of reusable AI primitives so every future AI feature
(SOAP drafting, treatment plans, referral letters, insurance appeals, etc.)
can drop into any workflow with the same look, error handling, and
disclaimer behavior.

### Reusable AI primitives in `frontend/src/components/ai/`
- `AiGenerateButton.jsx` — purple pill button with sparkles icon and
  loading state. Same trigger for every AI action across the app.
- `AiLoadingOverlay.jsx` — feature-agnostic "Generating AI draft…" panel.
- `AiDisclaimerBanner.jsx` — the mandatory yellow "human review required"
  banner. `role="provider"` on clinical output, `role="human"` on marketing.
- `AiDraftBadge.jsx` — the "✨ AI Draft" chip with tooltip
  "Generated using Amazon Bedrock. Requires human review before use."
- `AiDraftModal.jsx` — generic modal shell (title, disclaimer, sections,
  actions) — Lab Review uses it directly; future features plug in the
  same way.
- `aiErrors.js` — safe Bedrock error-code → toast translator.
- `index.js` — barrel exports.

### Feature integrations (existing pages extended, not replaced)
- **`pages/portal/LabReviewQueue.jsx`** — added an "AI Review" button on
  every row (`data-testid="lab-ai-review-{id}"`), an AI modal that
  renders all seven sections (Summary, Abnormal findings, Trends,
  Clinical considerations, Patient-friendly explanation, Suggested
  follow-up questions, Limitations), Copy / Regenerate / Close /
  Insert-into-Review-Note actions, and a `_aiPrefill` hook on the
  existing `ReviewDialog` so the draft populates the notes textarea for
  the provider to edit before saving via the existing review-status
  workflow.
- **`pages/portal/CampaignCenter.jsx`** — added a "Draft with AI" button
  next to the "Show preview" toggle in the composer, plus a
  `CampaignAiPanel` that opens in a nested dialog, submits only business
  context to `POST /api/campaigns/ai-draft`, and (on confirmation)
  populates the existing subject + RichTextEditor / plain-text field.

### Guardrails preserved
- Nothing auto-saves. Nothing auto-sends. Nothing auto-publishes.
- Every draft displays the mandatory disclaimer via `AiDisclaimerBanner`.
- Bedrock error codes (`bedrock_unavailable`, `bedrock_misconfigured`,
  `request_timeout`, `invalid_model_response`, `model_access_denied`,
  `ai_disabled`) translate to user-safe toasts via a single mapper.
- No raw AWS internals are surfaced — verified by unit tests.

### Tests
- Backend: 36 hermetic unit tests pass (Sprint 9 + 9.1 unchanged).
- Frontend: `components/ai/aiErrors.test.js` — 6 focused tests covering
  every Bedrock error code mapping and the fallback case. Passes under
  `craco test`.
- Live smoke tested via Playwright: 5 "AI Review" buttons render on the
  lab queue; the "Draft with AI" panel opens with all form fields.

### Files added
- `frontend/src/components/ai/AiDraftBadge.jsx`
- `frontend/src/components/ai/AiGenerateButton.jsx`
- `frontend/src/components/ai/AiLoadingOverlay.jsx`
- `frontend/src/components/ai/AiDisclaimerBanner.jsx`
- `frontend/src/components/ai/AiDraftModal.jsx`
- `frontend/src/components/ai/aiErrors.js`
- `frontend/src/components/ai/aiErrors.test.js`
- `frontend/src/components/ai/index.js`

### Files modified
- `frontend/src/pages/portal/LabReviewQueue.jsx`
- `frontend/src/pages/portal/CampaignCenter.jsx`
- `backend/tests/test_bedrock_features.py` (preload router modules at
  collection time to keep hermetic tests hermetic when run after
  `test_bedrock_ai.py`)

_Last updated: Feb 28, 2026 (Sprint 10A · AI Frontend Integration)_

---

## Sprint 11 · Staff Handoff Wiring (Feb 28, 2026)

### Scope
Closed the five staff handoffs and added a messages→tasks promotion path.
No new pages, no new dashboards, no schema drift. Every fix is a small
extension of an existing file. The single unifying change is that
`front_desk_visits.status` now syncs onto `appointments.status`, plus POS
checkout writes back onto the appointment.

### Handoff wiring
- **#1 Request → Confirmed** — `FrontDesk.jsx` now loads pending
  `status=requested` appointments and renders a warning-tone "Requests"
  card at the top of the queue with per-row **Confirm / Decline** buttons
  that PATCH `/appointments/{id}`.
- **#2 Today → Readiness** — `_hydrate_fd()` in `ops.py` computes
  `intake_complete`, `forms_pending`, `documents_ready` from the existing
  intakes/forms/files collections (never persisted). Rendered as three
  tiny chips under each client name via a new `ReadinessChips` helper in
  `FrontDesk.jsx`.
- **#3 Checked-in → Roomed → Ready** — `front_desk_update` now maps
  `checked_in → arrived`, `in_room → in_session`, `no_show → no_show`
  onto the linked `appointments.status` via `_FD_TO_APPT_STATUS`. The
  provider portal now sees front-desk state instantly.
- **#4 Visit → Checkout** — `PosCheckoutIn` gained `appointment_id`.
  `pos_checkout` writes `transaction_id` back onto the appointment and
  marks it `completed` when the transaction is paid; it also flips the
  front-desk row to `checked_out`. `FrontDesk.jsx` "Checkout" button now
  navigates to `/portal/staff/pos?client_id=...&appointment_id=...`;
  `PointOfSale.jsx` reads those params, shows a green banner, and clears
  the URL after completion. `pos_checkout` role widened to include
  `practitioner` so providers can close a visit.
- **#5 Service/Product → Inventory** — left unchanged pending policy
  clarification. Product sales already deduct correctly via
  `line.type == "inventory"`.
- **#6 Messages assignment/priority/due/status** — added
  `linked_task_id` to `ThreadOut` and a new
  `POST /api/messages/threads/{id}/promote-to-task` endpoint in
  `health_track.py` that creates an `internal_tasks` row (reusing the
  existing task assignment/priority/due-date/status/escalation model) and
  stores the reverse link. `Messages.jsx` gained a "Create task" button
  in the thread header that becomes a "Task linked" chip once promoted.

### Files modified
- `backend/models.py` — `PosCheckoutIn.appointment_id`,
  `AppointmentOut.transaction_id`, `FrontDeskOut.intake_complete` /
  `forms_pending` / `documents_ready` / `transaction_id`,
  `ThreadOut.linked_task_id`.
- `backend/routers/ops.py` — `_hydrate_fd()` readiness signals,
  `front_desk_update` status sync, `pos_checkout` appointment link,
  `pos_checkout` role widened.
- `backend/routers/health_track.py` — new promote-to-task endpoint.
- `frontend/src/pages/portal/FrontDesk.jsx` — requests card, readiness
  chips, checkout-to-POS navigation.
- `frontend/src/pages/portal/PointOfSale.jsx` — query-param intake,
  appointment banner, `appointment_id` on checkout call.
- `frontend/src/pages/portal/Messages.jsx` — promote-to-task button.

### Files added
- `backend/tests/test_staff_handoffs.py` — 5 focused end-to-end tests
  covering handoffs 1, 2, 3, 4, and 6. All pass. 41/41 backend tests
  green (Bedrock + features + handoffs).

_Last updated: Feb 28, 2026 (Sprint 11 · Staff Handoff Wiring)_

---

## Sprint 11.1 · Privacy-Safe Secure-Message Alerts (Feb 28, 2026)

### Scope
Replaced the leaky per-message push loop with a single privacy-safe
notification helper that sends BOTH web push and email alerts without
ever including the sender name, subject, message body, or attachment
details. Message content stays inside the portal.

### Changes
- **`backend/routers/health_track.py`** — new helpers
  `_message_recipient` (resolves the other portal user for a two-party
  thread), `_message_portal_path`, and `_notify_new_secure_message`
  (fires push + SendGrid email through the existing `notifiers`). Both
  channels wrap the actual send in `try/except` so the message insert
  always succeeds even if the alert channels fail. Email uses
  `redact_recipient=True` so the audit log stores only a SHA-256 prefix.
  `create_thread` fires the helper on the first message; `post_message`
  replaces the old per-participant push loop with a single call.
- **`backend/routers/health_track.py`** — links use `FRONTEND_ORIGIN`
  (matching the rest of the codebase) instead of `FRONTEND_URL`.
- **`frontend/public/service-worker.js`** — VERSION bumped to
  `nms-v9-2026-07-28-secure-message-push`; `renotify: true` added so
  successive alerts with the same tag surface fresh notifications
  instead of being silently coalesced.
- **`frontend/src/components/PushOptInBanner.jsx`** — copy updated to
  advertise secure-message alerts and to reassure users that message
  details stay inside the portal.
- **`frontend/src/pages/portal/Messages.jsx`** — header subtitle
  clarifies that email alerts never include message details.

### Guardrails verified
- Push payload is a fixed generic string ("You have a new secure
  message.") — no sender identity, subject, or body.
- Email HTML + plain-text bodies contain only a generic sender label
  ("your care team" or "a patient"), a portal link, and a
  non-monitoring/911 disclaimer — no PHI.
- Audit trail records only the thread id via `payload_metadata`; the
  recipient email is hashed via `redact_recipient=True`.
- 41/41 backend tests still pass. Live smoke: creating a thread and
  sending a follow-up both return 200; SendGrid failures are caught
  without failing the message insert.

_Last updated: Feb 28, 2026 (Sprint 11.1 · Privacy-Safe Secure-Message Alerts)_

---

## Sprint 12 · PostgreSQL Auth Foundation (Feb 28, 2026)

### Scope (Phases 1–4 + 9–10 of the migration charter)
Built the parallel PostgreSQL infrastructure the auth-stack cutover will
run on top of, without touching the still-Mongo runtime. Local PostgreSQL
is verified end-to-end; all foundation tests pass; no app behaviour has
changed yet.

### Delivered
- **12 SQLAlchemy models** across `backend/postgres_models/` (User, Client,
  UserSession, RefreshToken, LoginHistory, LoginContinuation,
  PasswordResetAttempt, PasswordResetToken, OAuthState, OAuthHandoff,
  AuditLog with autoincrementing `seq` + retained UUID `id`, SecurityEvent).
  All datetimes are `DateTime(timezone=True)`. `AuditLog.audit_metadata`
  uses `JSONB`. Foreign keys wired with correct `ondelete` behaviour.
- **Alembic** — new `alembic.ini`, rewritten `alembic/env.py` to load
  `Base.metadata` from `postgres_models` and resolve `DATABASE_URL` from
  process env. Initial revision `557f2e586456` applied to local dev.
- **Repositories layer** — `backend/repositories/*` covering users, clients,
  user_sessions, refresh_tokens (with `SELECT ... FOR UPDATE SKIP LOCKED`
  atomic claim), audit (with PostgreSQL transaction-scoped
  `pg_advisory_xact_lock`), login history + continuations, password reset
  (rate-limit windows + single-use tokens), OAuth state + one-shot handoff.
  Every function accepts an explicit `AsyncSession` and returns dicts
  matching the pre-migration Mongo shape.
- **Staff migration script** —
  `backend/scripts/migrate_staff_users_to_postgres.py`. Dry-run + real
  modes, idempotent (upserts by email), migrated 55 workforce users
  (33 admin, 16 staff, 4 practitioners, 1 MA, 1 auditor) locally. Never
  copies sessions, refresh tokens, reset tokens, OAuth material — cutover
  forces re-login.
- **Foundation tests** — 12 hermetic tests covering repo layer,
  atomic refresh rotation, single-use consume patterns, and audit chain
  seq-ordering. All pass in 0.65s.
- **Local dev Postgres** — installed PostgreSQL 15 apt package, created
  `nms_auth` DB owned by `nms_dev`. `DATABASE_URL` lives in
  `backend/.env` (gitignored); `.env.example` gained a placeholder entry.
- **Packages added to requirements.txt** — `sqlalchemy==2.0.51`,
  `alembic==1.18.5`, `psycopg==3.3.4`, `psycopg-binary==3.3.4`,
  `asyncpg==0.31.0`.

### Deferred to a follow-up PR (Phases 5–8 of the migration charter)
Converting `deps.py`, `sessions.py`, `audit.py`, and `routers/auth.py`
was scoped as this session's work but deliberately postponed to avoid
leaving the app in a broken hybrid state (a session pointing at a
Mongo-only user cannot satisfy the PostgreSQL FK). `routers/auth.py` is
975 lines with 15+ endpoints, each requiring careful atomic-transaction
conversion. See `PG_MIGRATION_STATUS.md` for the exact hand-off checklist.

### Test results
- 53/53 tests pass (12 new PG foundation + 41 pre-existing Bedrock /
  features / staff handoffs).
- App boots cleanly, `/api/health` returns 200.

_Last updated: Feb 28, 2026 (Sprint 12 · PostgreSQL Auth Foundation)_

---

## Sprint 12.5 · Auth Router Refactor (Feb 28, 2026)

### Scope (Session 1 of the atomic PG runtime cutover)
Split the 975-line `backend/routers/auth.py` into topical submodules so
the Session 2 PostgreSQL cutover can be reviewed one file at a time.
Behaviour is 100% preserved — MongoDB remains the persistence backend,
every route path / schema / cookie / MFA behaviour is unchanged, and
`routers.auth` continues to be the public entry point.

### Files added
- `backend/routers/auth_impl/_common.py` — shared imports, helpers,
  `json_dumps_body`, `_create_session`, `_email_hash`, etc. Uses `__all__`
  so `from ._common import *` re-exports underscored helpers.
- `backend/routers/auth_impl/registration.py` — register, login, login/continue.
- `backend/routers/auth_impl/refresh.py` — POST /auth/refresh with rotation.
- `backend/routers/auth_impl/sessions.py` — logout, logout-all, sessions list, revoke.
- `backend/routers/auth_impl/mfa.py` — setup, verify, disable.
- `backend/routers/auth_impl/profile.py` — me, profile update, change-password.
- `backend/routers/auth_impl/password_reset.py` — forgot, reset, dev/reset-token.
- `backend/routers/auth_impl/oauth.py` — Emergent Google + direct OAuth.
- `backend/routers/auth_impl/__init__.py` — imports every submodule so
  decorators register at import time.
- `backend/tests/test_auth_refactor_characterization.py` — 9 tests
  covering route registration, public helper exports, login + MFA,
  refresh cookie rotation, `/auth/me`, invalid password → 401, sessions
  list `is_current` flag, and generic forgot-password contract.

### Files modified
- `backend/routers/auth.py` — reduced from 975 lines to a thin shim
  that imports `auth_impl` (triggers route registration) and re-exports
  the helpers other backend modules import directly (`_create_session`,
  `_email_hash`, `_hash_token`, `_set_refresh_cookie`,
  `_clear_refresh_cookie`, `_revoke_all_sessions`, `_revoke_session`).

### Verification
- Full test suite: **62/62 passing** (9 new characterization + 12 PG
  foundation + 5 staff handoffs + 18 Bedrock features + 18 Bedrock AI).
- Backend imports cleanly and boots (`/api/health` OK).
- All 21 auth routes still registered on the shared FastAPI router.
- Live smoke: two-step MFA login returns 200 with access token +
  HttpOnly refresh cookie; refresh rotates the cookie.

_Last updated: Feb 28, 2026 (Sprint 12.5 · Auth Router Refactor)_


---

## Sprint 12.6 · Session 2a — Google OAuth Removal (2026-07-30) ✅

**Branch**: `auth-remove-google` (forked from `auth-refactor-session-1-1785441186`)

**Scope**: Remove Google SSO (Emergent-managed session exchange + direct
Google OAuth authorize/callback/exchange) end-to-end. MongoDB-backed
password/MFA runtime is preserved. The PostgreSQL runtime cutover is
NOT part of this session.

### Deleted
- `backend/routers/auth_impl/oauth.py`
- `backend/postgres_models/oauth.py`
- `backend/repositories/oauth.py`
- `frontend/src/pages/OAuthComplete.jsx`
- `backend/tests/test_sprint2_oauth_exchange.py`
- `auth_testing.md` (repo-root Google-flow doc)

### Modified — Backend
- `routers/auth_impl/__init__.py` — dropped `from . import oauth`
- `postgres_models/__init__.py` — dropped `OAuthState` / `OAuthHandoff` exports
- `alembic/env.py` — dropped OAuth model imports
- `server.py` — `/api/health` integrations dict no longer reports
  `google_oauth_direct`. Removed the empty "Emergent-managed Google SSO"
  section marker.
- `routers/compliance.py` — BAA checklist defaults now 7 rows
  (`google_workspace` entry removed).
- `routers/auth_impl/registration.py` — comment about Google-satisfies-MFA
  reworded; `mfa_bypass` field kept on user docs but no code path sets
  it now.
- `backend/.env` and `backend/.env.example` — removed
  `GOOGLE_OAUTH_CLIENT_ID` / `_SECRET` / `_REDIRECT_URI` variables.

### Modified — Frontend
- `components/AuthCard.jsx` — removed the "Continue with Google" button,
  the `googleDirectOn` / `googleSignInEmergent` / `googleSignInDirect`
  callbacks, the `#session_id=` hash callback handler, and the
  `redirectPath` prop.
- `lib/auth.jsx` — dropped `loginWithGoogleSession`,
  `beginGoogleOAuthDirect`, and `completeOAuthFromTokens` from the auth
  context.
- `App.js` — removed `OAuthComplete` import + the `/oauth-complete` route.
- `pages/Home.jsx` — removed the Google SSO button from the footer sign-in
  strip; replaced with a "Staff Sign In" link.
- `pages/Login.jsx` + `pages/StaffLogin.jsx` — removed the unused
  `redirectPath` prop.

### New Alembic migration (forward-only)
- `backend/alembic/versions/2026_07_30_2131-af896f736c94_drop_oauth_tables.py`
  drops `auth_oauth_handoffs` and `auth_oauth_states` (plus their indexes).
  Downgrade recreates them. The initial revision was NOT rewritten.
  Applied against the dev PostgreSQL instance (`alembic current` reports
  `af896f736c94 (head)`).

### Tests updated to expect 404
- `test_auth_refactor_characterization.py` — added `TestGoogleOAuthRemoved`;
  the "≥20 auth routes" assertion is now "≥16" AND explicitly asserts
  `google_routes == set()`.
- `test_iter16_phase16.py` — health check no longer asserts
  `google_oauth_direct`; the 503 tests are replaced by 404 assertions.
- `test_p0_login_fix.py` — item 5 flipped from 503 → 404.
- `test_uat_final_pass.py` — replaced `TestOAuthExchange` with
  `TestOAuthRoutesRemoved`.
- `test_phase8.py` — replaced `TestGoogleSession` with `TestGoogleSsoRemoved`.
- `test_sprint4_rbac_inventory.py` — dropped the Google routes from
  `PUBLIC_ROUTES` (they no longer exist to gate).
- `test_phase15_hipaa.py` — BAA row count 8 → 7; removed `google_workspace`
  from expected keys; replaced `anthropic` with `aws_bedrock` to match the
  Bedrock migration.
- `test_pg_auth_foundation.py` — dropped OAuth model/repo imports and the
  `TestOAuth` class.

### Verification
- Testing agent report `/app/test_reports/iteration_25.json`:
  **11/11 pass** for the new `test_session2a_google_removal.py` suite;
  **13/13 pass** for the updated characterization suite.
- Frontend Playwright: Home, `/staff-login`, `/login`, `/oauth-complete`
  all render as expected (no Google button, `/oauth-complete` falls
  through to the router's default handling).
- End-to-end MFA login smoke (admin + TOTP) → `/portal/admin` succeeds.
- BAA checklist returns 7 rows with the expected key set after purging
  the two legacy Mongo rows (`google_workspace`, `anthropic`).

### Non-goals confirmed
- No PostgreSQL runtime cutover.
- No rewrite of the initial Alembic revision.
- No admin bootstrap changes.

_Last updated: 2026-07-30 (Session 2a · Google OAuth Removal)_


---

## Sprint 12.7 · Session 2b — PostgreSQL Auth Runtime Cutover (2026-07-30) ✅

**Branch**: `auth-remove-google` (on top of Session 2a).

**Scope**: Convert all authentication persistence from MongoDB/Motor to
PostgreSQL/SQLAlchemy. API contract, JWT shape, refresh cookie behaviour,
MFA flow, and password-reset semantics unchanged. Admin bootstrap is a
separate follow-up (Session 2c).

### New files
- `backend/mongo_db.py` — Motor client + GridFS bucket now live here.
  Everything outside the auth stack imports `db` / `fs_bucket` via
  `deps.py`'s re-export.
- `backend/pg_bootstrap.py` — `sync_mongo_users_to_pg()` runs at startup
  to mirror pre-existing MongoDB users into PostgreSQL so the PG-backed
  auth stack can authenticate them. Idempotent (only inserts missing
  rows, refreshes transient password/MFA fields).

### Rewritten (auth surface — Motor-free)
- `backend/audit.py` — audit chain now lives in PostgreSQL, hash chain
  guarded by a per-transaction advisory lock. Signature preserved
  (`log_audit(db, ...)`) so every existing caller keeps compiling; the
  `db` argument is now ignored.
- `backend/sessions.py` — `issue_first_refresh`, `rotate_refresh`,
  `revoke_all_user_sessions`, `enforce_active_session_limit`,
  `check_and_touch_session`, `list_active_sessions_sanitized` all use
  `AsyncSessionLocal()` + `repositories/*`.
- `backend/deps.py` — `get_authenticated_user` reads user + session from
  PG. Re-exports `db` / `fs_bucket` from `mongo_db.py`.
- `backend/routers/auth_impl/*` — every submodule (registration, refresh,
  mfa, sessions, profile, password_reset, _common) rewritten to hit PG
  via repositories. `db` is still re-exported for the single Mongo
  `clients` write in `register()` (client business row).
- `backend/routers/admin.py` — user directory, session explorer, audit
  viewer, revoke endpoints all target PostgreSQL.

### Repository additions
- `repositories/users.py::list_recent`
- `repositories/user_sessions.py::list_active_for_admin`
- `repositories/audit.py::list_recent`

### Startup + tests
- `server.py` startup now invokes `sync_mongo_users_to_pg()` after
  seed_demo so existing Mongo users are visible to the PG auth stack.
- `postgres_db.py` loads `.env` defensively at module import so the
  connection URL is available even when postgres_db is imported before
  other modules call `load_dotenv`.
- `tests/conftest.py` now mirrors MFA enrollment + workforce session
  cleanup + audit-chain wipe into PostgreSQL (session-autouse). Also
  loads `.env` early so `test_pg_auth_foundation` no longer skips.
- `tests/test_pg_auth_foundation.py::TestAuditChain` isolates its
  primitive fake-hash inserts via a wipe fixture so the UAT
  `verify_audit_chain` test isn't contaminated.

### Verification
- Full auth regression: **114 pass**, 2 pre-existing SendGrid-live
  failures unrelated to this migration.
- Live curl smoke: MFA login → PG `auth_user_sessions` row created and
  `mfa_satisfied_at` set → refresh rotates (generation++, previous row
  replaced) → `/auth/sessions` returns the active set → `logout-all`
  revokes every row → password reset via dev token consumes the token,
  revokes all sessions, allows re-login.
- Grep hygiene (all zero):
  - `grep -rn 'from motor\|import motor\|AsyncIOMotor' backend/deps.py backend/audit.py backend/sessions.py backend/routers/auth_impl/ backend/repositories/`
  - `grep -rn 'db\.users\|db\.user_sessions\|db\.refresh_tokens\|db\.login_history\|db\.login_continuations\|db\.password_reset\|db\.audit_logs\|db\.security_events' backend/audit.py backend/sessions.py backend/routers/auth_impl/`
- Alembic head still `af896f736c94` (Session 2a's oauth-drop revision).

### Non-goals confirmed
- No admin bootstrap changes (Session 2c).
- No new alembic migrations.
- Mongo `clients`, `appointments`, `notes`, `files`, `visit_notes`, etc.
  remain on MongoDB — non-auth business collections are out of scope.
- Password hashing (bcrypt) unchanged — Argon2id migration is Session 2d.

_Last updated: 2026-07-30 (Session 2b · PostgreSQL Auth Runtime Cutover)_
