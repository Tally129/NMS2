"""
Phase 2: Google Search Console (read-only) + Rank Tracking Backend Tests

Tests all 8 scenarios for GSC integration:
1. Auth gate (unauthenticated + admin access)
2. Readiness endpoint (not_connected state, no credential leaks)
3. Sync safe no-op when disconnected
4. Honest empty reads (performance, queries, pages)
5. Rank tracking (distinct gsc_average_position vs serp_rank)
6. Overview honesty (connected=false for GSC metrics)
7. Advisory recommendations (all flags correct)
8. Safety policy (all flags correct)
"""

import requests
import json
from typing import Optional

# Base URL from frontend/.env
BASE_URL = "https://nms-campaign-command.preview.emergentagent.com"
API_BASE = f"{BASE_URL}/api"

# Test credentials from /app/memory/test_credentials.md
ADMIN_EMAIL = "admin@natmedsol.local"
ADMIN_PASSWORD = "Admin!2345"
PRACTITIONER_EMAIL = "ravello@natmedsol.local"
PRACTITIONER_PASSWORD = "Ravello!2345"


class TestResult:
    def __init__(self):
        self.passed = []
        self.failed = []
        self.warnings = []
    
    def add_pass(self, test_name: str, details: str = ""):
        self.passed.append(f"✅ {test_name}: {details}")
    
    def add_fail(self, test_name: str, details: str):
        self.failed.append(f"❌ {test_name}: {details}")
    
    def add_warning(self, test_name: str, details: str):
        self.warnings.append(f"⚠️  {test_name}: {details}")
    
    def print_summary(self):
        print("\n" + "="*80)
        print("PHASE 2 GSC BACKEND TEST RESULTS")
        print("="*80)
        
        if self.failed:
            print("\n❌ FAILED TESTS:")
            for fail in self.failed:
                print(f"  {fail}")
        
        if self.warnings:
            print("\n⚠️  WARNINGS:")
            for warn in self.warnings:
                print(f"  {warn}")
        
        if self.passed:
            print("\n✅ PASSED TESTS:")
            for p in self.passed:
                print(f"  {p}")
        
        total = len(self.passed) + len(self.failed)
        success_rate = (len(self.passed) / total * 100) if total > 0 else 0
        print(f"\n{'='*80}")
        print(f"SUMMARY: {len(self.passed)}/{total} tests passed ({success_rate:.0f}%)")
        print(f"{'='*80}\n")


def login(email: str, password: str) -> Optional[str]:
    """Login and return access token. Handle MFA if required."""
    try:
        response = requests.post(
            f"{API_BASE}/auth/login",
            json={"email": email, "password": password},
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get("mfa_required"):
                print(f"⚠️  MFA required for {email}. Cannot proceed with automated testing.")
                return None
            return data.get("access_token")
        else:
            print(f"❌ Login failed for {email}: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"❌ Login error for {email}: {str(e)}")
        return None


def test_scenario_1_auth(result: TestResult):
    """Scenario 1: Auth gate - unauthenticated rejected, admin allowed"""
    print("\n[Scenario 1] Testing Auth Gate...")
    
    # Test 1.1: Unauthenticated request should be rejected
    try:
        response = requests.get(
            f"{API_BASE}/marketing-os/search/search-console/readiness",
            timeout=10
        )
        if response.status_code in [401, 403]:
            result.add_pass(
                "1.1 Unauthenticated rejected",
                f"GET /readiness returned {response.status_code}"
            )
        else:
            result.add_fail(
                "1.1 Unauthenticated rejected",
                f"Expected 401/403, got {response.status_code}"
            )
    except Exception as e:
        result.add_fail("1.1 Unauthenticated rejected", f"Error: {str(e)}")
    
    # Test 1.2: Admin should be allowed
    admin_token = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    if not admin_token:
        result.add_fail("1.2 Admin access", "Failed to login as admin")
        return None
    
    try:
        response = requests.get(
            f"{API_BASE}/marketing-os/search/search-console/readiness",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=10
        )
        if response.status_code == 200:
            result.add_pass(
                "1.2 Admin access",
                "GET /readiness returned 200"
            )
        else:
            result.add_fail(
                "1.2 Admin access",
                f"Expected 200, got {response.status_code}: {response.text}"
            )
    except Exception as e:
        result.add_fail("1.2 Admin access", f"Error: {str(e)}")
    
    return admin_token


def test_scenario_2_readiness(result: TestResult, token: str):
    """Scenario 2: Readiness endpoint - not_connected state, no credential leaks"""
    print("\n[Scenario 2] Testing Readiness Endpoint...")
    
    try:
        response = requests.get(
            f"{API_BASE}/marketing-os/search/search-console/readiness",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        
        if response.status_code != 200:
            result.add_fail(
                "2.1 Readiness status",
                f"Expected 200, got {response.status_code}: {response.text}"
            )
            return
        
        data = response.json()
        
        # Check status is not_connected or configuration_incomplete
        status = data.get("status")
        if status in ["not_connected", "configuration_incomplete"]:
            result.add_pass(
                "2.1 Readiness status",
                f"status={status}"
            )
        else:
            result.add_fail(
                "2.1 Readiness status",
                f"Expected 'not_connected' or 'configuration_incomplete', got '{status}'"
            )
        
        # Check connected=false
        if data.get("connected") is False:
            result.add_pass("2.2 Connected flag", "connected=false")
        else:
            result.add_fail(
                "2.2 Connected flag",
                f"Expected connected=false, got {data.get('connected')}"
            )
        
        # Check read_only=true
        if data.get("read_only") is True:
            result.add_pass("2.3 Read-only flag", "read_only=true")
        else:
            result.add_fail(
                "2.3 Read-only flag",
                f"Expected read_only=true, got {data.get('read_only')}"
            )
        
        # Check external_write=false
        if data.get("external_write") is False:
            result.add_pass("2.4 External write flag", "external_write=false")
        else:
            result.add_fail(
                "2.4 External write flag",
                f"Expected external_write=false, got {data.get('external_write')}"
            )
        
        # Check NO credential values leaked
        json_str = json.dumps(data).lower()
        leaked_keys = []
        if "private_key" in json_str:
            leaked_keys.append("private_key")
        if "client_email" in json_str and "@" in json_str:
            # Check if actual email value is present (not just the key name)
            if any(domain in json_str for domain in [".iam.gserviceaccount.com", "@developer.gserviceaccount.com"]):
                leaked_keys.append("service_account_email")
        
        if not leaked_keys:
            result.add_pass("2.5 No credential leaks", "No private_key or service account email in response")
        else:
            result.add_fail(
                "2.5 No credential leaks",
                f"Credential values leaked: {', '.join(leaked_keys)}"
            )
        
    except Exception as e:
        result.add_fail("2.x Readiness endpoint", f"Error: {str(e)}")


def test_scenario_3_sync_safe_noop(result: TestResult, token: str):
    """Scenario 3: Sync is safe no-op when disconnected"""
    print("\n[Scenario 3] Testing Sync Safe No-Op...")
    
    try:
        response = requests.post(
            f"{API_BASE}/marketing-os/search/search-console/sync",
            headers={"Authorization": f"Bearer {token}"},
            json={},
            timeout=10
        )
        
        # Accept 200 or 201 (endpoint is decorated with status_code=201)
        if response.status_code not in [200, 201]:
            result.add_fail(
                "3.1 Sync no-op status",
                f"Expected 200/201, got {response.status_code}: {response.text}"
            )
            return
        
        result.add_pass(
            "3.1 Sync no-op status",
            f"POST /sync returned {response.status_code} (no 500 error)"
        )
        
        data = response.json()
        
        # Check started=false
        if data.get("started") is False:
            result.add_pass("3.2 Sync not started", "started=false")
        else:
            result.add_fail(
                "3.2 Sync not started",
                f"Expected started=false, got {data.get('started')}"
            )
        
        # Check reason matches readiness status
        reason = data.get("reason")
        if reason in ["not_connected", "configuration_incomplete"]:
            result.add_pass(
                "3.3 Sync reason",
                f"reason={reason}"
            )
        else:
            result.add_fail(
                "3.3 Sync reason",
                f"Expected 'not_connected' or 'configuration_incomplete', got '{reason}'"
            )
        
    except Exception as e:
        result.add_fail("3.x Sync safe no-op", f"Error: {str(e)}")


def ensure_site_exists(token: str) -> Optional[str]:
    """Ensure a marketing site exists, create if needed. Return site_id."""
    try:
        # Check if sites exist
        response = requests.get(
            f"{API_BASE}/marketing-os/search/sites",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        
        if response.status_code == 200:
            sites = response.json().get("sites", [])
            if sites:
                return sites[0]["id"]
        
        # Create a site
        response = requests.post(
            f"{API_BASE}/marketing-os/search/sites",
            headers={"Authorization": f"Bearer {token}"},
            json={"site_url": "https://natmedsol.com", "label": "NMS"},
            timeout=10
        )
        
        if response.status_code == 201:
            return response.json().get("id")
        
        return None
    except Exception as e:
        print(f"⚠️  Error ensuring site exists: {str(e)}")
        return None


def test_scenario_4_honest_empty_reads(result: TestResult, token: str):
    """Scenario 4: Honest empty reads (performance, queries, pages)"""
    print("\n[Scenario 4] Testing Honest Empty Reads...")
    
    # Ensure site exists
    site_id = ensure_site_exists(token)
    if not site_id:
        result.add_warning("4.x Honest empty reads", "Could not ensure site exists")
        return
    
    # Test 4.1: Performance endpoint
    try:
        response = requests.get(
            f"{API_BASE}/marketing-os/search/search-console/performance",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        
        if response.status_code != 200:
            result.add_fail(
                "4.1 Performance endpoint",
                f"Expected 200, got {response.status_code}: {response.text}"
            )
        else:
            data = response.json()
            
            # Check has_data=false
            if data.get("has_data") is False:
                result.add_pass("4.1a Performance has_data", "has_data=false")
            else:
                result.add_fail(
                    "4.1a Performance has_data",
                    f"Expected has_data=false, got {data.get('has_data')}"
                )
            
            # Check totals present with 0/null values
            totals = data.get("totals", {})
            if totals:
                clicks = totals.get("clicks")
                impressions = totals.get("impressions")
                if clicks == 0 and impressions == 0:
                    result.add_pass(
                        "4.1b Performance totals",
                        "totals present with clicks=0, impressions=0 (honest empty)"
                    )
                else:
                    result.add_fail(
                        "4.1b Performance totals",
                        f"Expected 0 values, got clicks={clicks}, impressions={impressions}"
                    )
            else:
                result.add_fail("4.1b Performance totals", "totals not present")
    
    except Exception as e:
        result.add_fail("4.1 Performance endpoint", f"Error: {str(e)}")
    
    # Test 4.2: Queries endpoint
    try:
        response = requests.get(
            f"{API_BASE}/marketing-os/search/search-console/queries",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        
        if response.status_code != 200:
            result.add_fail(
                "4.2 Queries endpoint",
                f"Expected 200, got {response.status_code}: {response.text}"
            )
        else:
            data = response.json()
            
            if data.get("has_data") is False and data.get("queries") == []:
                result.add_pass(
                    "4.2 Queries endpoint",
                    "has_data=false, queries=[] (honest empty)"
                )
            else:
                result.add_fail(
                    "4.2 Queries endpoint",
                    f"Expected has_data=false and queries=[], got has_data={data.get('has_data')}, queries={len(data.get('queries', []))} items"
                )
    
    except Exception as e:
        result.add_fail("4.2 Queries endpoint", f"Error: {str(e)}")
    
    # Test 4.3: Pages endpoint
    try:
        response = requests.get(
            f"{API_BASE}/marketing-os/search/search-console/pages",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        
        if response.status_code != 200:
            result.add_fail(
                "4.3 Pages endpoint",
                f"Expected 200, got {response.status_code}: {response.text}"
            )
        else:
            data = response.json()
            
            if data.get("has_data") is False and data.get("pages") == []:
                result.add_pass(
                    "4.3 Pages endpoint",
                    "has_data=false, pages=[] (honest empty)"
                )
            else:
                result.add_fail(
                    "4.3 Pages endpoint",
                    f"Expected has_data=false and pages=[], got has_data={data.get('has_data')}, pages={len(data.get('pages', []))} items"
                )
    
    except Exception as e:
        result.add_fail("4.3 Pages endpoint", f"Error: {str(e)}")


def ensure_tracked_keyword(token: str) -> bool:
    """Ensure at least one tracked keyword exists."""
    try:
        # Check if tracked keywords exist
        response = requests.get(
            f"{API_BASE}/marketing-os/search/keywords/tracked",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        
        if response.status_code == 200:
            keywords = response.json().get("keywords", [])
            if keywords:
                return True
        
        # Create a tracked keyword
        response = requests.post(
            f"{API_BASE}/marketing-os/search/keywords",
            headers={"Authorization": f"Bearer {token}"},
            json={"keyword": "book appointment online", "current_rank": 3},
            timeout=10
        )
        
        return response.status_code == 201
    except Exception as e:
        print(f"⚠️  Error ensuring tracked keyword: {str(e)}")
        return False


def test_scenario_5_rank_tracking(result: TestResult, token: str):
    """Scenario 5: Rank tracking - distinct gsc_average_position vs serp_rank"""
    print("\n[Scenario 5] Testing Rank Tracking...")
    
    # Ensure tracked keyword exists
    if not ensure_tracked_keyword(token):
        result.add_warning("5.x Rank tracking", "Could not ensure tracked keyword exists")
        return
    
    try:
        response = requests.get(
            f"{API_BASE}/marketing-os/search/rank-tracking",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        
        if response.status_code != 200:
            result.add_fail(
                "5.1 Rank tracking status",
                f"Expected 200, got {response.status_code}: {response.text}"
            )
            return
        
        data = response.json()
        keywords = data.get("keywords", [])
        
        if not keywords:
            result.add_warning(
                "5.1 Rank tracking keywords",
                "No tracked keywords returned (may be expected if none exist)"
            )
            return
        
        # Check first keyword has both gsc_average_position and serp_rank
        kw = keywords[0]
        
        if "gsc_average_position" not in kw:
            result.add_fail(
                "5.1 GSC average position",
                "gsc_average_position not present in keyword object"
            )
        else:
            gsc = kw["gsc_average_position"]
            if gsc.get("metric_type") == "gsc_average_position":
                result.add_pass(
                    "5.1 GSC average position",
                    f"metric_type='gsc_average_position', source='{gsc.get('source')}'"
                )
            else:
                result.add_fail(
                    "5.1 GSC average position",
                    f"Expected metric_type='gsc_average_position', got '{gsc.get('metric_type')}'"
                )
        
        if "serp_rank" not in kw:
            result.add_fail(
                "5.2 SERP rank",
                "serp_rank not present in keyword object"
            )
        else:
            serp = kw["serp_rank"]
            if serp.get("metric_type") == "serp_rank":
                result.add_pass(
                    "5.2 SERP rank",
                    f"metric_type='serp_rank', source='{serp.get('source')}'"
                )
            else:
                result.add_fail(
                    "5.2 SERP rank",
                    f"Expected metric_type='serp_rank', got '{serp.get('metric_type')}'"
                )
        
        # Check they are explicitly distinct
        if "gsc_average_position" in kw and "serp_rank" in kw:
            gsc_type = kw["gsc_average_position"].get("metric_type")
            serp_type = kw["serp_rank"].get("metric_type")
            if gsc_type != serp_type:
                result.add_pass(
                    "5.3 Distinct metrics",
                    f"gsc_average_position and serp_rank have different metric_type"
                )
            else:
                result.add_fail(
                    "5.3 Distinct metrics",
                    "gsc_average_position and serp_rank have same metric_type"
                )
        
        # Check summary has gains/losses/unchanged
        summary = data.get("summary", {})
        required_keys = ["gains", "losses", "unchanged"]
        missing = [k for k in required_keys if k not in summary]
        if not missing:
            result.add_pass(
                "5.4 Summary keys",
                f"gains={summary.get('gains')}, losses={summary.get('losses')}, unchanged={summary.get('unchanged')}"
            )
        else:
            result.add_fail(
                "5.4 Summary keys",
                f"Missing keys in summary: {', '.join(missing)}"
            )
    
    except Exception as e:
        result.add_fail("5.x Rank tracking", f"Error: {str(e)}")


def test_scenario_6_overview_honesty(result: TestResult, token: str):
    """Scenario 6: Overview honesty - connected=false for GSC metrics"""
    print("\n[Scenario 6] Testing Overview Honesty...")
    
    try:
        response = requests.get(
            f"{API_BASE}/marketing-os/search/overview",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        
        if response.status_code != 200:
            result.add_fail(
                "6.1 Overview status",
                f"Expected 200, got {response.status_code}: {response.text}"
            )
            return
        
        data = response.json()
        metrics = data.get("metrics", {})
        
        # Check GSC metrics have connected=false and value=null
        gsc_metrics = [
            "organic_keywords",
            "estimated_organic_traffic",
            "organic_clicks"
        ]
        
        all_honest = True
        for metric_name in gsc_metrics:
            metric = metrics.get(metric_name, {})
            connected = metric.get("connected")
            value = metric.get("value")
            
            if connected is False and value is None:
                result.add_pass(
                    f"6.{gsc_metrics.index(metric_name) + 1} {metric_name}",
                    f"connected=false, value=null (honest)"
                )
            else:
                result.add_fail(
                    f"6.{gsc_metrics.index(metric_name) + 1} {metric_name}",
                    f"Expected connected=false and value=null, got connected={connected}, value={value}"
                )
                all_honest = False
        
        # Check first-party metrics (tracked_keywords) may be populated
        tracked = metrics.get("tracked_keywords", {})
        if tracked.get("connected") is True:
            result.add_pass(
                "6.4 First-party metrics",
                f"tracked_keywords connected=true (first-party data)"
            )
        else:
            result.add_warning(
                "6.4 First-party metrics",
                "tracked_keywords not connected (may be expected if no keywords tracked)"
            )
    
    except Exception as e:
        result.add_fail("6.x Overview honesty", f"Error: {str(e)}")


def test_scenario_7_advisory_recommendations(result: TestResult, token: str):
    """Scenario 7: Advisory recommendations - all flags correct"""
    print("\n[Scenario 7] Testing Advisory Recommendations...")
    
    try:
        response = requests.get(
            f"{API_BASE}/marketing-os/search/search-console/recommendations",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        
        if response.status_code != 200:
            result.add_fail(
                "7.1 Recommendations status",
                f"Expected 200, got {response.status_code}: {response.text}"
            )
            return
        
        data = response.json()
        recommendations = data.get("recommendations", [])
        
        if not recommendations:
            result.add_warning(
                "7.1 Recommendations",
                "No recommendations returned (may be expected when disconnected)"
            )
            # Still check top-level flags
            if data.get("advisory_only") is True:
                result.add_pass("7.2 Top-level advisory_only", "advisory_only=true")
            else:
                result.add_fail("7.2 Top-level advisory_only", f"Expected true, got {data.get('advisory_only')}")
            
            if data.get("requires_human_approval") is True:
                result.add_pass("7.3 Top-level requires_human_approval", "requires_human_approval=true")
            else:
                result.add_fail("7.3 Top-level requires_human_approval", f"Expected true, got {data.get('requires_human_approval')}")
            return
        
        # Check every recommendation has correct flags
        all_correct = True
        for i, rec in enumerate(recommendations):
            if rec.get("advisory_only") is not True:
                result.add_fail(
                    f"7.{i+1}a Rec {i+1} advisory_only",
                    f"Expected advisory_only=true, got {rec.get('advisory_only')}"
                )
                all_correct = False
            
            if rec.get("requires_human_approval") is not True:
                result.add_fail(
                    f"7.{i+1}b Rec {i+1} requires_human_approval",
                    f"Expected requires_human_approval=true, got {rec.get('requires_human_approval')}"
                )
                all_correct = False
            
            if rec.get("external_write") is not False:
                result.add_fail(
                    f"7.{i+1}c Rec {i+1} external_write",
                    f"Expected external_write=false, got {rec.get('external_write')}"
                )
                all_correct = False
        
        if all_correct:
            result.add_pass(
                "7.1 All recommendations",
                f"All {len(recommendations)} recommendations have correct flags (advisory_only=true, requires_human_approval=true, external_write=false)"
            )
    
    except Exception as e:
        result.add_fail("7.x Advisory recommendations", f"Error: {str(e)}")


def test_scenario_8_safety_policy(result: TestResult, token: str):
    """Scenario 8: Safety policy - all flags correct"""
    print("\n[Scenario 8] Testing Safety Policy...")
    
    try:
        response = requests.get(
            f"{API_BASE}/marketing-os/capabilities",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        
        if response.status_code != 200:
            result.add_fail(
                "8.1 Capabilities status",
                f"Expected 200, got {response.status_code}: {response.text}"
            )
            return
        
        data = response.json()
        policy = data.get("policy", {})
        capabilities = data.get("capabilities", {})
        
        # Check policy flags
        policy_checks = [
            ("external_writes_enabled", False),
            ("automatic_budget_changes_enabled", False),
            ("automatic_campaign_creation_enabled", False),
            ("automatic_publishing_enabled", False),
            ("human_approval_required", True),
        ]
        
        for key, expected in policy_checks:
            actual = policy.get(key)
            if actual == expected:
                result.add_pass(
                    f"8.{policy_checks.index((key, expected)) + 1} policy.{key}",
                    f"{key}={expected}"
                )
            else:
                result.add_fail(
                    f"8.{policy_checks.index((key, expected)) + 1} policy.{key}",
                    f"Expected {key}={expected}, got {actual}"
                )
        
        # Check google_search_console capability flags
        gsc_cap = capabilities.get("google_search_console", {})
        gsc_checks = [
            ("write_enabled", False),
            ("external_write_enabled", False),
            ("phi_stored", False),
            ("position_is_serp_rank", False),
        ]
        
        for key, expected in gsc_checks:
            actual = gsc_cap.get(key)
            if actual == expected:
                result.add_pass(
                    f"8.{len(policy_checks) + gsc_checks.index((key, expected)) + 1} gsc.{key}",
                    f"{key}={expected}"
                )
            else:
                result.add_fail(
                    f"8.{len(policy_checks) + gsc_checks.index((key, expected)) + 1} gsc.{key}",
                    f"Expected {key}={expected}, got {actual}"
                )
    
    except Exception as e:
        result.add_fail("8.x Safety policy", f"Error: {str(e)}")


def main():
    print("="*80)
    print("PHASE 2: GOOGLE SEARCH CONSOLE (READ-ONLY) + RANK TRACKING")
    print("Backend Testing Suite")
    print("="*80)
    
    result = TestResult()
    
    # Scenario 1: Auth gate
    admin_token = test_scenario_1_auth(result)
    if not admin_token:
        print("\n❌ Cannot proceed without admin token")
        result.print_summary()
        return
    
    # Scenario 2: Readiness
    test_scenario_2_readiness(result, admin_token)
    
    # Scenario 3: Sync safe no-op
    test_scenario_3_sync_safe_noop(result, admin_token)
    
    # Scenario 4: Honest empty reads
    test_scenario_4_honest_empty_reads(result, admin_token)
    
    # Scenario 5: Rank tracking
    test_scenario_5_rank_tracking(result, admin_token)
    
    # Scenario 6: Overview honesty
    test_scenario_6_overview_honesty(result, admin_token)
    
    # Scenario 7: Advisory recommendations
    test_scenario_7_advisory_recommendations(result, admin_token)
    
    # Scenario 8: Safety policy
    test_scenario_8_safety_policy(result, admin_token)
    
    # Print summary
    result.print_summary()


if __name__ == "__main__":
    main()
