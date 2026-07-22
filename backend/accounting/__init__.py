"""
Accounting package — journals, ledger, posting engine, event bus.

Design principles (from ACCOUNTING_ARCHITECTURE.md):
    • The ONLY writer to `journal_entries` is `post_event()`.
    • Journal entries are immutable; corrections happen via reversing entries.
    • Events carry `idempotency_key` — unique index on `accounting_events`.
    • Every journal entry references its source event by `event_id` — unique index.
    • Money is stored as INTEGER CENTS throughout to avoid float drift.
"""
