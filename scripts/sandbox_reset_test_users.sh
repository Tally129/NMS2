#!/usr/bin/env bash
# SANDBOX-ONLY. tests/conftest.py enrolls MFA for every workforce user in the
# configured DB at pytest session start; run this after pytest so the demo
# admin/practitioner can log in to the preview without TOTP.
sudo -u postgres psql -d nms_app -Atc "update auth_users set mfa_enabled=false, mfa_secret=null, mfa_bypass=true where email in ('admin@natmedsol.local','ravello@natmedsol.local');"
