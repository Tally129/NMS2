"""add report-level lab records

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-02 22:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "emr_lab_reports",

        sa.Column("id", sa.String(length=64), nullable=False),

        sa.Column("client_id", sa.String(length=64), nullable=True),
        sa.Column("original_file_id", sa.String(length=64), nullable=True),

        sa.Column("source_filename", sa.String(length=255), nullable=True),
        sa.Column("mime_type", sa.String(length=120), nullable=True),

        sa.Column("report_title", sa.String(length=500), nullable=True),
        sa.Column("laboratory_name", sa.String(length=500), nullable=True),
        sa.Column("patient_name_on_report", sa.String(length=500), nullable=True),
        sa.Column("patient_dob_on_report", sa.String(length=100), nullable=True),
        sa.Column("ordering_provider", sa.String(length=500), nullable=True),
        sa.Column("accession_number", sa.String(length=300), nullable=True),

        sa.Column(
            "collection_date",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "reported_date",
            sa.DateTime(timezone=True),
            nullable=True,
        ),

        sa.Column(
            "review_status",
            sa.String(length=32),
            server_default="ai_transcribed",
            nullable=False,
        ),

        sa.Column(
            "assigned_provider_id",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "assigned_provider_name",
            sa.String(length=200),
            nullable=True,
        ),

        sa.Column(
            "review_priority",
            sa.String(length=32),
            nullable=True,
        ),
        sa.Column(
            "review_due_date",
            sa.DateTime(timezone=True),
            nullable=True,
        ),

        sa.Column(
            "document_confidence",
            sa.Float(),
            nullable=True,
        ),

        sa.Column(
            "verified",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "released_to_patient",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),

        sa.Column("approved_by", sa.String(length=64), nullable=True),
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),

        sa.Column("rejected_by", sa.String(length=64), nullable=True),
        sa.Column(
            "rejected_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),

        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("created_by_name", sa.String(length=200), nullable=True),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),

        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),

        sa.ForeignKeyConstraint(
            ["client_id"],
            ["emr_clients.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_provider_id"],
            ["auth_users.id"],
            ondelete="SET NULL",
        ),

        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_emr_lab_reports_client_id",
        "emr_lab_reports",
        ["client_id"],
        unique=False,
    )
    op.create_index(
        "ix_emr_lab_reports_original_file_id",
        "emr_lab_reports",
        ["original_file_id"],
        unique=False,
    )
    op.create_index(
        "ix_emr_lab_reports_accession_number",
        "emr_lab_reports",
        ["accession_number"],
        unique=False,
    )
    op.create_index(
        "ix_emr_lab_reports_collection_date",
        "emr_lab_reports",
        ["collection_date"],
        unique=False,
    )
    op.create_index(
        "ix_emr_lab_reports_review_status",
        "emr_lab_reports",
        ["review_status"],
        unique=False,
    )
    op.create_index(
        "ix_emr_lab_reports_assigned_provider_id",
        "emr_lab_reports",
        ["assigned_provider_id"],
        unique=False,
    )
    op.create_index(
        "ix_emr_lab_reports_review_priority",
        "emr_lab_reports",
        ["review_priority"],
        unique=False,
    )
    op.create_index(
        "ix_emr_lab_reports_review_due_date",
        "emr_lab_reports",
        ["review_due_date"],
        unique=False,
    )
    op.create_index(
        "ix_emr_lab_reports_verified",
        "emr_lab_reports",
        ["verified"],
        unique=False,
    )
    op.create_index(
        "ix_emr_lab_reports_released_to_patient",
        "emr_lab_reports",
        ["released_to_patient"],
        unique=False,
    )
    op.create_index(
        "ix_emr_lab_reports_created_at",
        "emr_lab_reports",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_emr_lab_reports_created_at",
        table_name="emr_lab_reports",
    )
    op.drop_index(
        "ix_emr_lab_reports_released_to_patient",
        table_name="emr_lab_reports",
    )
    op.drop_index(
        "ix_emr_lab_reports_verified",
        table_name="emr_lab_reports",
    )
    op.drop_index(
        "ix_emr_lab_reports_review_due_date",
        table_name="emr_lab_reports",
    )
    op.drop_index(
        "ix_emr_lab_reports_review_priority",
        table_name="emr_lab_reports",
    )
    op.drop_index(
        "ix_emr_lab_reports_assigned_provider_id",
        table_name="emr_lab_reports",
    )
    op.drop_index(
        "ix_emr_lab_reports_review_status",
        table_name="emr_lab_reports",
    )
    op.drop_index(
        "ix_emr_lab_reports_collection_date",
        table_name="emr_lab_reports",
    )
    op.drop_index(
        "ix_emr_lab_reports_accession_number",
        table_name="emr_lab_reports",
    )
    op.drop_index(
        "ix_emr_lab_reports_original_file_id",
        table_name="emr_lab_reports",
    )
    op.drop_index(
        "ix_emr_lab_reports_client_id",
        table_name="emr_lab_reports",
    )

    op.drop_table("emr_lab_reports")
