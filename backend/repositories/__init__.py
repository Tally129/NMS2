"""Repository layer for the PostgreSQL auth stack.

Each module exposes small async functions that take an `AsyncSession`
explicitly. They return plain dicts where the auth code expects
Mongo-shape docs (id, role, mfa_enabled, ...), so downstream callers
don't need to change field access.

Transactions are the CALLER's responsibility. Helpers here call
`session.flush()` for identity but do NOT commit — the auth route that
owns a multi-write flow controls the commit boundary.
"""
