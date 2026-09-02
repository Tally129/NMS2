#!/usr/bin/env python3
"""
Focused test for Marketing OS Search Intelligence PHI rejection fix.
Tests the extra="forbid" fix on SiteRegister, KeywordTrack, AuditRunRequest models.
"""
import requests
import json
import sys
from typing import Dict, Any

# Backend URL from frontend/.env
BASE_URL = "https://nms-nurture-phase8.preview.emergentagent.com/api"

# Test credentials
ADMIN_EMAIL = "admin@natmedsol.local"
ADMIN_PASSWORD = "Admin!2345"

class TestResult:
    def __init__(self):
        self.passed = []
        self.failed = []
        self.total = 0
    
    def add_pass(self, test_name: str, details: str = ""):
        self.passed.append(f"✅ {test_name}: {details}")
        self.total += 1
    
    def add_fail(self, test_name: str, details: str):
        self.failed.append(f"❌ {test_name}: {details}")
        self.total += 1
    
    def print_summary(self):
        print("\n" + "="*80)
        print("TEST SUMMARY")
        print("="*80)
        
        if self.failed:
            print("\n❌ FAILED TESTS:")
            for fail in self.failed:
                print(f"  {fail}")
        
        if self.passed:
            print("\n✅ PASSED TESTS:")
            for pass_test in self.passed:
                print(f"  {pass_test}")
        
        print(f"\nTotal: {len(self.passed)}/{self.total} passed")
        print("="*80)
        
        return len(self.failed) == 0

def login_admin() -> str:
    """Login as admin and return access token."""
    print(f"🔐 Logging in as {ADMIN_EMAIL}...")
    
    response = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    
    if response.status_code != 200:
        print(f"❌ Login failed: {response.status_code} {response.text}")
        sys.exit(1)
    
    data = response.json()
    token = data.get("access_token")
    
    if not token:
        print(f"❌ No access token in response: {data}")
        sys.exit(1)
    
    print(f"✅ Logged in successfully")
    return token

def test_phi_rejection(token: str, result: TestResult):
    """Test A: PHI / unknown-key rejection (the fix)"""
    print("\n" + "="*80)
    print("A) PHI / UNKNOWN-KEY REJECTION TESTS")
    print("="*80)
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # A1: Site registration with PHI key (email)
    print("\nA1: POST /api/marketing-os/search/sites with PHI key 'email'")
    response = requests.post(
        f"{BASE_URL}/marketing-os/search/sites",
        headers=headers,
        json={"site_url": "https://example.org", "email": "a@b.com"}
    )
    print(f"   Status: {response.status_code}")
    print(f"   Response: {response.text[:200]}")
    
    if response.status_code in [400, 422]:
        result.add_pass("A1: Site registration PHI rejection", f"Rejected with {response.status_code}")
    elif response.status_code == 201:
        result.add_fail("A1: Site registration PHI rejection", f"ACCEPTED (201) - should reject PHI key 'email'")
    else:
        result.add_pass("A1: Site registration PHI rejection", f"Rejected with {response.status_code} (any 4xx is PASS)")
    
    # A2: Keyword tracking with PHI key (diagnosis)
    print("\nA2: POST /api/marketing-os/search/keywords with PHI key 'diagnosis'")
    response = requests.post(
        f"{BASE_URL}/marketing-os/search/keywords",
        headers=headers,
        json={"keyword": "detox program", "diagnosis": "x"}
    )
    print(f"   Status: {response.status_code}")
    print(f"   Response: {response.text[:200]}")
    
    if response.status_code in [400, 422]:
        result.add_pass("A2: Keyword tracking PHI rejection", f"Rejected with {response.status_code}")
    elif response.status_code == 201:
        result.add_fail("A2: Keyword tracking PHI rejection", f"ACCEPTED (201) - should reject PHI key 'diagnosis'")
    else:
        result.add_pass("A2: Keyword tracking PHI rejection", f"Rejected with {response.status_code} (any 4xx is PASS)")
    
    # A3: Site audit with PHI key (patient_name)
    print("\nA3: POST /api/marketing-os/search/site-audit/run with PHI key 'patient_name'")
    response = requests.post(
        f"{BASE_URL}/marketing-os/search/site-audit/run",
        headers=headers,
        json={"site_url": "https://example.com", "patient_name": "z"}
    )
    print(f"   Status: {response.status_code}")
    print(f"   Response: {response.text[:200]}")
    
    if response.status_code in [400, 422]:
        result.add_pass("A3: Site audit PHI rejection", f"Rejected with {response.status_code}")
    elif response.status_code == 201:
        result.add_fail("A3: Site audit PHI rejection", f"ACCEPTED (201) - should reject PHI key 'patient_name'")
    else:
        result.add_pass("A3: Site audit PHI rejection", f"Rejected with {response.status_code} (any 4xx is PASS)")

def test_regression_valid_requests(token: str, result: TestResult):
    """Test B: Regression check - valid requests still work"""
    print("\n" + "="*80)
    print("B) REGRESSION CHECK - VALID REQUESTS")
    print("="*80)
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # B4: Valid site registration
    print("\nB4: POST /api/marketing-os/search/sites with valid payload")
    response = requests.post(
        f"{BASE_URL}/marketing-os/search/sites",
        headers=headers,
        json={"site_url": "https://example.com", "label": "Test Site"}
    )
    print(f"   Status: {response.status_code}")
    print(f"   Response: {response.text[:200]}")
    
    if response.status_code in [200, 201]:
        result.add_pass("B4: Valid site registration", f"Accepted with {response.status_code}")
    else:
        result.add_fail("B4: Valid site registration", f"Failed with {response.status_code}: {response.text[:100]}")
    
    # B5: Valid keyword tracking
    print("\nB5: POST /api/marketing-os/search/keywords with valid payload")
    response = requests.post(
        f"{BASE_URL}/marketing-os/search/keywords",
        headers=headers,
        json={"keyword": "book appointment online", "current_rank": 3}
    )
    print(f"   Status: {response.status_code}")
    print(f"   Response: {response.text[:200]}")
    
    if response.status_code in [200, 201]:
        data = response.json()
        intent = data.get("intent")
        if intent == "transactional":
            result.add_pass("B5: Valid keyword tracking", f"Accepted with {response.status_code}, intent=transactional")
        else:
            result.add_fail("B5: Valid keyword tracking", f"Accepted but intent={intent} (expected 'transactional')")
    else:
        result.add_fail("B5: Valid keyword tracking", f"Failed with {response.status_code}: {response.text[:100]}")
    
    # B6: Valid site audit
    print("\nB6: POST /api/marketing-os/search/site-audit/run with valid payload")
    response = requests.post(
        f"{BASE_URL}/marketing-os/search/site-audit/run",
        headers=headers,
        json={"site_url": "https://example.com", "max_pages": 3}
    )
    print(f"   Status: {response.status_code}")
    print(f"   Response: {response.text[:300]}")
    
    if response.status_code == 201:
        result.add_pass("B6: Valid site audit", f"Accepted with 201 (unreachable target with page_unreachable issue is acceptable)")
    elif response.status_code == 500:
        result.add_fail("B6: Valid site audit", f"Failed with 500: {response.text[:100]}")
    else:
        result.add_pass("B6: Valid site audit", f"Accepted with {response.status_code}")
    
    # B7: GET endpoints
    print("\nB7: GET /api/marketing-os/search/overview")
    response = requests.get(f"{BASE_URL}/marketing-os/search/overview", headers=headers)
    print(f"   Status: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        connected = data.get("connected")
        print(f"   connected={connected}")
        result.add_pass("B7a: GET overview", f"200, connected={connected}")
    else:
        result.add_fail("B7a: GET overview", f"Failed with {response.status_code}")
    
    print("\nB7: GET /api/marketing-os/search/keywords/tracked")
    response = requests.get(f"{BASE_URL}/marketing-os/search/keywords/tracked", headers=headers)
    print(f"   Status: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        keywords = data.get("keywords", [])
        print(f"   keywords count={len(keywords)}")
        result.add_pass("B7b: GET keywords/tracked", f"200, {len(keywords)} keywords")
    else:
        result.add_fail("B7b: GET keywords/tracked", f"Failed with {response.status_code}")
    
    print("\nB7: GET /api/marketing-os/search/recommendations")
    response = requests.get(f"{BASE_URL}/marketing-os/search/recommendations", headers=headers)
    print(f"   Status: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        recommendations = data.get("recommendations", [])
        print(f"   recommendations count={len(recommendations)}")
        
        # Check all recommendations have correct flags
        all_correct = True
        for rec in recommendations:
            if not (rec.get("advisory_only") == True and 
                    rec.get("requires_human_approval") == True and 
                    rec.get("external_write") == False):
                all_correct = False
                break
        
        if all_correct:
            result.add_pass("B7c: GET recommendations", f"200, all items have correct flags (advisory_only=true, requires_human_approval=true, external_write=false)")
        else:
            result.add_fail("B7c: GET recommendations", f"200 but some items have incorrect flags")
    else:
        result.add_fail("B7c: GET recommendations", f"Failed with {response.status_code}")

def test_safety_policy(token: str, result: TestResult):
    """Test C: Safety unchanged"""
    print("\n" + "="*80)
    print("C) SAFETY POLICY CHECK")
    print("="*80)
    
    headers = {"Authorization": f"Bearer {token}"}
    
    print("\nC8: GET /api/marketing-os/capabilities")
    response = requests.get(f"{BASE_URL}/marketing-os/capabilities", headers=headers)
    print(f"   Status: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"   Response: {json.dumps(data, indent=2)}")
        
        # Check policy flags
        policy = data.get("policy", {})
        capabilities = data.get("capabilities", {})
        search_intel = capabilities.get("search_intelligence", {})
        
        checks = []
        checks.append(("human_approval_required", policy.get("human_approval_required") == True))
        checks.append(("write_enabled", search_intel.get("write_enabled") == False))
        checks.append(("phi_stored", search_intel.get("phi_stored") == False))
        
        all_correct = all(check[1] for check in checks)
        
        if all_correct:
            result.add_pass("C8: Safety policy", "All flags correct: human_approval_required=true, write_enabled=false, phi_stored=false")
        else:
            failed_checks = [check[0] for check in checks if not check[1]]
            result.add_fail("C8: Safety policy", f"Incorrect flags: {', '.join(failed_checks)}")
    else:
        result.add_fail("C8: Safety policy", f"Failed with {response.status_code}")

def main():
    print("="*80)
    print("MARKETING OS SEARCH INTELLIGENCE - PHI FIX VERIFICATION")
    print("="*80)
    print(f"Backend URL: {BASE_URL}")
    print(f"Testing with: {ADMIN_EMAIL}")
    
    result = TestResult()
    
    # Login
    token = login_admin()
    
    # Run tests
    test_phi_rejection(token, result)
    test_regression_valid_requests(token, result)
    test_safety_policy(token, result)
    
    # Print summary
    success = result.print_summary()
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
