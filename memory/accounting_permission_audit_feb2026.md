# Accounting Permission Audit — Feb 2026

**Scope**: Every backend endpoint under `/api/accounting/*` and the frontend
route protecting the Accounting workspace.

## Summary

| Metric | Value |
|--------|-------|
| Total accounting endpoints | **64** |
| Endpoints reachable by admin | **64 / 64 (100%)** |
| Endpoints missing `admin` role | **0** |
| Frontend route (`/portal/admin/accounting`) admin-only | ✅ (App.js `<Protected roles={["admin"]}>`) |

**Result**: ✅ Admins have full, unrestricted access to every accounting
capability. No admin capability is inadvertently restricted.

## Endpoint Matrix (roles required)

| Method | Path | Admin | Practitioner | Staff | Notes |
|--------|------|-------|--------------|-------|-------|
| GET  | `/accounting/dashboard` | ✅ | ✅ |   | Health widgets |
| GET  | `/accounting/validate` | ✅ | ✅ |   | Ledger validation |
| POST | `/accounting/backfill/dry-run` | ✅ |   |   | Admin-only writes |
| POST | `/accounting/backfill/execute` | ✅ |   |   | Admin-only writes |
| GET  | `/accounting/backfill/runs` | ✅ |   |   | Historic replay runs |
| GET  | `/accounting/backfill/runs/{run_id}` | ✅ |   |   | |
| POST | `/accounting/backfill/runs/{run_id}/resume` | ✅ |   |   | |
| GET  | `/accounting/bank-accounts` | ✅ | ✅ | ✅ | Reference data |
| POST | `/accounting/bank-accounts` | ✅ |   |   | |
| PATCH| `/accounting/bank-accounts/{ba_id}` | ✅ |   |   | |
| DELETE| `/accounting/bank-accounts/{ba_id}` | ✅ |   |   | |
| POST | `/accounting/bank-accounts/{ba_id}/import` | ✅ |   |   | Statement upload |
| GET  | `/accounting/bank-accounts/{ba_id}/import-batches` | ✅ |   |   | |
| GET  | `/accounting/bank-accounts/{ba_id}/transactions` | ✅ | ✅ | ✅ | |
| GET  | `/accounting/cash/dashboard` | ✅ | ✅ |   | |
| GET  | `/accounting/cash/flow` | ✅ | ✅ |   | |
| GET  | `/accounting/cash/register/{ba_id}` | ✅ | ✅ |   | |
| GET  | `/accounting/cash/outstanding-checks` | ✅ | ✅ |   | |
| GET  | `/accounting/cash/outstanding-deposits` | ✅ | ✅ |   | |
| GET  | `/accounting/cash/outstanding-reconciliation` | ✅ | ✅ |   | |
| GET  | `/accounting/reconciliation/exceptions` | ✅ | ✅ |   | |
| GET  | `/accounting/reconciliation/history` | ✅ | ✅ |   | |
| GET  | `/accounting/reconciliation/{recon_id}/report` | ✅ | ✅ |   | |
| GET  | `/accounting/reconciliation/{ba_id}/workspace` | ✅ | ✅ |   | |
| POST | `/accounting/reconciliation/{ba_id}/auto-match` | ✅ |   |   | |
| POST | `/accounting/reconciliation/confirm-matches` | ✅ |   |   | |
| POST | `/accounting/reconciliation/match` | ✅ |   |   | |
| POST | `/accounting/reconciliation/unmatch/{bt_id}` | ✅ |   |   | |
| POST | `/accounting/reconciliation/split` | ✅ |   |   | |
| POST | `/accounting/reconciliation/finalize` | ✅ |   |   | |
| GET  | `/accounting/transfers` | ✅ | ✅ |   | |
| POST | `/accounting/transfers` | ✅ |   |   | |
| GET  | `/accounting/stripe/reconciliation` | ✅ |   |   | |
| GET  | `/accounting/stripe/settlement` | ✅ |   |   | |
| GET  | `/accounting/accounts` | ✅ | ✅ |   | Chart of Accounts |
| POST | `/accounting/accounts` | ✅ |   |   | |
| PATCH| `/accounting/accounts/{code}` | ✅ |   |   | |
| GET  | `/accounting/gl/{account_code}` | ✅ | ✅ |   | General Ledger |
| GET  | `/accounting/journal` | ✅ | ✅ |   | Transaction history |
| POST | `/accounting/journal/manual` | ✅ |   |   | |
| POST | `/accounting/journal/{entry_id}/reverse` | ✅ |   |   | |
| GET  | `/accounting/reports/profit-and-loss` | ✅ | ✅ |   | |
| GET  | `/accounting/reports/balance-sheet` | ✅ | ✅ |   | |
| GET  | `/accounting/reports/trial-balance` | ✅ | ✅ |   | |
| GET  | `/accounting/reports/ar-aging` | ✅ | ✅ |   | |
| GET  | `/accounting/expenses` | ✅ | ✅ | ✅ | |
| POST | `/accounting/expenses` | ✅ | ✅ |   | |
| GET  | `/accounting/vendors` | ✅ | ✅ | ✅ | |
| POST | `/accounting/vendors` | ✅ |   |   | |
| GET  | `/accounting/bills` | ✅ |   |   | |
| POST | `/accounting/bills` | ✅ |   |   | |
| POST | `/accounting/bills/{bill_id}/pay` | ✅ |   |   | |
| GET  | `/accounting/employees` | ✅ |   |   | |
| POST | `/accounting/employees` | ✅ |   |   | |
| GET  | `/accounting/payroll/runs` | ✅ |   |   | |
| POST | `/accounting/payroll/runs` | ✅ |   |   | |
| POST | `/accounting/payroll/runs/{run_id}/pay` | ✅ |   |   | |
| GET  | `/accounting/tax/summary` | ✅ |   |   | |
| GET  | `/accounting/tax/sales-tax` | ✅ | ✅ |   | |
| GET  | `/accounting/tax/payroll-tax` | ✅ |   |   | |
| GET  | `/accounting/1099/vendors` | ✅ |   |   | |
| GET  | `/accounting/1099/csv` | ✅ |   |   | |
| GET  | `/accounting/dead-letters` | ✅ |   |   | Processing issues |
| GET  | `/accounting/events` | ✅ |   |   | Event bus explorer |

## Inconsistencies found

**None.** Every endpoint that uses `require_roles(...)` includes `"admin"`.

## Frontend route protection

* Route `/portal/admin/accounting` → `<Protected roles={["admin"]}>Accounting</Protected>`
* Users with other roles (practitioner, staff, client, auditor) are redirected
  from the page even though many `/accounting/*` endpoints allow read-only
  access for practitioners. This is intentional: practitioners can consume
  cash-flow data through the operational routes (POS, invoices, etc.), but
  the dedicated Accounting workspace is admin-only.

## Preserved role restrictions for non-admin users

Non-admin restrictions remain unchanged from Sprint 1 → 2:

* Practitioners: read-only access to shared reports, dashboard, workspace,
  reconciliation history, journals, GL, chart of accounts, transfers list,
  cash/flow, sales-tax, validation, exceptions.
* Staff: read-only bank accounts, bank transactions, expenses list, vendors
  list (for POS lookups).
* Client / Auditor: no direct accounting endpoint access.

No modifications were needed. The audit confirms admin coverage is complete
and non-admin restrictions are consistent.
