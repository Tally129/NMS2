"""add marketing phase7 funnels qualification and offers

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-09-02 19:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision = "d6e7f8a9b0c1"
down_revision = "c5d6e7f8a9b0"
branch_labels = None
depends_on = None


def _ts():
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def upgrade() -> None:
    op.create_table(
        "marketing_offers",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(160), nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("service_interest", sa.String(160), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "min_qualification_score",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "eligible_locations",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "match_config",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_by",
            sa.String(64),
            sa.ForeignKey("auth_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        *_ts(),
    )
    op.create_unique_constraint(
        "uq_marketing_offers_slug",
        "marketing_offers",
        ["slug"],
    )
    op.create_index(
        "ix_marketing_offers_status",
        "marketing_offers",
        ["status"],
    )
    op.create_index(
        "ix_marketing_offers_service_interest",
        "marketing_offers",
        ["service_interest"],
    )

    op.create_table(
        "marketing_qualification_forms",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(160), nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="draft",
        ),
        sa.Column(
            "schema",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "scoring_rules",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "qualification_config",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_by",
            sa.String(64),
            sa.ForeignKey("auth_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        *_ts(),
    )
    op.create_unique_constraint(
        "uq_marketing_qualification_forms_slug",
        "marketing_qualification_forms",
        ["slug"],
    )
    op.create_index(
        "ix_marketing_qualification_forms_status",
        "marketing_qualification_forms",
        ["status"],
    )

    op.create_table(
        "marketing_funnels",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(160), nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("landing_page", sa.String(512), nullable=True),
        sa.Column(
            "qualification_form_id",
            sa.String(64),
            sa.ForeignKey(
                "marketing_qualification_forms.id",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
        sa.Column(
            "default_offer_id",
            sa.String(64),
            sa.ForeignKey(
                "marketing_offers.id",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
        sa.Column(
            "config",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_by",
            sa.String(64),
            sa.ForeignKey("auth_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        *_ts(),
    )
    op.create_unique_constraint(
        "uq_marketing_funnels_slug",
        "marketing_funnels",
        ["slug"],
    )
    op.create_index(
        "ix_marketing_funnels_status",
        "marketing_funnels",
        ["status"],
    )
    op.create_index(
        "ix_marketing_funnels_form",
        "marketing_funnels",
        ["qualification_form_id"],
    )
    op.create_index(
        "ix_marketing_funnels_offer",
        "marketing_funnels",
        ["default_offer_id"],
    )

    op.create_table(
        "marketing_funnel_steps",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "funnel_id",
            sa.String(64),
            sa.ForeignKey(
                "marketing_funnels.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("step_key", sa.String(96), nullable=False),
        sa.Column("step_type", sa.String(48), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column(
            "config",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        *_ts(),
    )
    op.create_unique_constraint(
        "uq_marketing_funnel_steps_key",
        "marketing_funnel_steps",
        ["funnel_id", "step_key"],
    )
    op.create_index(
        "ix_marketing_funnel_steps_funnel",
        "marketing_funnel_steps",
        ["funnel_id"],
    )
    op.create_index(
        "ix_marketing_funnel_steps_type",
        "marketing_funnel_steps",
        ["step_type"],
    )

    op.create_table(
        "marketing_qualification_submissions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "marketing_subject_id",
            sa.String(128),
            nullable=False,
        ),
        sa.Column(
            "funnel_id",
            sa.String(64),
            sa.ForeignKey(
                "marketing_funnels.id",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
        sa.Column(
            "qualification_form_id",
            sa.String(64),
            sa.ForeignKey(
                "marketing_qualification_forms.id",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column(
            "answers",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "qualification_score",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "qualification_status",
            sa.String(48),
            nullable=False,
        ),
        sa.Column(
            "matched_offer_id",
            sa.String(64),
            sa.ForeignKey(
                "marketing_offers.id",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
        sa.Column(
            "normalized_fields",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_marketing_qualification_submissions_subject",
        "marketing_qualification_submissions",
        ["marketing_subject_id"],
    )
    op.create_index(
        "ix_marketing_qualification_submissions_funnel",
        "marketing_qualification_submissions",
        ["funnel_id"],
    )
    op.create_index(
        "ix_marketing_qualification_submissions_form",
        "marketing_qualification_submissions",
        ["qualification_form_id"],
    )
    op.create_index(
        "ix_marketing_qualification_submissions_status",
        "marketing_qualification_submissions",
        ["qualification_status"],
    )
    op.create_index(
        "ix_marketing_qualification_submissions_offer",
        "marketing_qualification_submissions",
        ["matched_offer_id"],
    )
    op.create_index(
        "ix_marketing_qualification_submissions_submitted",
        "marketing_qualification_submissions",
        ["submitted_at"],
    )


def downgrade() -> None:
    op.drop_table("marketing_qualification_submissions")
    op.drop_table("marketing_funnel_steps")
    op.drop_table("marketing_funnels")
    op.drop_table("marketing_qualification_forms")
    op.drop_table("marketing_offers")
