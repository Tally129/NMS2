"""phase 3.1 clients and patient profile

Revision ID: e4a80693e8d6
Revises: 62cd2e365fc9
Create Date: 2026-07-31 00:06:29.083809

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e4a80693e8d6'
down_revision: Union[str, Sequence[str], None] = '62cd2e365fc9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Phase 3.1 — rename auth_clients -> emr_clients, add all Mongo
    clients fields, and create the three patient-profile side tables
    (intake_forms, supplement_sheets, client_supplement_assignments) plus
    the legacy staff-side password_reset_tokens rehoming table.
    Forward-only.
    """
    # 1. Extend the Client table.
    op.rename_table("auth_clients", "emr_clients")
    with op.batch_alter_table("emr_clients") as batch:
        batch.add_column(sa.Column("mrn", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("alt_phone", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("dob", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("sex", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("gender_identity", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("pronouns", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("marital_status", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("language", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("referral_source", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("assigned_practitioner_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("photo_file_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("primary_concern", sa.String(), nullable=True))
        batch.add_column(sa.Column("notes", sa.String(), nullable=True))
        batch.add_column(sa.Column("consent_marketing", sa.Boolean(),
                                    nullable=False, server_default=sa.text("false")))
        batch.add_column(sa.Column("consent_photo", sa.Boolean(),
                                    nullable=False, server_default=sa.text("false")))
        batch.add_column(sa.Column("consent_telehealth", sa.Boolean(),
                                    nullable=False, server_default=sa.text("false")))
        batch.add_column(sa.Column("comms_pref", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("address", postgresql.JSONB(), nullable=True))
        batch.add_column(sa.Column("emergency_contact", postgresql.JSONB(), nullable=True))
        batch.add_column(sa.Column("allergies", postgresql.JSONB(), nullable=True))
        batch.add_column(sa.Column("dietary_restrictions", postgresql.JSONB(), nullable=True))
        batch.add_column(sa.Column("wellness_goals", postgresql.JSONB(), nullable=True))
        batch.add_column(sa.Column("current_supplements", postgresql.JSONB(), nullable=True))
        batch.add_column(sa.Column("legacy_mongo_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_emr_clients_mrn", "emr_clients", ["mrn"], unique=True,
                    postgresql_where=sa.text("mrn IS NOT NULL"))
    op.create_index("ix_emr_clients_assigned_practitioner_id",
                    "emr_clients", ["assigned_practitioner_id"])
    op.create_index("ix_emr_clients_intake_completed", "emr_clients", ["intake_completed"])
    op.create_index("ix_emr_clients_legacy_mongo_id", "emr_clients", ["legacy_mongo_id"])
    op.create_foreign_key(
        "fk_emr_clients_assigned_practitioner",
        "emr_clients", "auth_users",
        ["assigned_practitioner_id"], ["id"], ondelete="SET NULL",
    )

    # 2. emr_intake_forms
    op.create_table(
        "emr_intake_forms",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("demographics", postgresql.JSONB(), nullable=True),
        sa.Column("health_history", postgresql.JSONB(), nullable=True),
        sa.Column("lifestyle", postgresql.JSONB(), nullable=True),
        sa.Column("symptoms", postgresql.JSONB(), nullable=True),
        sa.Column("consent", postgresql.JSONB(), nullable=True),
        sa.Column("legacy_mongo_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["client_id"], ["emr_clients.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("client_id", name="uq_emr_intake_forms_client_id"),
    )

    # 3. emr_supplement_sheets
    op.create_table(
        "emr_supplement_sheets",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.String(), nullable=True),
        sa.Column("items", postgresql.JSONB(), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("created_by_name", sa.String(length=200), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("legacy_mongo_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["auth_users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_emr_supplement_sheets_active", "emr_supplement_sheets", ["active"])

    # 4. emr_client_supplement_assignments
    op.create_table(
        "emr_client_supplement_assignments",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("sheet_id", sa.String(length=64), nullable=True),
        sa.Column("sheet_title", sa.String(length=255), nullable=True),
        sa.Column("sheet_summary", sa.String(), nullable=True),
        sa.Column("items_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("note_ids", postgresql.JSONB(), nullable=True),
        sa.Column("assigned_by_id", sa.String(length=64), nullable=True),
        sa.Column("assigned_by_name", sa.String(length=200), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_referenced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_by_id", sa.String(length=64), nullable=True),
        sa.Column("legacy_mongo_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["client_id"], ["emr_clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sheet_id"], ["emr_supplement_sheets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assigned_by_id"], ["auth_users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_emr_client_supplement_assignments_client",
                    "emr_client_supplement_assignments", ["client_id", "active"])

    # 5. emr_legacy_password_reset_tokens (portal_ops staff-side)
    op.create_table(
        "emr_legacy_password_reset_tokens",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["auth_users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("token_hash", name="uq_emr_legacy_prt_token_hash"),
    )
    op.create_index("ix_emr_legacy_prt_user_id",
                    "emr_legacy_password_reset_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_emr_legacy_prt_user_id", table_name="emr_legacy_password_reset_tokens")
    op.drop_table("emr_legacy_password_reset_tokens")
    op.drop_index("ix_emr_client_supplement_assignments_client",
                  table_name="emr_client_supplement_assignments")
    op.drop_table("emr_client_supplement_assignments")
    op.drop_index("ix_emr_supplement_sheets_active", table_name="emr_supplement_sheets")
    op.drop_table("emr_supplement_sheets")
    op.drop_table("emr_intake_forms")
    op.drop_constraint("fk_emr_clients_assigned_practitioner", "emr_clients", type_="foreignkey")
    op.drop_index("ix_emr_clients_legacy_mongo_id", table_name="emr_clients")
    op.drop_index("ix_emr_clients_intake_completed", table_name="emr_clients")
    op.drop_index("ix_emr_clients_assigned_practitioner_id", table_name="emr_clients")
    op.drop_index("ix_emr_clients_mrn", table_name="emr_clients")
    with op.batch_alter_table("emr_clients") as batch:
        for col in ("updated_at", "legacy_mongo_id", "current_supplements", "wellness_goals",
                    "dietary_restrictions", "allergies", "emergency_contact", "address",
                    "comms_pref", "consent_telehealth", "consent_photo", "consent_marketing",
                    "notes", "primary_concern", "photo_file_id", "assigned_practitioner_id",
                    "referral_source", "language", "marital_status", "pronouns",
                    "gender_identity", "sex", "dob", "alt_phone", "mrn"):
            batch.drop_column(col)
    op.rename_table("emr_clients", "auth_clients")
