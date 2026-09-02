"""Session 2a: Google OAuth removal verification tests."""
import os
import time
import pyotp
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://nms-nurture-phase8.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@natmedsol.local"
ADMIN_PASS = "Admin!2345"
# Try secret from review request first, then fallback to memory file
MFA_SECRETS = [
    "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP",
    "PTF6HBTLIOGPAGZ6ZUSWNXZME34V2GOA",
]


# ---------- Health endpoint ----------
def test_health_no_google_oauth_key():
    r = requests.get(f"{API}/health", timeout=10)
    assert r.status_code == 200
    integrations = r.json().get("integrations", {})
    assert "google_oauth_direct" not in integrations, f"google_oauth_direct still in health: {integrations}"
    assert set(integrations.keys()) == {"llm", "email", "sms"}, f"unexpected keys: {integrations.keys()}"


# ---------- Google OAuth routes return 404 ----------
@pytest.mark.parametrize("method,path", [
    ("GET", "/auth/google/oauth/authorize"),
    ("GET", "/auth/google/oauth/callback"),
    ("POST", "/auth/google/oauth/exchange"),
    ("POST", "/auth/google/session"),
])
def test_google_routes_404(method, path):
    r = requests.request(method, f"{API}{path}", json={}, timeout=10)
    assert r.status_code == 404, f"{method} {path} returned {r.status_code}, expected 404"


# ---------- Password + MFA login flow ----------
def _raw_post(path, json_body):
    """Bypass conftest's requests.post monkey-patch by using urllib directly."""
    import urllib.request, urllib.error, json as _json
    req = urllib.request.Request(
        f"{API}{path}",
        data=_json.dumps(json_body).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "pytest-session2a/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode()
            try:
                parsed = _json.loads(body) if body else {}
            except Exception:
                parsed = {"_raw": body}
            return resp.status, parsed, dict(resp.headers)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            parsed = _json.loads(body) if body else {}
        except Exception:
            parsed = {"_raw": body}
        return e.code, parsed, dict(e.headers or {})


def _login_with_mfa():
    """Uses conftest-patched requests.post which auto-completes MFA."""
    last_resp = None
    for secret in MFA_SECRETS:
        totp = pyotp.TOTP(secret).now()
        r2 = requests.post(
            f"{API}/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASS, "mfa_token": totp},
            timeout=10,
        )
        last_resp = r2
        if r2.status_code == 200 and r2.json().get("access_token"):
            return r2
        time.sleep(0.5)
    # Fallback: rely on conftest auto-MFA (send with no token)
    r2 = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=10)
    if r2.status_code == 200 and r2.json().get("access_token"):
        return r2
    pytest.fail(f"MFA login failed. Last: {last_resp.status_code} {last_resp.text[:300]}")


def test_login_step1_returns_mfa_required():
    """Verify raw step-1 (no mfa_token) returns mfa_required=True."""
    status, body, _ = _raw_post("/auth/login", {"email": ADMIN_EMAIL, "password": ADMIN_PASS})
    assert status == 200, f"login step1 status={status} body={body}"
    assert body.get("mfa_required") is True, f"expected mfa_required=true; got {body}"
    assert "access_token" not in body or not body.get("access_token"), "should not issue token before MFA"


def test_login_password_mfa_flow():
    r2 = _login_with_mfa()
    data = r2.json()
    assert "access_token" in data and data["access_token"]
    assert "refresh_token" not in data, "refresh_token must not appear in JSON body"
    # HttpOnly cookie nms_rt
    assert "nms_rt" in r2.cookies, f"nms_rt cookie missing. cookies={r2.cookies}"


def test_refresh_rotates_cookie():
    r2 = _login_with_mfa()
    old_cookie = r2.cookies.get("nms_rt")
    assert old_cookie
    sess = requests.Session()
    sess.cookies.set("nms_rt", old_cookie)
    r3 = sess.post(f"{API}/auth/refresh", timeout=10)
    assert r3.status_code == 200, f"refresh failed: {r3.status_code} {r3.text[:300]}"
    body = r3.json()
    assert "access_token" in body
    assert "refresh_token" not in body, "refresh_token leaked in JSON"
    new_cookie = r3.cookies.get("nms_rt")
    assert new_cookie, "no new nms_rt cookie on refresh"
    assert new_cookie != old_cookie, "refresh cookie was not rotated"


# ---------- Forgot password (no enumeration) ----------
@pytest.mark.parametrize("email", [ADMIN_EMAIL, "notreal-xyz@example.com"])
def test_forgot_password_200(email):
    r = requests.post(f"{API}/auth/forgot-password", json={"email": email}, timeout=10)
    assert r.status_code == 200, f"forgot-password {email}: {r.status_code} {r.text[:200]}"


# ---------- BAA checklist ----------
def test_baa_checklist_7_rows_no_google_workspace():
    r2 = _login_with_mfa()
    token = r2.json()["access_token"]
    r = requests.get(
        f"{API}/compliance/baa-checklist",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    assert r.status_code == 200, f"baa: {r.status_code} {r.text[:300]}"
    data = r.json()
    rows = data if isinstance(data, list) else data.get("items") or data.get("rows") or data.get("data") or []
    assert len(rows) == 7, f"expected 7 rows, got {len(rows)}: {rows}"
    keys = {row.get("key") or row.get("vendor") or row.get("id") or row.get("name") for row in rows}
    expected = {"mongodb_atlas", "aws", "aws_bedrock", "twilio", "sendgrid", "stripe", "emergent_migration"}
    assert keys == expected, f"key mismatch. got={keys} expected={expected}"
    assert "google_workspace" not in keys
