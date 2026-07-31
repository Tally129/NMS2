# Session 3 — PostgreSQL Migration Inventory

> Analysis-only session. No code was modified. This is the source-of-truth
> plan for Sessions 3a → 3g (per-domain migrations). Every subsequent
> session should carve out ONE row from the batch table below and treat it
> as its entire scope.

**Snapshot date**: 2026-07-31 (Phase 3.1b runtime cutover complete)
**Branch**: `auth-remove-google`
**Last commit**: (about to commit Phase 3.1b)
**Alembic head**: `b7e2c4d9a1f8`

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
