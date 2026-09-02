"""
Phase 3: Competitor Intelligence + Keyword Gap + Backlink + Local SEO Backend Tests

Tests all 8 scenarios for Phase 3 integration:
1. AUTH: Unauthenticated rejected, admin allowed
2. SITE: Ensure site exists (create if needed)
3. COMPETITORS (first-party): POST, GET list, GET by id, PHI reject
4. KEYWORD GAP: GET with connected=false, not_connected_reason, records=[]
5. CONTENT OPPORTUNITIES: GET with advisory_only=true, requires_human_approval=true
6. BACKLINKS: GET overview with connected=false and NULL counts (NOT 0), GET list
7. LOCAL SEO: GET with connected=false, GET opportunities with advisory_only=true
8. SAFETY: GET capabilities with correct policy flags
"""

import requests
import json
from typing import Optional

# Base URL from frontend/.env
BASE_URL = "https://nms-nurture-phase8.preview.emergentagent.com"
API_BASE = f"{BASE_URL}/api"

# Test credentials from /app/memory/test_credentials.md
ADMIN_EMAIL = "admin@natmedsol.local"
ADMIN_PASSWORD = "Admin!2345"


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
        print("PHASE 3 COMPETITOR INTELLIGENCE + KEYWORD GAP + BACKLINK + LOCAL SEO")
        print("Backend Test Results")
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
                print(f"⚠️  MFA required for {email}. Report this in test results.")
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
            f"{API_BASE}/marketing-os/search/competitors",
            timeout=10
        )
        if response.status_code in [401, 403]:
            result.add_pass(
                "1.1 Unauthenticated rejected",
                f"GET /competitors returned {response.status_code}"
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
        result.add_fail("1.2 Admin login", "Failed to login as admin (MFA may be required)")
        return None
    
    try:
        response = requests.get(
            f"{API_BASE}/marketing-os/search/competitors",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=10
        )
        if response.status_code == 200:
            result.add_pass(
                "1.2 Admin access",
                "GET /competitors returned 200"
            )
        else:
            result.add_fail(
                "1.2 Admin access",
                f"Expected 200, got {response.status_code}: {response.text}"
            )
    except Exception as e:
        result.add_fail("1.2 Admin access", f"Error: {str(e)}")
    
    return admin_token


def test_scenario_2_site(result: TestResult, token: str):
    """Scenario 2: Ensure site exists (create if needed)"""
    print("\n[Scenario 2] Testing Site Registration...")
    
    try:
        # Check if competitors endpoint returns connected=false (no site)
        response = requests.get(
            f"{API_BASE}/marketing-os/search/competitors",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        
        if response.status_code != 200:
            result.add_fail(
                "2.1 Check site status",
                f"Expected 200, got {response.status_code}: {response.text}"
            )
            return
        
        data = response.json()
        if data.get("connected") is False:
            # Need to create a site
            result.add_pass(
                "2.1 Site not connected",
                "connected=false (no site configured)"
            )
            
            # Create site
            response = requests.post(
                f"{API_BASE}/marketing-os/search/sites",
                headers={"Authorization": f"Bearer {token}"},
                json={"site_url": "https://natmedsol.com", "label": "NMS"},
                timeout=10
            )
            
            if response.status_code == 201:
                result.add_pass(
                    "2.2 Site created",
                    f"POST /sites returned 201"
                )
            else:
                result.add_fail(
                    "2.2 Site created",
                    f"Expected 201, got {response.status_code}: {response.text}"
                )
        else:
            result.add_pass(
                "2.1 Site already exists",
                "connected=true (site already configured)"
            )
    
    except Exception as e:
        result.add_fail("2.x Site registration", f"Error: {str(e)}")


def test_scenario_3_competitors(result: TestResult, token: str):
    """Scenario 3: Competitors (first-party) - POST, GET list, GET by id, PHI reject"""
    print("\n[Scenario 3] Testing Competitors (First-Party)...")
    
    # Test 3.1: POST competitor with domain normalization
    try:
        response = requests.post(
            f"{API_BASE}/marketing-os/search/competitors",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "domain": "https://www.rival-clinic.com",
                "display_name": "Rival Clinic"
            },
            timeout=10
        )
        
        if response.status_code == 201:
            data = response.json()
            normalized = data.get("normalized_domain")
            if normalized == "rival-clinic.com":
                result.add_pass(
                    "3.1 POST competitor",
                    f"201 created, normalized_domain='rival-clinic.com'"
                )
                competitor_id = data.get("id")
            else:
                result.add_fail(
                    "3.1 POST competitor",
                    f"Expected normalized_domain='rival-clinic.com', got '{normalized}'"
                )
                competitor_id = data.get("id")
        else:
            result.add_fail(
                "3.1 POST competitor",
                f"Expected 201, got {response.status_code}: {response.text}"
            )
            competitor_id = None
    except Exception as e:
        result.add_fail("3.1 POST competitor", f"Error: {str(e)}")
        competitor_id = None
    
    # Test 3.2: GET list shows competitor
    try:
        response = requests.get(
            f"{API_BASE}/marketing-os/search/competitors",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            competitors = data.get("competitors", [])
            if len(competitors) > 0:
                result.add_pass(
                    "3.2 GET competitors list",
                    f"200 OK, {len(competitors)} competitor(s) listed"
                )
            else:
                result.add_fail(
                    "3.2 GET competitors list",
                    "Expected at least 1 competitor, got 0"
                )
        else:
            result.add_fail(
                "3.2 GET competitors list",
                f"Expected 200, got {response.status_code}: {response.text}"
            )
    except Exception as e:
        result.add_fail("3.2 GET competitors list", f"Error: {str(e)}")
    
    # Test 3.3: GET competitor by id
    if competitor_id:
        try:
            response = requests.get(
                f"{API_BASE}/marketing-os/search/competitors/{competitor_id}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                comparison = data.get("comparison", {})
                data_available = comparison.get("data_available")
                
                if data_available is False:
                    reason = comparison.get("reason")
                    if reason == "no_competitor_data_provider":
                        result.add_pass(
                            "3.3 GET competitor by id",
                            f"200 OK, comparison.data_available=false, reason='no_competitor_data_provider'"
                        )
                    else:
                        result.add_fail(
                            "3.3 GET competitor by id",
                            f"Expected reason='no_competitor_data_provider', got '{reason}'"
                        )
                else:
                    result.add_fail(
                        "3.3 GET competitor by id",
                        f"Expected data_available=false, got {data_available}"
                    )
            else:
                result.add_fail(
                    "3.3 GET competitor by id",
                    f"Expected 200, got {response.status_code}: {response.text}"
                )
        except Exception as e:
            result.add_fail("3.3 GET competitor by id", f"Error: {str(e)}")
    else:
        result.add_warning("3.3 GET competitor by id", "Skipped (no competitor_id)")
    
    # Test 3.4: PHI rejection - POST with email field
    try:
        response = requests.post(
            f"{API_BASE}/marketing-os/search/competitors",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "domain": "https://x.com",
                "email": "a@b.com"
            },
            timeout=10
        )
        
        if response.status_code == 400 or response.status_code == 422:
            result.add_pass(
                "3.4 PHI rejection",
                f"POST with email field rejected with {response.status_code}"
            )
        else:
            result.add_fail(
                "3.4 PHI rejection",
                f"Expected 400/422, got {response.status_code}: {response.text}"
            )
    except Exception as e:
        result.add_fail("3.4 PHI rejection", f"Error: {str(e)}")


def test_scenario_4_keyword_gap(result: TestResult, token: str):
    """Scenario 4: Keyword gap - connected=false, not_connected_reason, records=[]"""
    print("\n[Scenario 4] Testing Keyword Gap...")
    
    try:
        response = requests.get(
            f"{API_BASE}/marketing-os/search/keyword-gap",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        
        if response.status_code != 200:
            result.add_fail(
                "4.1 Keyword gap status",
                f"Expected 200, got {response.status_code}: {response.text}"
            )
            return
        
        data = response.json()
        
        # Check connected=false
        if data.get("connected") is False:
            result.add_pass(
                "4.1 Keyword gap connected",
                "connected=false"
            )
        else:
            result.add_fail(
                "4.1 Keyword gap connected",
                f"Expected connected=false, got {data.get('connected')}"
            )
        
        # Check not_connected_reason
        reason = data.get("not_connected_reason")
        if reason == "no_competitor_data_provider":
            result.add_pass(
                "4.2 Not connected reason",
                "not_connected_reason='no_competitor_data_provider'"
            )
        else:
            result.add_fail(
                "4.2 Not connected reason",
                f"Expected 'no_competitor_data_provider', got '{reason}'"
            )
        
        # Check records=[]
        records = data.get("records", None)
        if records == []:
            result.add_pass(
                "4.3 Records empty",
                "records=[]"
            )
        else:
            result.add_fail(
                "4.3 Records empty",
                f"Expected records=[], got {len(records) if records else 'null'} items"
            )
        
        # Check summary present with numeric zero counts (acceptable for count of zero records)
        summary = data.get("summary", {})
        if summary:
            result.add_pass(
                "4.4 Summary present",
                f"summary present with keys: {list(summary.keys())}"
            )
        else:
            result.add_fail(
                "4.4 Summary present",
                "summary not present"
            )
    
    except Exception as e:
        result.add_fail("4.x Keyword gap", f"Error: {str(e)}")


def test_scenario_5_content_opportunities(result: TestResult, token: str):
    """Scenario 5: Content opportunities - advisory_only=true, requires_human_approval=true"""
    print("\n[Scenario 5] Testing Content Opportunities...")
    
    try:
        response = requests.get(
            f"{API_BASE}/marketing-os/search/content-opportunities",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        
        if response.status_code != 200:
            result.add_fail(
                "5.1 Content opportunities status",
                f"Expected 200, got {response.status_code}: {response.text}"
            )
            return
        
        data = response.json()
        
        # Check advisory_only=true
        if data.get("advisory_only") is True:
            result.add_pass(
                "5.1 Advisory only",
                "advisory_only=true"
            )
        else:
            result.add_fail(
                "5.1 Advisory only",
                f"Expected advisory_only=true, got {data.get('advisory_only')}"
            )
        
        # Check requires_human_approval=true
        if data.get("requires_human_approval") is True:
            result.add_pass(
                "5.2 Requires human approval",
                "requires_human_approval=true"
            )
        else:
            result.add_fail(
                "5.2 Requires human approval",
                f"Expected requires_human_approval=true, got {data.get('requires_human_approval')}"
            )
        
        # Check opportunities is a list
        opportunities = data.get("opportunities")
        if isinstance(opportunities, list):
            result.add_pass(
                "5.3 Opportunities list",
                f"opportunities is a list with {len(opportunities)} items"
            )
            
            # If any items exist, check external_write=false
            if len(opportunities) > 0:
                all_correct = True
                for i, opp in enumerate(opportunities):
                    if opp.get("external_write") is not False:
                        result.add_fail(
                            f"5.4 Opportunity {i+1} external_write",
                            f"Expected external_write=false, got {opp.get('external_write')}"
                        )
                        all_correct = False
                
                if all_correct:
                    result.add_pass(
                        "5.4 All opportunities external_write",
                        f"All {len(opportunities)} opportunities have external_write=false"
                    )
        else:
            result.add_fail(
                "5.3 Opportunities list",
                f"Expected opportunities to be a list, got {type(opportunities)}"
            )
    
    except Exception as e:
        result.add_fail("5.x Content opportunities", f"Error: {str(e)}")


def test_scenario_6_backlinks(result: TestResult, token: str):
    """Scenario 6: Backlinks - overview with connected=false and NULL counts (NOT 0), list empty"""
    print("\n[Scenario 6] Testing Backlinks...")
    
    # Test 6.1: Backlinks overview
    try:
        response = requests.get(
            f"{API_BASE}/marketing-os/search/backlinks/overview",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        
        if response.status_code != 200:
            result.add_fail(
                "6.1 Backlinks overview status",
                f"Expected 200, got {response.status_code}: {response.text}"
            )
        else:
            data = response.json()
            
            # Check connected=false
            if data.get("connected") is False:
                result.add_pass(
                    "6.1a Backlinks connected",
                    "connected=false"
                )
            else:
                result.add_fail(
                    "6.1a Backlinks connected",
                    f"Expected connected=false, got {data.get('connected')}"
                )
            
            # Check counts are NULL (not 0)
            count_fields = ["backlink_count", "referring_domains", "new_backlinks", "lost_backlinks"]
            all_null = True
            for field in count_fields:
                value = data.get(field)
                if value is not None:
                    result.add_fail(
                        f"6.1b {field}",
                        f"Expected null, got {value} (must be null, NOT 0)"
                    )
                    all_null = False
            
            if all_null:
                result.add_pass(
                    "6.1b Backlink counts NULL",
                    "All counts (backlink_count, referring_domains, new_backlinks, lost_backlinks) are null (NOT 0)"
                )
    
    except Exception as e:
        result.add_fail("6.1 Backlinks overview", f"Error: {str(e)}")
    
    # Test 6.2: Backlinks list
    try:
        response = requests.get(
            f"{API_BASE}/marketing-os/search/backlinks",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        
        if response.status_code != 200:
            result.add_fail(
                "6.2 Backlinks list status",
                f"Expected 200, got {response.status_code}: {response.text}"
            )
        else:
            data = response.json()
            
            # Check backlinks=[]
            backlinks = data.get("backlinks", None)
            if backlinks == []:
                result.add_pass(
                    "6.2a Backlinks empty",
                    "backlinks=[]"
                )
            else:
                result.add_fail(
                    "6.2a Backlinks empty",
                    f"Expected backlinks=[], got {len(backlinks) if backlinks else 'null'} items"
                )
            
            # Check not_connected_reason present
            reason = data.get("not_connected_reason")
            if reason:
                result.add_pass(
                    "6.2b Not connected reason",
                    f"not_connected_reason='{reason}'"
                )
            else:
                result.add_fail(
                    "6.2b Not connected reason",
                    "not_connected_reason not present"
                )
    
    except Exception as e:
        result.add_fail("6.2 Backlinks list", f"Error: {str(e)}")


def test_scenario_7_local_seo(result: TestResult, token: str):
    """Scenario 7: Local SEO - connected=false, not_connected_reason, opportunities advisory_only=true"""
    print("\n[Scenario 7] Testing Local SEO...")
    
    # Test 7.1: Local SEO endpoint
    try:
        response = requests.get(
            f"{API_BASE}/marketing-os/search/local",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        
        if response.status_code != 200:
            result.add_fail(
                "7.1 Local SEO status",
                f"Expected 200, got {response.status_code}: {response.text}"
            )
        else:
            data = response.json()
            
            # Check connected=false
            if data.get("connected") is False:
                result.add_pass(
                    "7.1a Local connected",
                    "connected=false"
                )
            else:
                result.add_fail(
                    "7.1a Local connected",
                    f"Expected connected=false, got {data.get('connected')}"
                )
            
            # Check not_connected_reason
            reason = data.get("not_connected_reason")
            if reason == "no_local_data_source":
                result.add_pass(
                    "7.1b Not connected reason",
                    "not_connected_reason='no_local_data_source'"
                )
            else:
                result.add_fail(
                    "7.1b Not connected reason",
                    f"Expected 'no_local_data_source', got '{reason}'"
                )
            
            # Check locations=[]
            locations = data.get("locations", None)
            if locations == []:
                result.add_pass(
                    "7.1c Locations empty",
                    "locations=[]"
                )
            else:
                result.add_fail(
                    "7.1c Locations empty",
                    f"Expected locations=[], got {len(locations) if locations else 'null'} items"
                )
    
    except Exception as e:
        result.add_fail("7.1 Local SEO", f"Error: {str(e)}")
    
    # Test 7.2: Local opportunities
    try:
        response = requests.get(
            f"{API_BASE}/marketing-os/search/local/opportunities",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        
        if response.status_code != 200:
            result.add_fail(
                "7.2 Local opportunities status",
                f"Expected 200, got {response.status_code}: {response.text}"
            )
        else:
            data = response.json()
            
            # Check advisory_only=true
            if data.get("advisory_only") is True:
                result.add_pass(
                    "7.2a Advisory only",
                    "advisory_only=true"
                )
            else:
                result.add_fail(
                    "7.2a Advisory only",
                    f"Expected advisory_only=true, got {data.get('advisory_only')}"
                )
            
            # Check requires_human_approval=true
            if data.get("requires_human_approval") is True:
                result.add_pass(
                    "7.2b Requires human approval",
                    "requires_human_approval=true"
                )
            else:
                result.add_fail(
                    "7.2b Requires human approval",
                    f"Expected requires_human_approval=true, got {data.get('requires_human_approval')}"
                )
    
    except Exception as e:
        result.add_fail("7.2 Local opportunities", f"Error: {str(e)}")


def test_scenario_8_safety(result: TestResult, token: str):
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
        
        # Check policy flags
        policy_checks = [
            ("external_writes_enabled", False),
            ("automatic_budget_changes_enabled", False),
            ("automatic_campaign_creation_enabled", False),
            ("automatic_publishing_enabled", False),
            ("human_approval_required", True),
        ]
        
        all_correct = True
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
                all_correct = False
    
    except Exception as e:
        result.add_fail("8.x Safety policy", f"Error: {str(e)}")


def main():
    print("="*80)
    print("PHASE 3: COMPETITOR INTELLIGENCE + KEYWORD GAP + BACKLINK + LOCAL SEO")
    print("Backend Testing Suite")
    print("="*80)
    
    result = TestResult()
    
    # Scenario 1: Auth gate
    admin_token = test_scenario_1_auth(result)
    if not admin_token:
        print("\n❌ Cannot proceed without admin token")
        result.print_summary()
        return
    
    # Scenario 2: Site registration
    test_scenario_2_site(result, admin_token)
    
    # Scenario 3: Competitors (first-party)
    test_scenario_3_competitors(result, admin_token)
    
    # Scenario 4: Keyword gap
    test_scenario_4_keyword_gap(result, admin_token)
    
    # Scenario 5: Content opportunities
    test_scenario_5_content_opportunities(result, admin_token)
    
    # Scenario 6: Backlinks
    test_scenario_6_backlinks(result, admin_token)
    
    # Scenario 7: Local SEO
    test_scenario_7_local_seo(result, admin_token)
    
    # Scenario 8: Safety policy
    test_scenario_8_safety(result, admin_token)
    
    # Print summary
    result.print_summary()


if __name__ == "__main__":
    main()
