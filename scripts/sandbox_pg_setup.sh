#!/usr/bin/env bash
# SANDBOX-ONLY: (re)create the local PostgreSQL role/database used by the
# backend, apply Alembic migrations and seed demo users. Never touches
# anything except the local 127.0.0.1 cluster. Idempotent.
set -euo pipefail
cd /app/backend

python - <<'EOF' > /tmp/sandbox_pg_setup.sql
from dotenv import dotenv_values
from urllib.parse import urlparse
u = dotenv_values('/app/backend/.env')['DATABASE_URL'].replace('postgresql+psycopg', 'postgresql')
p = urlparse(u)
assert p.hostname in {'127.0.0.1', 'localhost'}, 'refusing: non-local DATABASE_URL'
pw = (p.password or '').replace("'", "''")
db = p.path.lstrip('/')
user = p.username
print(f"""
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{user}') THEN
    CREATE ROLE {user} LOGIN PASSWORD '{pw}' CREATEDB;
  ELSE
    ALTER ROLE {user} WITH LOGIN PASSWORD '{pw}' CREATEDB;
  END IF;
END $$;
SELECT 'CREATE DATABASE {db} OWNER {user}' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '{db}')\\gexec
""")
EOF
sudo -u postgres psql -v ON_ERROR_STOP=1 -q -f /tmp/sandbox_pg_setup.sql
rm -f /tmp/sandbox_pg_setup.sql

alembic upgrade head > /tmp/alembic_sandbox.log 2>&1 || { tail -20 /tmp/alembic_sandbox.log; exit 1; }
tail -1 /tmp/alembic_sandbox.log
CONFIRM_DEMO_SEED=YES python scripts/seed_demo_users.py --fixed-passwords | tail -2
echo "sandbox postgres ready"
