"""Phase 14 Marketing OS controlled execution models."""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from postgres_db import Base


class MarketingExecutionRequest(Base):
    __tablename__ = "marketing_execution_requests"

    id = Column(String, primary_key=True)

    provider = Column(String(64), nullable=False)
    action_type = Column(String(100), nullable=False)

    target_type = Column(String(100), nullable=False)
    target_id = Column(String(255), nullable=True)

    idempotency_key = Column(
        String(255),
        nullable=False,
        unique=True,
    )

    request_payload = Column(
        JSONB,
        nullable=False,
        default=dict,
    )

    dry_run = Column(
        Boolean,
        nullable=False,
        default=True,
    )

    status = Column(
        String(32),
        nullable=False,
        default="draft",
    )

    human_approval_required = Column(
        Boolean,
        nullable=False,
        default=True,
    )

    approved_by = Column(
        String,
        ForeignKey("auth_users.id"),
        nullable=True,
    )

    approved_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    executed_by = Column(
        String,
        ForeignKey("auth_users.id"),
        nullable=True,
    )

    executed_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_by = Column(
        String,
        ForeignKey("auth_users.id"),
        nullable=True,
    )

    failure_code = Column(
        String(100),
        nullable=True,
    )

    failure_message = Column(
        Text,
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_marketing_execution_requests_idempotency_key",
        ),
    )


class MarketingExecutionApproval(Base):
    __tablename__ = "marketing_execution_approvals"

    id = Column(String, primary_key=True)

    execution_request_id = Column(
        String,
        ForeignKey(
            "marketing_execution_requests.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    decision = Column(
        String(32),
        nullable=False,
    )

    reason = Column(
        Text,
        nullable=True,
    )

    decided_by = Column(
        String,
        ForeignKey("auth_users.id"),
        nullable=False,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class MarketingExecutionAttempt(Base):
    __tablename__ = "marketing_execution_attempts"

    id = Column(String, primary_key=True)

    execution_request_id = Column(
        String,
        ForeignKey(
            "marketing_execution_requests.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    attempt_number = Column(
        Integer,
        nullable=False,
        default=1,
    )

    provider = Column(
        String(64),
        nullable=False,
    )

    dry_run = Column(
        Boolean,
        nullable=False,
        default=True,
    )

    status = Column(
        String(32),
        nullable=False,
    )

    request_snapshot = Column(
        JSONB,
        nullable=False,
        default=dict,
    )

    response_snapshot = Column(
        JSONB,
        nullable=True,
    )

    error_code = Column(
        String(100),
        nullable=True,
    )

    error_message = Column(
        Text,
        nullable=True,
    )

    started_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    finished_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )


class MarketingProviderExecutionPolicy(Base):
    __tablename__ = "marketing_provider_execution_policies"

    id = Column(String, primary_key=True)

    provider = Column(
        String(64),
        nullable=False,
        unique=True,
    )

    enabled = Column(
        Boolean,
        nullable=False,
        default=False,
    )

    dry_run_only = Column(
        Boolean,
        nullable=False,
        default=True,
    )

    human_approval_required = Column(
        Boolean,
        nullable=False,
        default=True,
    )

    allowed_actions = Column(
        JSONB,
        nullable=False,
        default=list,
    )

    created_by = Column(
        String,
        ForeignKey("auth_users.id"),
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
