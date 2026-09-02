"""merge appointment archive and marketing phase6 heads

Revision ID: c5d6e7f8a9b0
Revises: apptreqarchive0901, b4c5d6e7f8a9
Create Date: 2026-09-02

This is a graph-only Alembic merge revision.

It intentionally performs no schema changes. It reconciles the authoritative
appointment-request archive migration with the isolated Marketing OS migration
chain after both independently branched from revision c133fd9fc54c.
"""

from __future__ import annotations

revision = "c5d6e7f8a9b0"
down_revision = ("apptreqarchive0901", "b4c5d6e7f8a9")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
