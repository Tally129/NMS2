#!/usr/bin/env python3
"""
Marketing OS Search Intelligence Phase 1 Backend Test Suite
Tests all 7 scenarios from the review request
"""
import requests
import json
from datetime import datetime

# Load backend URL from frontend/.env
BACKEND_URL = "https://nms-campaign-command.preview.emergentagent.com/api"

# Test credentials from /app/memory/test_credentials.md
ADMIN_EMAIL = "admin@natmedsol.local"
ADMIN_PASSWORD = "Admin!2345"
PRACTITIONER_EMAIL = "ravello@natmedsol.local"
PRACTITIONER_PASSWORD = "Ravello!2345"
AUDITOR_EMAIL = "auditor@natmedsol.local"
AUDITOR_PASSWORD = "Auditor!2345"

# Test state
test_results = []
admin_token = None
practitioner_token = None
auditor_token = None
test_site_id = None


def log_test(scenario, test_name, passed, details=""):
    """Log test result"""
    status = "✅ PASS" if passed else "❌ FAIL"
    result = f"{status} | Scenario {scenario} | {test_name}"
    if details:
        result += f"\n    Details: {details}"
    test_results.append((passed, result))
    print(result)


def login(email, password):
    """Login and return access token"""
    try:
        payload = {"email": email, "password": password}
        resp = requests.post(f"{BACKEND_URL}/auth/login", json=payload, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            # Check if MFA is required
            if data.get("mfa_required"):
                return None, "MFA required but not provided"
            return data.get("access_token"), None
        else:
            return None, f"Login failed: {resp.status_code} - {resp.text}"
    except Exception as e:
        return None, f"Exception: {e}"


def test_scenario_1_authorization():
    """Scenario 1: Authorization (unauthenticated, auditor forbidden, admin allowed)"""
    print("\n=== SCENARIO 1: AUTHORIZATION ===")
    
    global admin_token, practitioner_token, auditor_token
    
    # Test 1: Unauthenticated GET /api/marketing-os/search/overview -> must be rejected (401/403)
    try:
        resp = requests.get(f"{BACKEND_URL}/marketing-os/search/overview", timeout=10)
        if resp.status_code in [401, 403]:
            log_test(1, "Unauthenticated GET /search/overview (401/403)", True, 
                    f"Correctly rejected with {resp.status_code}")
        else:
            log_test(1, "Unauthenticated GET /search/overview (401/403)", False, 
                    f"Expected 401/403, got {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log_test(1, "Unauthenticated GET /search/overview (401/403)", False, f"Exception: {e}")
    
    # Login as auditor
    auditor_token, error = login(AUDITOR_EMAIL, AUDITOR_PASSWORD)
    if error:
        log_test(1, "Auditor login", False, error)
    else:
        log_test(1, "Auditor login", True, "Successfully logged in as auditor")
    
    # Test 2: As auditor (non-marketing role) GET /api/marketing-os/search/overview -> must be forbidden (403)
    if auditor_token:
        try:
            headers = {"Authorization": f"Bearer {auditor_token}"}
            resp = requests.get(f"{BACKEND_URL}/marketing-os/search/overview", 
                              headers=headers, timeout=10)
            if resp.status_code == 403:
                log_test(1, "Auditor GET /search/overview (403)", True, 
                        "Correctly forbidden for non-marketing role")
            else:
                log_test(1, "Auditor GET /search/overview (403)", False, 
                        f"Expected 403, got {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            log_test(1, "Auditor GET /search/overview (403)", False, f"Exception: {e}")
    
    # Login as admin
    admin_token, error = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    if error:
        log_test(1, "Admin login", False, error)
    else:
        log_test(1, "Admin login", True, "Successfully logged in as admin")
    
    # Test 3: As admin GET /api/marketing-os/search/overview -> 200
    if admin_token:
        try:
            headers = {"Authorization": f"Bearer {admin_token}"}
            resp = requests.get(f"{BACKEND_URL}/marketing-os/search/overview", 
                              headers=headers, timeout=10)
            if resp.status_code == 200:
                log_test(1, "Admin GET /search/overview (200)", True, 
                        "Admin successfully accessed marketing endpoint")
            else:
                log_test(1, "Admin GET /search/overview (200)", False, 
                        f"Expected 200, got {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            log_test(1, "Admin GET /search/overview (200)", False, f"Exception: {e}")


def test_scenario_2_empty_not_connected():
    """Scenario 2: Empty/not-connected (before creating any site)"""
    print("\n=== SCENARIO 2: EMPTY / NOT-CONNECTED ===")
    
    if not admin_token:
        log_test(2, "Empty state tests", False, "No admin token available")
        return
    
    headers = {"Authorization": f"Bearer {admin_token}"}
    
    # Test 1: GET /api/marketing-os/search/overview -> 200, connected=false
    try:
        resp = requests.get(f"{BACKEND_URL}/marketing-os/search/overview", 
                          headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if (data.get("connected") == False and 
                data.get("not_connected_reason") == "no_marketing_site_configured"):
                # Check all metrics have value=null and connected=false
                metrics = data.get("metrics", {})
                all_null = all(m.get("value") is None and m.get("connected") == False 
                             for m in metrics.values() if isinstance(m, dict))
                if all_null or not metrics:
                    log_test(2, "GET /search/overview (not connected)", True, 
                            f"Correctly returned connected=false with reason: {data.get('not_connected_reason')}")
                else:
                    log_test(2, "GET /search/overview (not connected)", False, 
                            f"Metrics should have value=null and connected=false: {metrics}")
            else:
                log_test(2, "GET /search/overview (not connected)", False, 
                        f"Expected connected=false with reason, got: {data}")
        else:
            log_test(2, "GET /search/overview (not connected)", False, 
                    f"Expected 200, got {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log_test(2, "GET /search/overview (not connected)", False, f"Exception: {e}")
    
    # Test 2: GET /api/marketing-os/search/keywords/tracked -> 200, connected=false, keywords=[]
    try:
        resp = requests.get(f"{BACKEND_URL}/marketing-os/search/keywords/tracked", 
                          headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if (data.get("connected") == False and 
                data.get("keywords") == []):
                log_test(2, "GET /search/keywords/tracked (not connected)", True, 
                        "Correctly returned connected=false with empty keywords")
            else:
                log_test(2, "GET /search/keywords/tracked (not connected)", False, 
                        f"Expected connected=false with keywords=[], got: {data}")
        else:
            log_test(2, "GET /search/keywords/tracked (not connected)", False, 
                    f"Expected 200, got {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log_test(2, "GET /search/keywords/tracked (not connected)", False, f"Exception: {e}")
    
    # Test 3: GET /api/marketing-os/search/site-audit -> 200, has_run=false
    try:
        resp = requests.get(f"{BACKEND_URL}/marketing-os/search/site-audit", 
                          headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("has_run") == False or data.get("connected") == False:
                log_test(2, "GET /search/site-audit (not connected)", True, 
                        f"Correctly returned has_run=false or connected=false")
            else:
                log_test(2, "GET /search/site-audit (not connected)", False, 
                        f"Expected has_run=false, got: {data}")
        else:
            log_test(2, "GET /search/site-audit (not connected)", False, 
                    f"Expected 200, got {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log_test(2, "GET /search/site-audit (not connected)", False, f"Exception: {e}")


def test_scenario_3_site_registration():
    """Scenario 3: Site registration (create site, list sites, reject private URLs, reject PHI keys)"""
    print("\n=== SCENARIO 3: SITE REGISTRATION ===")
    
    if not admin_token:
        log_test(3, "Site registration tests", False, "No admin token available")
        return
    
    headers = {"Authorization": f"Bearer {admin_token}"}
    global test_site_id
    
    # Test 1: POST /api/marketing-os/search/sites with valid public URL -> 201
    try:
        payload = {"site_url": "https://example.com", "label": "Test Site"}
        resp = requests.post(f"{BACKEND_URL}/marketing-os/search/sites", 
                           json=payload, headers=headers, timeout=10)
        if resp.status_code == 201:
            data = resp.json()
            if data.get("id") and data.get("normalized_url"):
                test_site_id = data["id"]
                log_test(3, "POST /search/sites (valid URL)", True, 
                        f"Created site: {test_site_id}, normalized_url: {data.get('normalized_url')}")
            else:
                log_test(3, "POST /search/sites (valid URL)", False, 
                        f"Missing id or normalized_url: {data}")
        else:
            log_test(3, "POST /search/sites (valid URL)", False, 
                    f"Expected 201, got {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log_test(3, "POST /search/sites (valid URL)", False, f"Exception: {e}")
    
    # Test 2: GET /api/marketing-os/search/sites -> 200, lists the site
    try:
        resp = requests.get(f"{BACKEND_URL}/marketing-os/search/sites", 
                          headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            sites = data.get("sites", [])
            if len(sites) > 0 and any(s.get("id") == test_site_id for s in sites):
                log_test(3, "GET /search/sites (list)", True, 
                        f"Listed {len(sites)} sites, found created site")
            else:
                log_test(3, "GET /search/sites (list)", False, 
                        f"Created site not found in list: {sites}")
        else:
            log_test(3, "GET /search/sites (list)", False, 
                    f"Expected 200, got {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log_test(3, "GET /search/sites (list)", False, f"Exception: {e}")
    
    # Test 3: POST with private/non-public URL -> 400
    try:
        payload = {"site_url": "http://localhost/", "label": "Local Site"}
        resp = requests.post(f"{BACKEND_URL}/marketing-os/search/sites", 
                           json=payload, headers=headers, timeout=10)
        if resp.status_code == 400:
            log_test(3, "POST /search/sites (private URL rejected)", True, 
                    "Correctly rejected private/non-public URL")
        else:
            log_test(3, "POST /search/sites (private URL rejected)", False, 
                    f"Expected 400, got {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log_test(3, "POST /search/sites (private URL rejected)", False, f"Exception: {e}")
    
    # Test 4: POST with PHI key -> 400
    try:
        payload = {"site_url": "https://example.org", "email": "a@b.com"}
        resp = requests.post(f"{BACKEND_URL}/marketing-os/search/sites", 
                           json=payload, headers=headers, timeout=10)
        if resp.status_code == 400:
            log_test(3, "POST /search/sites (PHI key rejected)", True, 
                    "Correctly rejected payload with PHI key")
        else:
            log_test(3, "POST /search/sites (PHI key rejected)", False, 
                    f"Expected 400, got {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log_test(3, "POST /search/sites (PHI key rejected)", False, f"Exception: {e}")


def test_scenario_4_keyword_tracking():
    """Scenario 4: Keyword tracking (add keyword, list keywords, reject PHI keys)"""
    print("\n=== SCENARIO 4: KEYWORD TRACKING ===")
    
    if not admin_token:
        log_test(4, "Keyword tracking tests", False, "No admin token available")
        return
    
    headers = {"Authorization": f"Bearer {admin_token}"}
    
    # Test 1: POST /api/marketing-os/search/keywords with valid keyword -> 201
    try:
        payload = {"keyword": "book appointment online", "current_rank": 3}
        resp = requests.post(f"{BACKEND_URL}/marketing-os/search/keywords", 
                           json=payload, headers=headers, timeout=10)
        if resp.status_code == 201:
            data = resp.json()
            if data.get("id") and data.get("intent") == "transactional":
                log_test(4, "POST /search/keywords (valid keyword)", True, 
                        f"Created keyword with intent=transactional: {data.get('keyword')}")
            else:
                log_test(4, "POST /search/keywords (valid keyword)", False, 
                        f"Expected intent=transactional, got: {data}")
        else:
            log_test(4, "POST /search/keywords (valid keyword)", False, 
                    f"Expected 201, got {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log_test(4, "POST /search/keywords (valid keyword)", False, f"Exception: {e}")
    
    # Test 2: GET /api/marketing-os/search/keywords/tracked -> 200, connected=true, keywords contains the keyword
    try:
        resp = requests.get(f"{BACKEND_URL}/marketing-os/search/keywords/tracked", 
                          headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("connected") == True:
                keywords = data.get("keywords", [])
                found = any(k.get("keyword") == "book appointment online" and 
                          k.get("current_rank") == 3 for k in keywords)
                if found:
                    log_test(4, "GET /search/keywords/tracked (with keyword)", True, 
                            f"Found tracked keyword with current_rank=3")
                else:
                    log_test(4, "GET /search/keywords/tracked (with keyword)", False, 
                            f"Keyword not found or rank mismatch: {keywords}")
            else:
                log_test(4, "GET /search/keywords/tracked (with keyword)", False, 
                        f"Expected connected=true, got: {data}")
        else:
            log_test(4, "GET /search/keywords/tracked (with keyword)", False, 
                    f"Expected 200, got {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log_test(4, "GET /search/keywords/tracked (with keyword)", False, f"Exception: {e}")
    
    # Test 3: POST with PHI key -> 400
    try:
        payload = {"keyword": "detox program", "diagnosis": "x"}
        resp = requests.post(f"{BACKEND_URL}/marketing-os/search/keywords", 
                           json=payload, headers=headers, timeout=10)
        if resp.status_code == 400:
            log_test(4, "POST /search/keywords (PHI key rejected)", True, 
                    "Correctly rejected payload with PHI key")
        else:
            log_test(4, "POST /search/keywords (PHI key rejected)", False, 
                    f"Expected 400, got {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log_test(4, "POST /search/keywords (PHI key rejected)", False, f"Exception: {e}")


def test_scenario_5_technical_site_audit():
    """Scenario 5: Technical site audit (run audit, get audit, get issues)"""
    print("\n=== SCENARIO 5: TECHNICAL SITE AUDIT (READ-ONLY) ===")
    
    if not admin_token:
        log_test(5, "Site audit tests", False, "No admin token available")
        return
    
    headers = {"Authorization": f"Bearer {admin_token}"}
    
    # Test 1: POST /api/marketing-os/search/site-audit/run -> 201
    # IMPORTANT: Outbound internet may be blocked. If unreachable, must still succeed (201)
    # and record a completed run with a "page_unreachable" critical issue.
    try:
        payload = {"site_url": "https://example.com", "max_pages": 3}
        resp = requests.post(f"{BACKEND_URL}/marketing-os/search/site-audit/run", 
                           json=payload, headers=headers, timeout=30)
        if resp.status_code == 201:
            data = resp.json()
            required_fields = ["pages_scanned", "critical_count", "warning_count", 
                             "opportunity_count", "informational_count"]
            if all(field in data for field in required_fields):
                log_test(5, "POST /search/site-audit/run (201)", True, 
                        f"Audit run completed: pages_scanned={data.get('pages_scanned')}, "
                        f"critical={data.get('critical_count')}, warning={data.get('warning_count')}, "
                        f"opportunity={data.get('opportunity_count')}, info={data.get('informational_count')}")
            else:
                log_test(5, "POST /search/site-audit/run (201)", False, 
                        f"Missing required fields: {data}")
        else:
            log_test(5, "POST /search/site-audit/run (201)", False, 
                    f"Expected 201, got {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log_test(5, "POST /search/site-audit/run (201)", False, f"Exception: {e}")
    
    # Test 2: GET /api/marketing-os/search/site-audit -> 200, has_run=true
    try:
        resp = requests.get(f"{BACKEND_URL}/marketing-os/search/site-audit", 
                          headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("has_run") == True:
                log_test(5, "GET /search/site-audit (has_run=true)", True, 
                        f"Latest audit run found with counts")
            else:
                log_test(5, "GET /search/site-audit (has_run=true)", False, 
                        f"Expected has_run=true, got: {data}")
        else:
            log_test(5, "GET /search/site-audit (has_run=true)", False, 
                    f"Expected 200, got {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log_test(5, "GET /search/site-audit (has_run=true)", False, f"Exception: {e}")
    
    # Test 3: GET /api/marketing-os/search/site-audit/issues -> 200, returns issues array
    try:
        resp = requests.get(f"{BACKEND_URL}/marketing-os/search/site-audit/issues", 
                          headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if "issues" in data and isinstance(data["issues"], list):
                log_test(5, "GET /search/site-audit/issues (200)", True, 
                        f"Retrieved {len(data['issues'])} audit issues")
            else:
                log_test(5, "GET /search/site-audit/issues (200)", False, 
                        f"Expected issues array, got: {data}")
        else:
            log_test(5, "GET /search/site-audit/issues (200)", False, 
                    f"Expected 200, got {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log_test(5, "GET /search/site-audit/issues (200)", False, f"Exception: {e}")


def test_scenario_6_advisory_recommendations():
    """Scenario 6: Advisory recommendations (all must have advisory_only=true, requires_human_approval=true, external_write=false)"""
    print("\n=== SCENARIO 6: ADVISORY RECOMMENDATIONS ===")
    
    if not admin_token:
        log_test(6, "Advisory recommendations tests", False, "No admin token available")
        return
    
    headers = {"Authorization": f"Bearer {admin_token}"}
    
    # Test: GET /api/marketing-os/search/recommendations -> 200
    # EVERY recommendation object MUST have advisory_only=true, requires_human_approval=true, external_write=false
    try:
        resp = requests.get(f"{BACKEND_URL}/marketing-os/search/recommendations", 
                          headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            recommendations = data.get("recommendations", [])
            
            # Check top-level flags
            if (data.get("advisory_only") == True and 
                data.get("requires_human_approval") == True):
                log_test(6, "GET /search/recommendations (top-level flags)", True, 
                        f"advisory_only=true, requires_human_approval=true")
            else:
                log_test(6, "GET /search/recommendations (top-level flags)", False, 
                        f"Expected advisory_only=true and requires_human_approval=true, got: {data}")
            
            # Check each recommendation
            if recommendations:
                all_valid = all(
                    rec.get("advisory_only") == True and 
                    rec.get("requires_human_approval") == True and 
                    rec.get("external_write") == False 
                    for rec in recommendations
                )
                if all_valid:
                    log_test(6, "GET /search/recommendations (all recs valid)", True, 
                            f"All {len(recommendations)} recommendations have correct flags")
                else:
                    invalid = [rec for rec in recommendations if not (
                        rec.get("advisory_only") == True and 
                        rec.get("requires_human_approval") == True and 
                        rec.get("external_write") == False
                    )]
                    log_test(6, "GET /search/recommendations (all recs valid)", False, 
                            f"Invalid recommendations: {invalid}")
            else:
                log_test(6, "GET /search/recommendations (all recs valid)", True, 
                        "No recommendations returned (empty is valid)")
        else:
            log_test(6, "GET /search/recommendations (200)", False, 
                    f"Expected 200, got {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log_test(6, "GET /search/recommendations (200)", False, f"Exception: {e}")


def test_scenario_7_safety_policy():
    """Scenario 7: Safety policy unchanged (capabilities and health endpoints)"""
    print("\n=== SCENARIO 7: SAFETY POLICY UNCHANGED ===")
    
    if not admin_token:
        log_test(7, "Safety policy tests", False, "No admin token available")
        return
    
    headers = {"Authorization": f"Bearer {admin_token}"}
    
    # Test 1: GET /api/marketing-os/capabilities -> 200
    try:
        resp = requests.get(f"{BACKEND_URL}/marketing-os/capabilities", 
                          headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            policy = data.get("policy", {})
            capabilities = data.get("capabilities", {})
            search_intel = capabilities.get("search_intelligence", {})
            
            # Check policy flags
            policy_valid = (
                policy.get("external_writes_enabled") == False and
                policy.get("automatic_budget_changes_enabled") == False and
                policy.get("automatic_campaign_creation_enabled") == False and
                policy.get("automatic_publishing_enabled") == False and
                policy.get("human_approval_required") == True
            )
            
            if policy_valid:
                log_test(7, "GET /capabilities (policy flags)", True, 
                        "All policy flags correct: external_writes=false, human_approval=true")
            else:
                log_test(7, "GET /capabilities (policy flags)", False, 
                        f"Policy flags incorrect: {policy}")
            
            # Check search_intelligence capability flags
            search_valid = (
                search_intel.get("write_enabled") == False and
                search_intel.get("phi_stored") == False
            )
            
            if search_valid:
                log_test(7, "GET /capabilities (search_intelligence flags)", True, 
                        "search_intelligence.write_enabled=false, phi_stored=false")
            else:
                log_test(7, "GET /capabilities (search_intelligence flags)", False, 
                        f"search_intelligence flags incorrect: {search_intel}")
        else:
            log_test(7, "GET /capabilities (200)", False, 
                    f"Expected 200, got {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log_test(7, "GET /capabilities (200)", False, f"Exception: {e}")
    
    # Test 2: GET /api/marketing-os/health -> 200
    try:
        resp = requests.get(f"{BACKEND_URL}/marketing-os/health", 
                          headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            health_valid = (
                data.get("external_writes_enabled") == False and
                data.get("human_approval_required") == True
            )
            
            if health_valid:
                log_test(7, "GET /health (flags)", True, 
                        "external_writes_enabled=false, human_approval_required=true")
            else:
                log_test(7, "GET /health (flags)", False, 
                        f"Health flags incorrect: {data}")
        else:
            log_test(7, "GET /health (200)", False, 
                    f"Expected 200, got {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log_test(7, "GET /health (200)", False, f"Exception: {e}")


def main():
    """Run all test scenarios"""
    print("=" * 80)
    print("Marketing OS Search Intelligence Phase 1 Backend Test Suite")
    print(f"Backend URL: {BACKEND_URL}")
    print("=" * 80)
    
    # Run all scenarios in order
    test_scenario_1_authorization()
    test_scenario_2_empty_not_connected()
    test_scenario_3_site_registration()
    test_scenario_4_keyword_tracking()
    test_scenario_5_technical_site_audit()
    test_scenario_6_advisory_recommendations()
    test_scenario_7_safety_policy()
    
    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    
    passed = sum(1 for p, _ in test_results if p)
    failed = sum(1 for p, _ in test_results if not p)
    total = len(test_results)
    
    print(f"\nTotal Tests: {total}")
    print(f"Passed: {passed} ✅")
    print(f"Failed: {failed} ❌")
    print(f"Success Rate: {(passed/total*100):.1f}%\n")
    
    if failed > 0:
        print("FAILED TESTS:")
        for passed, result in test_results:
            if not passed:
                print(result)
    
    print("\n" + "=" * 80)
    return failed == 0


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
