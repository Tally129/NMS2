"""phase 3.7 s3 storage cutover + final structured-collection stragglers

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-08-01 04:00:00.000000

Adds:
  * Storage-backend metadata columns to `emr_file_meta`
    (`storage_backend`, `storage_key`, `bucket`, `version_id`,
    `legacy_gridfs_id`, `retention_hold_until`) so files can live in
    S3/filesystem instead of GridFS.
  * Five final tables for the remaining runtime Mongo callers so the app
    no longer needs Motor at all (memberships, campaign_templates,
    campaign_unsubscribes, forms_legacy, symptom_logs).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_generic(name: str, extra_cols=(), extra_indexes=()):
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
    for idx_col in extra_indexes:
        op.create_index(f"ix_{name}_{idx_col}", name, [idx_col])


def upgrade() -> None:
    # 1. Storage-backend columns on emr_file_meta
    op.add_column("emr_file_meta",
        sa.Column("storage_backend", sa.String(length=32), nullable=True))
    op.add_column("emr_file_meta",
        sa.Column("storage_key", sa.String(length=512), nullable=True))
    op.add_column("emr_file_meta",
        sa.Column("bucket", sa.String(length=128), nullable=True))
    op.add_column("emr_file_meta",
        sa.Column("version_id", sa.String(length=128), nullable=True))
    op.add_column("emr_file_meta",
        sa.Column("legacy_gridfs_id", sa.String(length=64), nullable=True))
    op.add_column("emr_file_meta",
        sa.Column("retention_hold_until", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_emr_file_meta_storage_key", "emr_file_meta", ["storage_key"])
    op.create_index("ix_emr_file_meta_legacy_gridfs_id",
                     "emr_file_meta", ["legacy_gridfs_id"])

    # 2. Final structured-data stragglers
    _create_generic(
        "emr_memberships",
        (sa.Column("client_id", sa.String(length=64), nullable=True),
         sa.Column("status", sa.String(length=32), nullable=True)),
        extra_indexes=("client_id", "status"),
    )
    _create_generic("emr_campaign_templates")
    _create_generic("emr_campaign_unsubscribes")
    _create_generic("emr_forms_legacy")
    _create_generic(
        "emr_symptom_logs",
        (sa.Column("client_id", sa.String(length=64), nullable=True),),
        extra_indexes=("client_id",),
    )


def downgrade() -> None:
    for name in ("emr_symptom_logs", "emr_forms_legacy",
                  "emr_campaign_unsubscribes", "emr_campaign_templates",
                  "emr_memberships"):
        op.drop_table(name)
    op.drop_index("ix_emr_file_meta_legacy_gridfs_id", table_name="emr_file_meta")
    op.drop_index("ix_emr_file_meta_storage_key", table_name="emr_file_meta")
    for col in ("retention_hold_until", "legacy_gridfs_id", "version_id",
                 "bucket", "storage_key", "storage_backend"):
        op.drop_column("emr_file_meta", col)
