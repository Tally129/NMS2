"""phase 3.5 crm and operations tables

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-01 02:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_generic_table(name: str, extra_cols=()):
    cols = [
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                    server_default=sa.text("now()"), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()),
                    nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("legacy_mongo_id", sa.String(length=64), nullable=True),
    ]
    cols.extend(extra_cols)
    op.create_table(name, *cols)
    op.create_index(f"ix_{name}_created_at", name, ["created_at"])


def upgrade() -> None:
    _create_generic_table("emr_campaigns")

    _create_generic_table(
        "emr_front_desk_visits",
        (
            sa.Column("client_id", sa.String(length=64), nullable=True),
            sa.ForeignKeyConstraint(["client_id"], ["emr_clients.id"],
                                     ondelete="SET NULL"),
        ),
    )
    op.create_index("ix_emr_front_desk_visits_client_id",
                     "emr_front_desk_visits", ["client_id"])

    _create_generic_table(
        "emr_internal_tasks",
        (
            sa.Column("status", sa.String(length=32), nullable=True),
            sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        ),
    )
    op.create_index("ix_emr_internal_tasks_status",
                     "emr_internal_tasks", ["status"])

    _create_generic_table("emr_integration_log")

    _create_generic_table(
        "emr_protocol_enrollments",
        (
            sa.Column("client_id", sa.String(length=64), nullable=True),
            sa.Column("practitioner_id", sa.String(length=64), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=True),
            sa.ForeignKeyConstraint(["client_id"], ["emr_clients.id"],
                                     ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["practitioner_id"], ["auth_users.id"],
                                     ondelete="SET NULL"),
        ),
    )
    op.create_index("ix_emr_protocol_enrollments_client_id",
                     "emr_protocol_enrollments", ["client_id"])
    op.create_index("ix_emr_protocol_enrollments_practitioner_id",
                     "emr_protocol_enrollments", ["practitioner_id"])
    op.create_index("ix_emr_protocol_enrollments_status",
                     "emr_protocol_enrollments", ["status"])

    _create_generic_table("emr_protocol_templates")

    _create_generic_table(
        "emr_file_meta",
        (
            sa.Column("client_id", sa.String(length=64), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["client_id"], ["emr_clients.id"],
                                     ondelete="SET NULL"),
        ),
    )
    op.create_index("ix_emr_file_meta_client_id", "emr_file_meta", ["client_id"])
    op.create_index("ix_emr_file_meta_deleted_at", "emr_file_meta", ["deleted_at"])


def downgrade() -> None:
    for name in ("emr_file_meta", "emr_protocol_templates",
                  "emr_protocol_enrollments", "emr_integration_log",
                  "emr_internal_tasks", "emr_front_desk_visits",
                  "emr_campaigns"):
        op.drop_table(name)
