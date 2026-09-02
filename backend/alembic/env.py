"""Alembic environment. Loads DATABASE_URL from process env and every
NMS PostgreSQL model so autogenerate sees all tables."""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool
from alembic import context

# --- Path setup: make backend/ importable when Alembic is invoked from anywhere.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Load .env before importing models so DATABASE_URL / secrets are available.
try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND_DIR / ".env")
except Exception:
    pass

# Import ALL models so `Base.metadata` includes every table.
from postgres_models import Base  # noqa: E402,F401
from postgres_models import (  # noqa: E402,F401
    User, Client, UserSession, RefreshToken,
    LoginHistory, LoginContinuation,
    PasswordResetAttempt, PasswordResetToken,
    RecoveryCode,
    IntakeForm, SupplementSheet, ClientSupplementAssignment, LegacyPasswordResetToken,
    AuditLog, SecurityEvent,
)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Resolve DATABASE_URL at runtime. Never bake it into alembic.ini.
db_url = os.environ.get("DATABASE_URL", "").strip()
if not db_url:
    raise RuntimeError("DATABASE_URL is not configured for Alembic")

# Alembic uses a synchronous engine internally. Strip the async driver
# marker so `create_engine` works. We keep the +psycopg suffix — psycopg 3
# is dual-mode (sync + async).
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+psycopg://", 1)
elif db_url.startswith("postgresql://") and "+" not in db_url.split("://", 1)[0]:
    db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)

# `-x db_url=...` on the CLI can override.
x_args = context.get_x_argument(as_dictionary=True)
if x_args.get("db_url"):
    db_url = x_args["db_url"]

config.set_main_option("sqlalchemy.url", db_url)

import postgres_models.terminals  # noqa: F401

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section) or {},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
