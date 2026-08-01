"""Local-development-only demo user seed.

This script is NOT invoked from application startup. It must be run
explicitly from a developer workstation. It refuses to run in any
environment that looks like production:

    * HIPAA_MODE=true         → refuse
    * ENVIRONMENT=production  → refuse
    * CONFIRM_DEMO_SEED != YES → refuse

By default it generates a fresh random password for each demo account
and prints them to stdout ONCE. Pass `--fixed-passwords` to seed the
legacy fixture passwords used by the pytest suite; that path is intended
for CI / local test loops and refuses to run unless HIPAA_MODE=false.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import secrets
import string
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from auth_utils import hash_password
from models import new_id
from pg_shims import find_user_by_email, insert_user

log = logging.getLogger("seed-demo-users")


# Fixture passwords are ONLY used with --fixed-passwords and ONLY read by
# the pytest suite. They are documented in tests/, not runtime code.
_FIXTURE_ACCOUNTS = [
    ("admin@natmedsol.local",     "Admin!2345",     "admin",             "Site Administrator"),
    ("ravello@natmedsol.local",   "Ravello!2345",   "practitioner",      "Dr. Gail Ravello"),
    ("frontdesk@natmedsol.local", "FrontDesk!2345", "staff",             "Front Desk Staff"),
    ("auditor@natmedsol.local",   "Auditor!2345",   "auditor",           "Compliance Auditor"),
    ("ma@natmedsol.local",        "MedAssist!2345", "medical_assistant", "Morgan Assistant"),
]
# Emails without their fixture passwords — used when generating random creds.
_DEMO_EMAILS_AND_ROLES = [
    (email, role, name) for email, _pw, role, name in _FIXTURE_ACCOUNTS
]


def _random_password() -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(20))


def _refuse_production_environment(fixed_passwords: bool):
    hipaa = os.environ.get("HIPAA_MODE", "false").lower() in {"1", "true", "yes", "on"}
    env = (os.environ.get("ENVIRONMENT") or "").strip().lower()
    confirm = (os.environ.get("CONFIRM_DEMO_SEED") or "").strip().upper()

    if env == "production":
        raise SystemExit("Refusing to seed demo users: ENVIRONMENT=production")
    if hipaa:
        raise SystemExit("Refusing to seed demo users: HIPAA_MODE is on")
    if confirm != "YES":
        raise SystemExit(
            "Refusing to seed demo users without CONFIRM_DEMO_SEED=YES in env"
        )
    if fixed_passwords and hipaa:
        raise SystemExit(
            "--fixed-passwords is only permitted when HIPAA_MODE=false"
        )


async def seed(fixed_passwords: bool):
    now = datetime.now(timezone.utc)
    created = []
    if fixed_passwords:
        rows = [(e, pw, r, name) for (e, pw, r, name) in _FIXTURE_ACCOUNTS]
    else:
        rows = [(e, _random_password(), r, name)
                for (e, r, name) in _DEMO_EMAILS_AND_ROLES]

    for email, password, role, full_name in rows:
        existing = await find_user_by_email(email)
        if existing:
            log.info("skipped (already exists): %s", email)
            continue
        await insert_user({
            "id": new_id(), "email": email,
            "password_hash": hash_password(password),
            "full_name": full_name, "phone": None, "role": role,
            "mfa_enabled": False, "mfa_secret": None,
            "is_active": True, "created_at": now, "last_login_at": None,
        })
        created.append((email, password, role))

    print()
    print("=" * 72)
    print(" DEMO USERS SEEDED — copy the passwords now; they are not stored.")
    print("=" * 72)
    for email, password, role in created:
        print(f"  {email:<32} {role:<20} {password}")
    if not created:
        print("  (no new accounts — all demo emails already existed)")
    print("=" * 72)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fixed-passwords", action="store_true",
                     help="Use fixture passwords documented in tests/ (CI only).")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _refuse_production_environment(args.fixed_passwords)
    asyncio.run(seed(fixed_passwords=args.fixed_passwords))


if __name__ == "__main__":
    main()
