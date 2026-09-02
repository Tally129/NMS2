# Session 3 — PostgreSQL Migration Inventory

> Analysis-only session. No code was modified. This is the source-of-truth
> plan for Sessions 3a → 3g (per-domain migrations). Every subsequent
> session should carve out ONE row from the batch table below and treat it
> as its entire scope.

**Snapshot date**: 2026-07-31 (Phase 3.2 scheduling runtime cutover complete)
**Branch**: `auth-remove-google`
**Last commit**: (about to commit Phase 3.2)
**Alembic head**: `c8f4a2e7b3d1`

---

## Session 3.2 — Scheduling Runtime Cutover Complete (2026-07-31)

The following five MongoDB collections have been **dropped** after successful
backfill + regression + smoke tests; verified they do NOT regenerate on
backend restart or after normal HTTP traffic:

| Collection             | Docs at drop | PG target                  |
|------------------------|--------------|-----------------------------|
| `appointments`         | 515          | `emr_appointments`          |
| `appointment_requests` | 7            | `emr_appointment_requests`  |
| `availability`         | 0            | `emr_availability`          |
| `reminders`            | 401          | `emr_reminders`             |
| `reminder_settings`    | 0            | `emr_reminder_settings`     |

Migration artifacts:
- Alembic revision `c8f4a2e7b3d1` (phase 3.2 scheduling)
- `postgres_models/scheduling.py` — Appointment / AppointmentRequest /
  Availability / Reminder / ReminderSettings models
- `repositories/scheduling.py` — full CRUD + list_appointments_with_waiting_state
- `scripts/phase3_2_backfill.py` (idempotent) — 923 rows migrated
- `scripts/phase3_2_reconcile.py` — orphan-reference audit report

All eight routers touching the retired collections were rewritten:
`server.py`, `routers/appointments.py`, `routers/telehealth.py`,
`routers/campaigns.py`, `routers/campaign_extras.py`,
`routers/compliance.py`, `routers/portal_ops.py`, `routers/ops.py`,
`routers/admin.py`.

Regression tests: `tests/test_session3_2_scheduling.py` (6/6 pass)
plus `tests/test_session3_1_clients.py` (6/6 pass, no regression).

---

## Session 3.1b — Runtime Cutover Complete (2026-07-31)

The following six MongoDB collections have been **dropped** and verified they
do NOT regenerate on backend restart or after normal HTTP traffic:

| Collection                       | Docs at drop | PG target                              |
|----------------------------------|--------------|----------------------------------------|
| `users`                          | 1,221        | `auth_users`                           |
| `clients`                        | 1,587        | `emr_clients`                          |
| `intake_forms`                   | 2            | `emr_intake_forms`                     |
| `supplement_sheets`              | 76           | `emr_supplement_sheets`                |
| `client_supplement_assignments`  | 97           | `emr_client_supplement_assignments`    |
| `password_reset_tokens`          | 0            | `emr_legacy_password_reset_tokens`     |

All 15 target routers have been rewritten to route through
`pg_shims.py` (Mongo-shape helpers over the async SQLAlchemy repositories):
`server.py`, `permissions.py`, `routers/clients.py`, `routers/portal_ops.py`,
`routers/telehealth.py`, `routers/appointments.py`, `routers/campaigns.py`,
`routers/campaign_extras.py`, `routers/lab_review.py`, `routers/ops.py`,
`routers/tasks.py`, `routers/health_track.py`, `routers/delegations.py`,
`routers/compliance.py`, `routers/forms_protocols.py`, `routers/admin.py`.

Added Alembic revision `b7e2c4d9a1f8` (adds `emr_clients.tags` JSONB).
Removed dead helper `pg_bootstrap.py`.
Added regression tests: `tests/test_session3_1_clients.py` (6/6 pass) +
`tests/pg_test_helpers.py`.

---

## 1. Global metrics

- **Total distinct Mongo collections still accessed at runtime**: **67**
- **Total documents across those 67 collections**: **~50,700**
  (the loudest are `integration_log ≈ 31,905`, `audit_logs ≈ 9,023`
  [now a Mongo mirror after Session 2b — no new writes],
  `login_history ≈ 2,970`, `clients ≈ 1,577`, `users ≈ 1,218`,
  `appointments ≈ 394`).
- **Motor imports outside the auth stack**: **1 remaining file** —
  `backend/mongo_db.py` (intentional — Session 2b centralized the Motor
  client there, re-exported through `deps.py`).
- **GridFS usage**: 2 write paths, 2 read paths.
  - `routers/clients.py` → patient uploads (`emr_files` bucket)
  - `routers/telehealth.py` → visit recording WebM upload/download
    (same bucket)
- **Dynamic-schema patterns needing redesign before SQL**: 6 (see §4).

---

## 2. Collection inventory

Legend

| Field                | Meaning                                                          |
| -------------------- | ---------------------------------------------------------------- |
| **Count**            | `estimated_document_count()` from live Mongo (approx).           |
| **PHI**              | ✅ contains protected health information (per HIPAA).             |
| **PG target**        | Proposed SQLAlchemy table(s).                                    |
| **Complexity**       | L = low (thin table), M = medium (FKs + light indexing),         |
|                      | H = high (denormalisation, GridFS blobs, or FK graph rework).    |
| **Batch**            | Session 3x that should own it (see §5 for definitions).          |

### 2.a Legacy auth collections — Session 3.0 outcome

Session 3.0 (2026-07-30) dropped **6 of these 10** collections in the
development MongoDB after a full backup and reconciliation. The remaining
**4** stayed in place because non-auth routers still consume them and
must migrate as part of their proper domain sessions.

| Collection                | Count  | PHI | PG target                      | Session 3.0 outcome                                        |
| ------------------------- | ------ | --- | ------------------------------ | ---------------------------------------------------------- |
| `user_sessions`           | 66     | –   | `auth_user_sessions`            | ✅ **DROPPED**                                              |
| `refresh_tokens`          | 85     | –   | `auth_refresh_tokens`           | ✅ **DROPPED**                                              |
| `login_history`           | 2970   | –   | `auth_login_history`            | ✅ **DROPPED**                                              |
| `login_continuations`     | 0      | –   | `auth_login_continuations`      | ✅ **DROPPED**                                              |
| `password_reset_attempts` | 377    | –   | `auth_password_reset_attempts`  | ✅ **DROPPED**                                              |
| `oauth_handoffs`          | 55     | –   | (removed in Session 2a)         | ✅ **DROPPED**                                              |
| `users`                   | 1218   | ✅   | `auth_users`                    | ⛔ DEFER — 42 runtime refs (see §7 owner list)              |
| `password_reset_tokens`   | 0      | –   | `auth_password_reset_tokens`    | ⛔ DEFER — 3 refs in `portal_ops.py` staff-side reset flow  |
| `audit_logs`              | 9023   | –   | `auth_audit_logs`               | ✅ **DROPPED (Session 3.0b)**                                |
| `security_events`         | 223    | –   | `auth_security_events`          | ✅ **DROPPED (Session 3.0b)**                                |

**Backup**: `/app/backups/session-3.0-20260730T233413Z/test_database/*.bson.gz`
(verified via `mongorestore --dryRun`).

**Follow-up sessions that must remove the 4 deferred consumers**:
- `users` → Session 3.1 (Patients/Clients) and a parallel sweep of the
  ~10 routers that read `db.users` for display-name lookups
- `password_reset_tokens` → covered by the portal-ops migration
  (currently unowned — schedule alongside Session 3.7)
- `audit_logs` + `security_events` → point `compliance.py` at the PG
  `auth_audit_logs` table and drop the startup index-creation calls in
  `server.py`. Small standalone follow-up (Session 3.0b).

---

### 2.b Domain: **Patients / Clients** (Batch 3.1)

| Collection                        | Count | PHI | Files/routes                                                                 | PG target                                    | FKs / indexes                                                       | Complexity |
| --------------------------------- | ----- | --- | ---------------------------------------------------------------------------- | -------------------------------------------- | ------------------------------------------------------------------- | ---------- |
| `clients`                         | 1577  | ✅   | `clients.py`, `admin.py`, `appointments.py`, `campaigns.py`, `telehealth.py`, `lab_review.py`, `portal_ops.py`, `ops.py`, `forms_protocols.py`, `tasks.py`, `health_track.py`, `delegations.py`, `auth_impl/registration.py`, `auth_impl/profile.py`, `deps.py`, `permissions.py`, `campaign_extras.py`, `server.py` | `emr_clients` (extend existing empty `auth_clients` or rename) | FK→`auth_users(id)`; UNIQUE(email), INDEX(assigned_practitioner_id, intake_completed) | **H** |
| `intake_forms`                    | 2     | ✅   | `clients.py`, `server.py`                                                    | `emr_intake_forms`                            | FK→`emr_clients(id)`                                                | L          |
| `intakes`                         | (0)   | ✅   | `telehealth.py`, `ops.py`                                                    | (merge into `emr_intake_forms`)               | ""                                                                  | L          |
| `client_supplement_assignments`   | 97    | ✅   | `clients.py`, `compliance.py`, `server.py`                                   | `emr_client_supplement_assignments`           | FK→`emr_clients(id)`; INDEX(client_id, active)                       | L          |
| `supplement_sheets`               | 76    | ✅   | `clients.py`, `forms_protocols.py`                                           | `emr_supplement_sheets`                       | FK→`emr_clients(id)`; INDEX(client_id, created_at DESC)              | L          |

Why this batch is highest-impact: **`clients` is the anchor FK for every
downstream domain.** Migrate this first and the rest of the graph resolves.

---

### 2.c Domain: **Scheduling / Appointments** (Batch 3.2)

| Collection              | Count | PHI | Files/routes                                                          | PG target                     | FKs / indexes                                                                     | Complexity |
| ----------------------- | ----- | --- | --------------------------------------------------------------------- | ----------------------------- | --------------------------------------------------------------------------------- | ---------- |
| `appointments`          | 394   | ✅   | `appointments.py`, `telehealth.py`, `campaigns.py`, `ops.py`, `portal_ops.py`, `compliance.py`, `campaign_extras.py`, `server.py` | `emr_appointments`            | FK→`emr_clients(id)`, `auth_users(id)` (practitioner); INDEX(client_id, start_at), (practitioner_id, start_at), (status, start_at) | **H** |
| `appointment_requests`  | 7     | ✅   | `admin.py`, `server.py`                                               | `emr_appointment_requests`    | FK→`emr_clients(id)`; INDEX(status, created_at)                                    | L          |
| `availability`          | (0)   | –   | `appointments.py`                                                     | `emr_provider_availability`   | FK→`auth_users(id)`; INDEX(user_id, day_of_week)                                    | L          |
| `reminders`             | 314   | ✅   | `appointments.py`                                                     | `emr_appointment_reminders`   | FK→`emr_appointments(id)`; INDEX(appointment_id, send_at, sent_at)                 | L          |
| `reminder_settings`     | (0)   | –   | `appointments.py`                                                     | `emr_reminder_settings`       | UNIQUE(scope='global') — single-row config                                          | L          |

Watch-out: `appointments` has a status-machine (`requested`→`confirmed`→
`in_session`→`completed`/`cancelled`/`no_show`). Encode as `Enum` or a
`CHECK` constraint, not just VARCHAR.

---

### 2.d Domain: **Clinical records** (Batch 3.3) — the PHI-heaviest batch

| Collection                | Count | PHI | Files/routes                                                                 | PG target                            | FKs / indexes                                                                | Complexity |
| ------------------------- | ----- | --- | ---------------------------------------------------------------------------- | ------------------------------------ | ---------------------------------------------------------------------------- | ---------- |
| `visit_notes`             | 140   | ✅   | `clients.py`, `telehealth.py`, `ops.py`, `admin.py`, `compliance.py`, `server.py` | `emr_visit_notes`                     | FK→`emr_clients`, `auth_users(practitioner_id)`, `emr_appointments`; INDEX(client_id, encounter_at DESC), (practitioner_id) | **H**      |
| `live_soap_drafts`        | 21    | ✅   | `telehealth.py`                                                              | `emr_live_soap_drafts`               | FK→`emr_appointments(id)` UNIQUE; INDEX(appointment_id)                       | M          |
| `symptom_logs`            | (0)   | ✅   | `health_track.py`                                                            | `emr_symptom_logs`                   | FK→`emr_clients(id)`; INDEX(client_id, logged_at DESC)                        | L          |
| `lab_values`              | 5     | ✅   | `health_track.py`, `lab_review.py`                                           | `emr_lab_values`                     | FK→`emr_clients(id)`; INDEX(client_id, drawn_at DESC)                          | L          |
| `treatment_plans`         | 8     | ✅   | `appointments.py`, `campaigns.py`, `compliance.py`                           | `emr_treatment_plans`                | FK→`emr_clients(id)`; INDEX(client_id, active)                                  | M          |
| `treatments`              | 1     | ✅   | `ops.py`, `portal_ops.py`                                                    | `emr_treatments`                     | FK→`emr_treatment_plans(id)`                                                    | L          |
| `protocol_enrollments`    | 135   | ✅   | `forms_protocols.py`, `compliance.py`, `server.py`                           | `emr_protocol_enrollments`           | FK→`emr_clients`, `emr_protocol_templates`; INDEX(client_id, active)             | M          |
| `protocol_templates`      | 1     | –   | `forms_protocols.py`, `server.py`                                            | `emr_protocol_templates` (config)     | UNIQUE(name); JSONB body                                                        | L          |
| `visit_chat`              | 29    | ✅   | `telehealth.py`                                                              | `emr_visit_chat`                     | FK→`emr_appointments(id)`; INDEX(appointment_id, ts)                            | L          |
| `clinical_delegations`    | 2     | ✅   | `delegations.py`                                                             | `emr_clinical_delegations`           | FK→`auth_users(from_user_id)`, `auth_users(to_user_id)`; INDEX(from_user_id, active) | M      |

Batch note: this is where **BAA compliance depends on the migration**.
Move audit-tie-in first (already PG in Session 2b), then this domain.

---

### 2.e Domain: **Secure messaging + document metadata** (Batch 3.4)

| Collection         | Count | PHI | Files/routes                                                             | PG target                    | FKs / indexes                                                    | Complexity |
| ------------------ | ----- | --- | ------------------------------------------------------------------------ | ---------------------------- | ---------------------------------------------------------------- | ---------- |
| `message_threads`  | 13    | ✅   | `health_track.py`                                                        | `emr_message_threads`        | FK→`emr_clients(id)`; INDEX(client_id, last_message_at)          | M          |
| `messages`         | 17    | ✅   | `health_track.py`                                                        | `emr_messages`               | FK→`emr_message_threads(id)`, `auth_users(sender_id)`; INDEX(thread_id, sent_at DESC) | M |
| `files`            | 71    | ✅   | `clients.py`, `admin.py`, `ops.py`, `compliance.py`, `lab_review.py`, `server.py`, `malware_scan.py` | `emr_files`                 | FK→`emr_clients(id)`, `auth_users(uploaded_by)`; INDEX(client_id, uploaded_at DESC); `gridfs_id` stays as VARCHAR pointer | **H** (GridFS coupling) |
| `form_submissions` | 168   | ✅   | `forms_protocols.py`, `compliance.py`, `server.py`                       | `emr_form_submissions`       | FK→`emr_clients`, `emr_form_templates`; INDEX(client_id, submitted_at) | M    |
| `form_templates`   | 4     | –   | `forms_protocols.py`, `server.py`                                        | `emr_form_templates` (config) | UNIQUE(slug); JSONB schema                                        | L          |
| `forms`            | (0)   | –   | `ops.py`                                                                 | (merge into `emr_form_submissions`) | ""                                                          | L          |
| `soap_templates`   | 2     | –   | `forms_protocols.py`, `server.py`                                        | `emr_soap_templates`         | UNIQUE(name); JSONB sections                                       | L          |

**GridFS decision**: keep GridFS as-is for now. The `files.gridfs_id`
column stores the ObjectId as a string. Do NOT migrate blobs to
PostgreSQL LOs — S3/MinIO is a better target for the next capital
project. This means **Mongo cannot be fully retired at the end of
Session 3.4**; `mongo_db.py` stays until GridFS is replaced.

---

### 2.f Domain: **CRM / Leads / Marketing** (Batch 3.5)

| Collection             | Count | PHI | Files/routes                                          | PG target                   | FKs / indexes                                                                | Complexity |
| ---------------------- | ----- | --- | ----------------------------------------------------- | --------------------------- | ---------------------------------------------------------------------------- | ---------- |
| `campaigns`            | 30    | –   | `campaigns.py`, `campaign_extras.py`                  | `crm_campaigns`             | INDEX(status, scheduled_at)                                                    | M          |
| `campaign_templates`   | (0)   | –   | `campaign_extras.py`                                  | `crm_campaign_templates`    | UNIQUE(slug); JSONB body                                                        | L          |
| `campaign_unsubscribes`| (0)   | –   | `campaign_extras.py`                                  | `crm_campaign_unsubscribes` | UNIQUE(email_hash); INDEX(campaign_id, unsubscribed_at)                         | L          |
| `vip_list`             | 4     | –   | `server.py`                                           | `crm_vip_list`              | UNIQUE(email); INDEX(created_at DESC)                                           | L          |
| `legal_policies`       | 9     | –   | `legal.py`                                            | `crm_legal_policies`        | UNIQUE(slug, version)                                                          | L          |
| `legal_acceptances`    | 4     | –   | `legal.py`                                            | `crm_legal_acceptances`     | FK→`auth_users`, `crm_legal_policies`; INDEX(user_id, policy_id)                | L          |

---

### 2.g Domain: **Billing / Payments / Accounting / Inventory** (Batch 3.6)

Split into **3.6a — Ledger core** and **3.6b — Ancillary** because the
double-entry accounting engine touches 12 collections and must migrate as
one atomic unit (event/journal/COA/DL/backfill invariants).

#### 3.6a — Ledger core (must migrate together)

| Collection                  | Count | PHI | Files/routes                                                     | PG target                       | FKs / indexes                                                       | Complexity |
| --------------------------- | ----- | --- | ---------------------------------------------------------------- | ------------------------------- | ------------------------------------------------------------------- | ---------- |
| `accounting_events`         | 284   | –   | `accounting.py`, `accounting/*`                                  | `acc_events`                    | INDEX(event_type, ts), (source_id) — content-hash unique             | **H**      |
| `journal_entries`           | 283   | –   | `accounting.py`, `accounting/*`                                  | `acc_journal_entries`           | FK→`acc_events`, `acc_accounts`; INDEX(period_end, account_id)       | **H**      |
| `chart_of_accounts`         | 34    | –   | `accounting.py`, `accounting/*`                                  | `acc_accounts`                  | UNIQUE(code); INDEX(type)                                            | M          |
| `posting_dead_letters`      | 11    | –   | `accounting.py`, `accounting/posting_engine.py`, `validation.py`, `dashboard.py` | `acc_posting_dead_letters`      | INDEX(created_at DESC, resolved_at)                                   | L          |
| `accounting_backfill_runs`  | 61    | –   | `accounting.py`, `accounting/backfill.py`                        | `acc_backfill_runs`             | INDEX(started_at DESC)                                                | L          |
| `invoices`                  | 0     | ✅   | `appointments.py`, `accounting/backfill.py`, `accounting/reports.py` | `acc_invoices`                  | FK→`emr_clients`; INDEX(client_id, issued_at)                          | M          |
| `transactions`              | 163   | ✅   | `ops.py`, `accounting/backfill.py`                               | `acc_transactions`              | FK→`emr_clients`; INDEX(client_id, ts)                                 | M          |
| `memberships`               | (0)   | ✅   | `campaigns.py`, `appointments.py`, `accounting/backfill.py`      | `acc_memberships`               | FK→`emr_clients`; INDEX(client_id, status)                             | L          |
| `pos_sales`                 | (0)   | ✅   | `compliance.py`                                                  | `acc_pos_sales`                 | FK→`emr_clients`; INDEX(client_id, sold_at)                            | M          |

#### 3.6b — Banking + payroll + inventory (ancillary; migrate together)

| Collection              | Count | PHI | Files/routes                                          | PG target                       | FKs / indexes                                                       | Complexity |
| ----------------------- | ----- | --- | ----------------------------------------------------- | ------------------------------- | ------------------------------------------------------------------- | ---------- |
| `bank_accounts`         | 16    | –   | `accounting.py`, `accounting/banking.py`, `cash_reports.py`, `reconciliation.py` | `bank_accounts`                | UNIQUE(gl_account_id) — one bank account per COA row                 | L          |
| `bank_transactions`     | 4     | –   | `accounting.py`, `accounting/banking.py`, `statements.py`, `reconciliation.py`, `cash_reports.py` | `bank_transactions`            | FK→`bank_accounts`, `bank_import_batches`; INDEX(account_id, posted_at)  | M      |
| `bank_import_batches`   | 21    | –   | `accounting.py`, `accounting/statements.py`           | `bank_import_batches`          | FK→`bank_accounts`; INDEX(account_id, imported_at DESC)              | L          |
| `bank_transfers`        | 11    | –   | `accounting.py`                                       | `bank_transfers`               | FK→`bank_accounts` (source, dest)                                     | L          |
| `reconciliations`       | 0     | –   | `accounting.py`, `accounting/banking.py`, `reconciliation.py`, `cash_reports.py` | `bank_reconciliations`          | FK→`bank_accounts`; INDEX(account_id, period_end)                    | M          |
| `imported_batches`      | 27    | –   | `ops.py`                                              | `bank_imported_batches`        | INDEX(imported_at DESC)                                              | L          |
| `expenses`              | 11    | –   | `accounting.py`, `accounting/backfill.py`             | `acc_expenses`                 | FK→`vendors`; INDEX(paid_at DESC)                                     | L          |
| `vendor_bills`          | 22    | –   | `accounting.py`                                       | `acc_vendor_bills`             | FK→`vendors`; INDEX(due_at)                                            | L          |
| `vendors`               | 12    | –   | `accounting.py`, `portal_ops.py`                      | `acc_vendors`                  | UNIQUE(name)                                                          | L          |
| `payroll_runs`          | 11    | ✅   | `accounting.py`                                       | `acc_payroll_runs`             | FK→`employees`; INDEX(period_end)                                     | M          |
| `employees`             | 11    | ✅   | `accounting.py`                                       | `acc_employees`                | FK→`auth_users`; UNIQUE(email)                                        | L          |
| `time_entries`          | 56    | –   | `ops.py`                                              | `acc_time_entries`             | FK→`acc_employees`; INDEX(employee_id, worked_at)                     | L          |
| `inventory_items`       | 102   | –   | `ops.py`, `portal_ops.py`, `accounting/backfill.py`, `server.py` | `inv_items`                    | UNIQUE(sku); INDEX(qty_on_hand, reorder_at)                            | M          |
| `inventory_transactions`| 56    | –   | `ops.py`, `accounting/backfill.py`                    | `inv_transactions`             | FK→`inv_items`; INDEX(item_id, ts DESC)                                | L          |
| `front_desk_visits`     | 51    | ✅   | `ops.py`                                              | `emr_front_desk_visits`        | FK→`emr_clients`; INDEX(client_id, visited_at DESC)                    | L          |

---

### 2.h Domain: **Config, templates, notifications, support** (Batch 3.7)

| Collection             | Count | PHI | Files/routes                                    | PG target                    | FKs / indexes                                            | Complexity |
| ---------------------- | ----- | --- | ----------------------------------------------- | ---------------------------- | -------------------------------------------------------- | ---------- |
| `internal_tasks`       | 20    | ✅   | `tasks.py`, `lab_review.py`, `health_track.py`  | `sup_internal_tasks`         | FK→`auth_users(assigned_to)`; INDEX(assigned_to, status, priority) | M    |
| `push_subscriptions`   | 1     | –   | `notifiers.py`, `server.py`                     | `sup_push_subscriptions`     | FK→`auth_users`; UNIQUE(user_id, endpoint)                | L          |
| `breakglass_sessions`  | 25    | ✅   | `breakglass.py`, `permissions.py`, `server.py`  | `sup_breakglass_sessions`    | FK→`auth_users(actor_id)`; INDEX(actor_id, ends_at)      | M          |
| `baa_records`          | 7     | –   | `compliance.py`                                 | `sup_baa_records` (config)   | UNIQUE(key)                                                | L          |
| `integration_log`      | 31905 | –   | `notifiers.py`, `telehealth.py`, `appointments.py`, `ops.py`, `accounting.py`, `server.py` | `sup_integration_log`       | INDEX(vendor, ts DESC), (status)                          | **H** (volume) |
| `ws_tickets`           | 0     | –   | `telehealth.py`, `server.py`                    | `sup_ws_tickets`             | UNIQUE(token); short TTL                                   | L          |

`integration_log` at ~32k rows is the largest volume in the app. Keep it
INSERT-only + partition by day OR archive to S3 after 90 days.

---

## 3. Stays outside PostgreSQL — permanent list

| Item                                    | Why                                                                                          |
| --------------------------------------- | -------------------------------------------------------------------------------------------- |
| `emr_files.files` / `emr_files.chunks`  | GridFS blob storage. Replace with S3/MinIO in a dedicated capital project, NOT with Postgres LOs. |
| Object storage metadata (`gridfs_id`)   | Keep as a VARCHAR pointer on `emr_files`. If S3 replaces GridFS, this becomes `s3_key`.        |
| Legacy Session 2b mirror collections    | Drop after 30-day grace + backup verification (see §2.a).                                     |
| One-off ad-hoc analytics queries        | If ever added, use a read replica or dbt-style materialized views — do NOT put them in PG.    |

---

## 4. Dynamic-schema patterns needing pre-migration redesign

These are collections where the shape of a document depends on a
`type`/`kind` field. Naively migrating them to a SQL table produces a
sparse mess.

| Collection              | Pattern                                                                                       | Recommendation                                                                                                     |
| ----------------------- | --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `accounting_events`     | `event_type` dispatches to 8 shapes (appointment_completed, pos_sale, expense, payroll, …).   | Keep a flat table + a `payload JSONB` column; validate at the router level. Do NOT try to normalise the payloads.  |
| `journal_entries`       | Line-items are an array on the document.                                                       | Split into `acc_journal_entries` + `acc_journal_entry_lines` (1-N) with `sum(debit)=sum(credit)` CHECK constraint. |
| `integration_log`       | `payload` blob varies per vendor.                                                              | JSONB column + generated `vendor` index.                                                                            |
| `form_templates`        | `sections`/`questions` nested.                                                                 | JSONB column; validate schema in Pydantic before insert.                                                            |
| `protocol_templates`    | `steps` array with per-step config.                                                            | JSONB column; validate in Pydantic.                                                                                 |
| `visit_notes`           | Legacy shape mixes free-text SOAP with structured amendments (`amendments[]`).                 | Split into `emr_visit_notes` + `emr_visit_note_amendments` (1-N); keep `soap` as JSONB.                             |
| `campaigns`             | `steps[]` with `channel` = `email`/`sms`/`push`/`wait`.                                        | Split into `crm_campaigns` + `crm_campaign_steps` (1-N).                                                            |
| `treatment_plans`       | `items[]` with `dose`, `frequency`, `duration`.                                                | Split into `emr_treatment_plans` + `emr_treatment_plan_items` (1-N).                                                |

---

## 5. Dependency graph + migration batches

```
                    ┌──────────────────────────┐
                    │        auth_users        │  (already PG — Session 2b)
                    └────────────┬─────────────┘
                                 │
                                 ▼
             ┌───────────────────────────────────────┐
             │             emr_clients               │  ← Batch 3.1
             └────┬──────────┬──────────┬────────────┘
                  │          │          │
                  ▼          ▼          ▼
       ┌──────────────┐ ┌────────────┐ ┌────────────────────┐
       │appointments  │ │visit_notes │ │message_threads/    │
       │ + reminders  │ │ + treatment│ │messages/files      │
       │              │ │  plans/labs│ │                    │
       └──────┬───────┘ └────────────┘ └────────────────────┘
              │            Batch 3.3          Batch 3.4
              │
              ▼
        Batch 3.2
              │
              ▼
       ┌──────────────┐          ┌──────────────────┐
       │  invoices /  │          │ campaigns /      │
       │  memberships │◀────────▶│ vip_list /       │
       │  / pos_sales │          │ legal_*          │
       └──────┬───────┘          └──────────────────┘
              │                       Batch 3.5
              ▼
       ┌────────────────────────────────────────────┐
       │  accounting_events → journal_entries →     │
       │  chart_of_accounts + posting_dead_letters  │
       │  + banking + payroll + inventory + vendors │
       └────────────────────────────────────────────┘
                       Batch 3.6 (a + b)

       ┌───────────────────────────────────────┐
       │ internal_tasks · push_subscriptions · │
       │ breakglass_sessions · baa_records ·   │
       │ integration_log · ws_tickets          │
       └───────────────────────────────────────┘
                       Batch 3.7
```

**Ordering rule**: never migrate a domain until every FK-parent it depends
on is on PostgreSQL.

### Proposed batches (one per session)

| Session | Domain                                                | Collections migrated                                                                                     | Est. sessions |
| ------- | ----------------------------------------------------- | -------------------------------------------------------------------------------------------------------- | ------------- |
| **3.0** | Retire the Session 2b legacy Mongo mirrors            | drop 10 collections after backup + audit                                                                 | 1 short       |
| **3.1** | Patients / Clients                                    | `clients`, `intake_forms`, `intakes` (merge), `client_supplement_assignments`, `supplement_sheets`       | 1             |
| **3.2** | Scheduling / Appointments                             | `appointments`, `appointment_requests`, `availability`, `reminders`, `reminder_settings`                 | 1             |
| **3.3** | Clinical records                                      | `visit_notes` (split), `live_soap_drafts`, `symptom_logs`, `lab_values`, `treatment_plans` (split),      | 1 (long)      |
|         |                                                       | `treatments`, `protocol_enrollments`, `protocol_templates`, `visit_chat`, `clinical_delegations`         |               |
| **3.4** | Secure messaging + document metadata (GridFS stays)   | `message_threads`, `messages`, `files`, `form_submissions`, `form_templates`, `forms`, `soap_templates`  | 1             |
| **3.5** | CRM / Leads / Marketing                               | `campaigns` (split), `campaign_templates`, `campaign_unsubscribes`, `vip_list`, `legal_policies`, `legal_acceptances` | 1 |
| **3.6a**| Billing / Payments (ledger core)                      | `accounting_events`, `journal_entries` (split), `chart_of_accounts`, `posting_dead_letters`, `accounting_backfill_runs`, `invoices`, `transactions`, `memberships`, `pos_sales` | 1 (long) |
| **3.6b**| Banking / Payroll / Inventory                         | `bank_accounts`, `bank_transactions`, `bank_import_batches`, `bank_transfers`, `reconciliations`, `imported_batches`, `expenses`, `vendor_bills`, `vendors`, `payroll_runs`, `employees`, `time_entries`, `inventory_items`, `inventory_transactions`, `front_desk_visits` | 1 (long) |
| **3.7** | Config / templates / notifications / support          | `internal_tasks`, `push_subscriptions`, `breakglass_sessions`, `baa_records`, `integration_log`, `ws_tickets` | 1 |

**After Session 3.7**, the only remaining Mongo dependencies are the
GridFS blob store (`emr_files.files` + `emr_files.chunks`). At that point
`mongo_db.py` can be reduced to a GridFS-only handle. Replacing GridFS
with S3/MinIO is a follow-up capital project **outside the Session 3
scope**.

---

## 6. Per-batch acceptance criteria (identical shape for every session)

Every 3.x session must satisfy this checklist before it is considered
complete:

1. **SQLAlchemy models** for every table in the batch, following the
   `emr_*` / `acc_*` / `crm_*` / `sup_*` / `inv_*` / `bank_*` prefix
   conventions.
2. **Forward-only Alembic revision** applied against the dev DB (do not
   rewrite prior migrations).
3. **Repositories** in `backend/repositories/` for every table; router
   code must not embed raw SQL or ORM statements outside repositories.
4. **Router code cutover** — every `db.<collection>.<op>` call in the
   batch's file list replaced with the repository. Zero regex hits
   remain after grep for the batch's collection names.
5. **Data migration script** in `backend/scripts/` — reads Mongo, writes
   PG, idempotent, callable both at startup (dev seed) and as a one-off
   management command. Log summary: `inserted=X, updated=Y, skipped=Z`.
6. **Backfill verification query** — one `SELECT COUNT(*)` per new PG
   table must match `db.<collection>.count_documents({})` at the moment
   of the cutover, with a documented tolerance for excluded/soft-deleted
   rows.
7. **Regression tests** — every existing pytest that touched the
   collection now passes against the PG-backed router (no double-write
   band-aids).
8. **New pytest** at `backend/tests/test_session3x_<domain>.py` covering
   at least one create/read/update/delete per table, one FK
   constraint-violation case, and one index-hit sanity check.
9. **`testing_agent_v3_fork`** run against the domain's HTTP surface.
10. **Audit events preserved** — every `log_audit(...)` call surface
    remains identical (already PG-backed since Session 2b).
11. **Rollback plan** — the Alembic downgrade is written and applied
    once in the dev DB to prove reversibility.
12. **Documentation**: PRD.md gains a `Sprint 12.x` entry with commit
    hash, Alembic revision, files touched, and remaining risks.

---

## 7. Cross-cutting risks and mitigations

| Risk                                                                             | Mitigation                                                                                                             |
| -------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `clients` FK propagates through 18 files.                                        | Complete Session 3.1 in one sitting; use a shim layer in `deps.py::_resolve_self_client` to return PG or Mongo shape.  |
| `accounting_events` hash chain integrity across the cutover.                     | Re-derive the chain from the migrated PG rows in Session 3.6a; keep Mongo read-only until re-derived hashes verify.    |
| `integration_log` size (~32k rows).                                              | Migrate incrementally by 5k-row batches; add PG index BEFORE bulk COPY.                                                |
| GridFS coupling in `files.gridfs_id`.                                             | Keep GridFS operational; add a `storage_backend` VARCHAR column on `emr_files` (`gridfs` / `s3`) for the future switch. |
| `visit_notes.amendments[]` array shape.                                          | Split into a child table BEFORE loading data; migrate amendments as separate rows.                                     |
| Mongo `_id` ObjectId leaking into PG `id` VARCHAR(64).                            | Use `str(_id)` at migration time (`hex` form is 24 chars, fits comfortably).                                            |
| Test parallelism against PG (advisory-lock contention in audit chain).           | Batch tests reuse `TestAuditChain::_isolate_chain` pattern from Session 2b.                                            |
| Legacy Mongo callers hitting a table that has already migrated.                   | Delete every `db.<collection>` reference in the domain's file list as part of the same PR — no dual-write phase.        |

---

## 8. Not in scope for Session 3

- **Argon2id migration** — Session 2d.
- **Risk-based login detection** — Session 2d.
- **Recovery-code regeneration UX** — Session 2d.

---

## Phase 3.1a Migration Status (2026-07-30) — data layer landed

| Domain          | Collection                        | Mongo rows | PG table                              | PG rows | Backfilled | Router cutover |
| --------------- | --------------------------------- | ---------- | ------------------------------------- | ------- | ---------- | -------------- |
| Identity        | `users`                           | 1219       | `auth_users`                          | 1375    | ✅ (Session 2b + `pg_bootstrap`) | ✅ Auth stack (Sessions 2a/2b/2c) — non-auth reads pending (Phase 3.1b) |
| Patients        | `clients`                         | 1584       | `emr_clients` (extended)              | 1584    | ✅          | ⛔ Phase 3.1b   |
| Patients        | `intake_forms`                    | 2          | `emr_intake_forms`                    | 2       | ✅          | ⛔ Phase 3.1b   |
| Patients        | `intakes`                         | 0          | (merged into `emr_intake_forms`)      | 0       | n/a        | ⛔ Phase 3.1b   |
| Patients        | `supplement_sheets`               | 76         | `emr_supplement_sheets`               | 76      | ✅          | ⛔ Phase 3.1b   |
| Patients        | `client_supplement_assignments`   | 97         | `emr_client_supplement_assignments`   | 97      | ✅          | ⛔ Phase 3.1b   |
| Patients        | `password_reset_tokens`           | 0          | `emr_legacy_password_reset_tokens`    | 0       | n/a (empty) | ⛔ Phase 3.1b (portal_ops) |

**Alembic**: forward-only revision `e4a80693e8d6`. Renamed `auth_clients` →
`emr_clients` and added 20+ columns + 3 new side tables + the legacy
staff-side reset-token table. No prior migration modified.

**Backfill script**: `backend/scripts/phase3_1_backfill.py` (idempotent,
resumable, dry-run capable, deduplicates NMS-CUSTOM MRN, NULL-ifies
orphan `user_id` / `assigned_practitioner_id` FKs so the demo test data
imports cleanly).

**Row-count reconciliation** — all 4 non-empty collections
match Mongo exactly. 84 client rows had orphan user_ids nulled during
import (dev-only test artifacts). 2 rows had their MRN nulled to satisfy
the unique constraint (both were `NMS-CUSTOM` demo dupes).

### Phase 3.1b — Router cutover (next session)

The data layer is landed; the app still READS from Mongo for the
patient/client domain. Phase 3.1b must:

1. Add repositories: `repositories/clients.py`, `repositories/intake.py`,
   `repositories/supplements.py`, `repositories/legacy_password_reset.py`.
2. Cutover files (in this order — leaf routers first, then `server.py`
   seed, then `deps.py`):
   - `deps.py::_resolve_self_client` → PG
   - `routers/clients.py` (largest surface — client CRUD + intake + files)
   - `routers/portal_ops.py` (staff CRUD + password_reset_tokens)
   - `routers/campaign_extras.py` (client segmentation)
   - `routers/campaigns.py` (client audience)
   - `routers/telehealth.py` (client lookup during video calls)
   - `routers/appointments.py` (client lookup during scheduling)
   - `routers/ops.py` (front desk client search)
   - `routers/lab_review.py` (client attribution)
   - `routers/tasks.py` (client link on tasks)
   - `routers/health_track.py` (labs/messages client attribution)
   - `routers/delegations.py` (user directory)
   - `routers/permissions.py` (user directory)
   - `routers/admin.py::dashboard_stats` (client + note counts)
   - `routers/auth_impl/registration.py::register` (client row insert)
   - `routers/auth_impl/profile.py::update_me` (client mirror)
   - `server.py::seed_demo` (client seed)
3. Test file `test_session3_1_clients.py` + full auth regression.
4. Drop `db.clients`, `db.intake_forms`, `db.intakes`, `db.supplement_sheets`,
   `db.client_supplement_assignments`, `db.password_reset_tokens`, `db.users`.
5. Verify collections don't come back after startup + traffic.

_Last updated: 2026-07-30 (Phase 3.1a · Data layer landed)_

- **Passkeys / WebAuthn** — post-2d, standalone.
- **GridFS → S3/MinIO** — capital project after Session 3.7.
- **Retiring `mongo_db.py` entirely** — impossible until GridFS is
  replaced (see above).
- **Front-end changes** — every domain migration MUST keep the JSON
  contract byte-identical.

_Compiled 2026-07-30 · analysis-only session · no code changed._


---

## Phase 3.4b — Runtime Cutover via Motor-Compat Adapter (2026-08-01)

**Strategy**: Adapter-only. `motor_compat_pg.MotorCompatDb` wraps the Motor
`db` handle re-exported by `deps.py`. Reads/writes to the 8 retired
collections transparently route to PostgreSQL. Routers are untouched.

**Retired collections (dropped, non-regenerative):**
- messages
- message_threads
- form_templates
- form_submissions
- soap_templates
- lab_values
- treatment_plans
- treatments

**Schema additions (Alembic `a1b2c3d4e5f6`):**
- Added JSONB `payload NOT NULL DEFAULT '{}'` to each of the 8 tables to
  carry router-provided fields that aren't first-class columns.
- Relaxed `emr_lab_values.marker` NOT NULL (router writes `test_name` into
  payload instead).

**Adapter contract:**
- Full `find / find_one / insert_one / insert_many / update_one /
  update_many / find_one_and_update / delete_one / delete_many /
  count_documents / distinct` surface.
- Cursor `.sort().limit().skip().to_list()` + async iteration.
- Mongo operators: `$in`, `$nin`, `$ne`, `$gt/$gte/$lt/$lte`, `$exists`,
  `$regex/$options`, `$or`, `$set`, `$unset`, `$inc`, `$push`, `$addToSet`
  (incl. `$each`), `$pull`, upsert.
- Type-safe JSONB equality via `payload @> {"key": val}` containment for
  booleans/numbers/strings.
- No Mongo fallback for these 8 collections — `MotorCompatDb._RETIRED`
  entries always resolve through `MotorCompatCollection`.

**Verification:**
- Alembic head: `a1b2c3d4e5f6` (up from `8ae0b2901822`).
- 20/20 Phase 3.1b–3.4 smoke tests pass (`test_session3_1_clients.py`,
  `test_session3_2_scheduling.py`, `test_session3_3_clinical.py`,
  `test_session3_4_messaging.py`).
- New test file `tests/test_session3_4_messaging.py` (6 tests) exercises
  treatments catalog, form templates + submissions, SOAP templates,
  messages + threads (incl. push + addToSet), lab values (incl. review
  status + attach/detach), and treatment plans.
- Legacy `conftest.py::_ensure_builtin_form_templates` fixture neutered —
  it previously reseeded Mongo `form_templates` via raw pymongo. Runtime
  seeds now flow through the adapter (blocked by `DEMO_SEED_DISABLE=1`).
- Post-restart regen check: **0 of 8** retired collections regenerate.

**Remaining Motor imports (runtime):** `deps.py` (wraps + re-exports),
`mongo_db.py` (still owns non-retired collections + GridFS).

_Last updated: 2026-08-01 (Phase 3.4b · Adapter cutover complete)_



---

## Phase 3.5 — CRM & Operations Cutover (2026-08-01)

**Strategy**: Extend the `motor_compat_pg` adapter with 7 new tables. No
router edits required — the adapter's generic JSONB payload approach
handles every field the routers write.

**Retired collections (dropped, non-regenerative):**
- campaigns
- front_desk_visits
- internal_tasks
- integration_log
- protocol_enrollments
- protocol_templates
- files (metadata only; GridFS `emr_files.chunks` / `emr_files.files` remain
  in Mongo — capital-project S3 cutover deferred)

**Schema additions (Alembic `b2c3d4e5f6a7`):**
- New table `emr_campaigns` (id + created_at + payload).
- New table `emr_front_desk_visits` (adds typed `client_id` FK + index).
- New table `emr_internal_tasks` (adds typed `status` index + `due_date`
  for dashboard-summary range filters).
- New table `emr_integration_log` (id + created_at + payload).
- New table `emr_protocol_enrollments` (adds typed `client_id`,
  `practitioner_id`, `status` indices).
- New table `emr_protocol_templates` (id + created_at + payload).
- New table `emr_file_meta` (adds typed `client_id`, `deleted_at` indices;
  metadata-only — GridFS blob storage untouched).
- Models exported via `postgres_models/crm_and_ops.py`.

**Adapter changes:**
- `motor_compat_pg._MODEL_BY_NAME` extended with the 7 new mappings.
- `MotorCompatDb._RETIRED` now covers 15 collections total (8 from
  Phase 3.4b + 7 from Phase 3.5). No Mongo fallback for any of them.

**Router edits:** none. Every existing `db.campaigns.*`,
`db.front_desk_visits.*`, `db.internal_tasks.*`, `db.integration_log.*`,
`db.protocol_enrollments.*`, `db.protocol_templates.*`, `db.files.*` call
transparently routes to PostgreSQL.

**Verification:**
- Alembic head: `b2c3d4e5f6a7` (up from `a1b2c3d4e5f6`).
- 26/26 Phase 3.1b–3.5 smoke tests pass (test_session3_1_clients ×6,
  test_session3_2_scheduling ×6, test_session3_3_clinical ×2,
  test_session3_4_messaging ×6, test_session3_5_crm_ops ×6).
- New test file `tests/test_session3_5_crm_ops.py` covers campaign
  create+list, task create+list+dashboard-summary+update+delete, protocol
  template + enrollment lifecycle, front-desk check-in + today + update,
  file upload metadata + list + soft-delete, and integration_log
  insertion via the adapter.
- One legacy test drift fixed: `test_session3_4_messaging.py` now writes
  its fake file record via the adapter (was previously pymongo-direct;
  since `files` is now PG-only, the router lookup was 404-ing).
- Post-restart regen check: **0 of 15** retired collections regenerate.

_Last updated: 2026-08-01 (Phase 3.5 · CRM & Operations Adapter cutover)_



---

## Phase 3.6 — Remaining Structured-Data Cutover (2026-08-01)

**Strategy**: Extend the `motor_compat_pg` adapter with 28 new tables +
retire 8 empty index shells left behind by earlier phases. No router
edits, no repository additions. The generic `id + created_at + payload`
schema (with select typed columns promoted where router filters need
indexes) covers every access pattern.

**Retired collections (28, dropped, non-regenerative):**
- Accounting: `chart_of_accounts`, `journal_entries`, `transactions`,
  `expenses`, `invoices`, `vendor_bills`, `vendors`,
  `accounting_backfill_runs`, `accounting_events`
- Banking: `bank_accounts`, `bank_import_batches`, `bank_transactions`,
  `bank_transfers`, `imported_batches`, `reconciliations`
- Payroll: `employees`, `payroll_runs`, `time_entries`
- Inventory: `inventory_items`, `inventory_transactions`
- Legal: `baa_records`, `legal_acceptances`, `legal_policies`
- Security: `breakglass_sessions`
- Ops/Infra: `posting_dead_letters`, `vip_list`, `ws_tickets`,
  `user_sessions`

**Empty shells removed (8):** `users`, `clients`, `appointments`,
`visit_notes`, `clinical_delegations`, `push_subscriptions`,
`live_soap_drafts`, `visit_chat`. Confirmed zero runtime references
before dropping.

**Schema additions (Alembic `c3d4e5f6a7b8`):**
- 28 new tables in `postgres_models/structured_rest.py` following the
  Phase 3.5 pattern (`id` PK + `created_at` indexed + `payload` JSONB +
  `legacy_mongo_id`).
- Typed indexed columns promoted where routers filter/sort:
  - `emr_chart_of_accounts` — `code`, `active`
  - `emr_transactions` — `client_id`, `status`
  - `emr_accounting_events` — `idempotency_key`
  - `emr_bank_accounts` — `active`
  - `emr_bank_transactions` — `bank_account_id`, `reconciliation_id`
  - `emr_reconciliations` — `bank_account_id`
  - `emr_time_entries`, `emr_legal_acceptances`,
    `emr_breakglass_sessions`, `emr_user_sessions_legacy` — `user_id`
  - `emr_legal_policies` — `slug`
  - `emr_ws_tickets` — `expires_at`
- No PG tables dropped; earlier migration history untouched.

**Adapter changes:**
- `motor_compat_pg._MODEL_BY_NAME` extended from 15 → 43 entries.
- `MotorCompatDb._RETIRED` therefore covers all 43 retired collections.
  Any `db.<retired>` access resolves to `MotorCompatCollection`
  unconditionally — no Mongo fallback.
- No new adapter operations needed; existing `find / find_one /
  find_one_and_update / insert_one / update_one / update_many /
  delete_one / delete_many / count_documents / distinct` plus operators
  (`$in`, `$ne`, `$gt/$gte/$lt/$lte`, `$exists`, `$regex`, `$or`, `$set`,
  `$unset`, `$inc`, `$push`, `$addToSet`, `$pull`, upsert) covered every
  call site.

**Router edits:** none.

**Verification:**
- Alembic head: `c3d4e5f6a7b8` (up from `b2c3d4e5f6a7`).
- 35/35 Phase 3.1b–3.6 smoke tests pass (35 = 6 + 6 + 2 + 6 + 6 + 9).
- New test file `tests/test_session3_6_structured_rest.py` covers:
  accounts + journal entries, transactions + expenses, invoices + vendor
  bills + vendors, bank account/import batch/transactions/transfer/
  reconciliation flow, employee + payroll_run + time_entry flow,
  inventory item + adjustment (via `/inventory/{id}/adjust` HTTP), legal
  policy + acceptance + BAA, break-glass + WS ticket persistence with
  `find_one_and_update` semantics, accounting events + dead-letter +
  backfill runs + VIP list + imported batches.
- Post-restart regen check: **0 of 43** retired collections regenerate.
  Only `emr_files.chunks` / `emr_files.files` remain in Mongo (GridFS
  blob storage, explicitly excluded from this phase).

**Remaining Motor imports (runtime):** `deps.py` (wraps + re-exports),
`mongo_db.py` (still owns GridFS + the raw Motor client). Everything
else — every router — reads/writes exclusively via PG through the
adapter.

_Last updated: 2026-08-01 (Phase 3.6 · Structured data fully on PG)_



---

## Phase 3.7 — GridFS retirement + full Mongo removal (2026-08-01)

**Strategy**: Introduce an async `Storage` abstraction with two backends
(`FilesystemStorage`, `S3Storage`); migrate blobs from GridFS via a
resumable backfill script; cut all runtime blob I/O in `routers/clients`
and `routers/telehealth` to `storage.get_storage()`; delete `mongo_db.py`;
strip the Motor fallback from `MotorCompatDb` so unknown-collection
access raises loudly instead of hitting Mongo; verify boot with
`MONGO_URL` unset/unreachable.

**Structured-data stragglers migrated (5 tables):**
`memberships`, `campaign_templates`, `campaign_unsubscribes`,
`forms` (`emr_forms_legacy`), `symptom_logs`. Same JSONB-payload pattern
as Phases 3.5/3.6. Cumulative retired-collection registration in
`motor_compat_pg._MODEL_BY_NAME` is now **48** entries.

**GridFS retirement:**
- Dropped `emr_files.files` + `emr_files.chunks` (6 blobs × 21 bytes,
  snapshot at `/tmp/gridfs_pre_drop_snapshot.json`).
- 6/6 blobs backfilled via `scripts/backfill_gridfs_to_storage.py` with
  checksum reconciliation clean.
- `mongo_db.py` deleted. `deps.py` no longer imports Motor.
- `MotorCompatDb` no longer holds a Motor client — unknown-collection
  access raises `AttributeError` instead of silent Mongo fallback.

**Schema additions (Alembic `d4e5f6a7b8c9`):**
- 6 new columns on `emr_file_meta`: `storage_backend`, `storage_key`
  (indexed), `bucket`, `version_id`, `legacy_gridfs_id` (indexed),
  `retention_hold_until`.
- 5 new tables for the remaining collections.

**Files added:**
- `backend/storage/__init__.py` — `get_storage()` factory + re-exports.
- `backend/storage/base.py` — `Storage` protocol, `ObjectMetadata`,
  `NotFound`, `StorageError`.
- `backend/storage/filesystem.py` — sandbox / dev / test backend.
- `backend/storage/s3.py` — S3 backend with SSE-KMS, streaming multipart,
  presigned URLs; imports boto3 lazily.
- `backend/scripts/backfill_gridfs_to_storage.py` — idempotent, resumable
  backfill with `--dry-run`, `--resume`, `--limit`.
- `backend/tests/test_session3_7_storage.py` — 7 smoke tests.
- `backend/alembic/versions/2026_08_01_0400-d4e5f6a7b8c9_*.py`.
- `memory/PHASE_3_7_DEPLOYMENT.md` — EC2 deployment + rollback runbook.

**Files changed:**
- `backend/routers/clients.py` — upload/download go through the storage
  adapter; unmigrated legacy rows return 410.
- `backend/routers/telehealth.py` — visit recording upload/download go
  through the storage adapter; legacy path returns 410.
- `backend/routers/campaigns.py` — remove `from pymongo import
  ReturnDocument` (replaced with a local truthy constant).
- `backend/server.py` — remove unused `bson.ObjectId` import + `fs_bucket`
  from `deps` imports; `close_mongo` is now a no-op shim.
- `backend/routers/ops.py` — remove unused `bson.ObjectId` import.
- `backend/motor_compat_pg.py` — remove Motor fallback; unknown
  collections raise.
- `backend/deps.py` — remove `mongo_db` import; provide no-op
  `close_mongo` shim; `db = MotorCompatDb()` (no arg).
- `backend/postgres_models/crm_and_ops.py` — `FileMeta` gains six
  storage-backend columns.
- `backend/postgres_models/structured_rest.py` — 5 new models.
- `backend/postgres_models/__init__.py` — export new models.
- `backend/.env` — add `STORAGE_BACKEND`, `STORAGE_FS_ROOT`,
  `S3_BUCKET_NAME`, `S3_KMS_KEY_ARN`, `S3_PRESIGN_EXPIRES_SECONDS`.
- `backend/mongo_db.py` — **deleted**.

**Packages installed:** `boto3==1.34.162`, `botocore==1.34.162`,
`s3transfer==0.10.4`. `motor` + `pymongo` are still installed but no
longer imported at runtime (only by the backfill script and tests).

**Env changes:**
- Added: `STORAGE_BACKEND`, `STORAGE_FS_ROOT`, `S3_BUCKET_NAME`,
  `S3_KMS_KEY_ARN`, `S3_PRESIGN_EXPIRES_SECONDS`, `AWS_ACCESS_KEY_ID` /
  `AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN` (dev only; prod uses
  instance profile).
- No longer required at runtime: `MONGO_URL`, `DB_NAME`.

**Verification:**
- Alembic head: `d4e5f6a7b8c9`.
- 42/42 smoke tests pass (6+6+2+6+6+9+7).
- Backend boots + serves `/api/health` with `MONGO_URL` unset **and**
  with `MONGO_URL` pointed at an unreachable host.
- No runtime Motor / PyMongo / GridFS / `fs_bucket` imports remain.
- Mongo collections after restart: **0**. Zero regeneration.

_Last updated: 2026-08-01 (Phase 3.7 · MongoDB fully retired)_

