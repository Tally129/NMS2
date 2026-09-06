#!/usr/bin/env python3
"""
Backend testing for NMS Marketing OS paid-media phase (sandbox, no provider credentials).
Tests all scenarios specified in the review request.
"""

import os
import sys
import requests
from datetime import date, timedelta

# Base URL from frontend/.env
BASE_URL = "https://seo-command-center-24.preview.emergentagent.com"
API_BASE = f"{BASE_URL}/api"

# Test credentials from /app/memory/test_credentials.md
ADMIN_EMAIL = "admin@natmedsol.local"
ADMIN_PASSWORD = "Admin!2345"
PRACTITIONER_EMAIL = "ravello@natmedsol.local"
PRACTITIONER_PASSWORD = "Ravello!2345"

# Test results tracking
test_results = []


def log_test(scenario, test_name, passed, details=""):
    """Log test result"""
    status = "✅ PASS" if passed else "❌ FAIL"
    test_results.append({
        "scenario": scenario,
        "test": test_name,
        "passed": passed,
        "details": details
    })
    print(f"{status} | {scenario} | {test_name}")
    if details and not passed:
        print(f"  Details: {details}")


def login(email, password):
    """Login and return access token"""
    response = requests.post(
        f"{API_BASE}/auth/login",
        json={"email": email, "password": password},
        timeout=30
    )
    if response.status_code == 200:
        data = response.json()
        return data.get("access_token")
    else:
        print(f"Login failed for {email}: {response.status_code} {response.text}")
        return None


def test_scenario_1_sync_status():
    """
    Scenario 1: GET /api/marketing-os/paid/sync-status
    - Admin: scheduler_enabled false; items has exactly 3 providers (google_ads, meta_ads, microsoft_ads)
      each connected false, readiness "not_connected", cached_campaigns 0, cached_rows 0, last_successful_sync null
    - Practitioner: 200 too
    - No token: 401/403
    """
    print("\n=== SCENARIO 1: GET /api/marketing-os/paid/sync-status ===")
    
    # Test 1.1: No token -> 401/403
    response = requests.get(f"{API_BASE}/marketing-os/paid/sync-status", timeout=30)
    passed = response.status_code in [401, 403]
    log_test("Scenario 1", "No token -> 401/403", passed, 
             f"Expected 401/403, got {response.status_code}")
    
    # Test 1.2: Admin token -> 200 with correct structure
    admin_token = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    if not admin_token:
        log_test("Scenario 1", "Admin login", False, "Failed to get admin token")
        return
    
    headers = {"Authorization": f"Bearer {admin_token}"}
    response = requests.get(f"{API_BASE}/marketing-os/paid/sync-status", headers=headers, timeout=30)
    
    if response.status_code != 200:
        log_test("Scenario 1", "Admin GET sync-status -> 200", False, 
                 f"Expected 200, got {response.status_code}: {response.text}")
        return
    
    data = response.json()
    log_test("Scenario 1", "Admin GET sync-status -> 200", True)
    
    # Check scheduler_enabled
    passed = data.get("scheduler_enabled") == False
    log_test("Scenario 1", "scheduler_enabled = false", passed, 
             f"Expected false, got {data.get('scheduler_enabled')}")
    
    # Check items has exactly 3 providers
    items = data.get("items", [])
    passed = len(items) == 3
    log_test("Scenario 1", "items has exactly 3 providers", passed, 
             f"Expected 3, got {len(items)}")
    
    # Check each provider
    expected_providers = {"google_ads", "meta_ads", "microsoft_ads"}
    actual_providers = {item.get("provider") for item in items}
    passed = actual_providers == expected_providers
    log_test("Scenario 1", "providers are google_ads, meta_ads, microsoft_ads", passed, 
             f"Expected {expected_providers}, got {actual_providers}")
    
    # Check each provider's fields
    for item in items:
        provider = item.get("provider")
        
        # connected = false
        passed = item.get("connected") == False
        log_test("Scenario 1", f"{provider}: connected = false", passed, 
                 f"Expected false, got {item.get('connected')}")
        
        # readiness = "not_connected"
        passed = item.get("readiness") == "not_connected"
        log_test("Scenario 1", f"{provider}: readiness = 'not_connected'", passed, 
                 f"Expected 'not_connected', got {item.get('readiness')}")
        
        # cached_campaigns = 0
        passed = item.get("cached_campaigns") == 0
        log_test("Scenario 1", f"{provider}: cached_campaigns = 0", passed, 
                 f"Expected 0, got {item.get('cached_campaigns')}")
        
        # cached_rows = 0
        passed = item.get("cached_rows") == 0
        log_test("Scenario 1", f"{provider}: cached_rows = 0", passed, 
                 f"Expected 0, got {item.get('cached_rows')}")
        
        # last_successful_sync = null
        passed = item.get("last_successful_sync") is None
        log_test("Scenario 1", f"{provider}: last_successful_sync = null", passed, 
                 f"Expected null, got {item.get('last_successful_sync')}")
    
    # Test 1.3: Practitioner token -> 200
    practitioner_token = login(PRACTITIONER_EMAIL, PRACTITIONER_PASSWORD)
    if not practitioner_token:
        log_test("Scenario 1", "Practitioner login", False, "Failed to get practitioner token")
        return
    
    headers = {"Authorization": f"Bearer {practitioner_token}"}
    response = requests.get(f"{API_BASE}/marketing-os/paid/sync-status", headers=headers, timeout=30)
    passed = response.status_code == 200
    log_test("Scenario 1", "Practitioner GET sync-status -> 200", passed, 
             f"Expected 200, got {response.status_code}")


def test_scenario_2_campaigns():
    """
    Scenario 2: GET /api/marketing-os/paid/campaigns
    - Default: 200 {items: [], total 0, start_date/end_date = default 30-day window ending yesterday}
    - ?provider=meta_ads,google_ads -> 200
    - ?provider=tiktok -> 422
    - ?start_date=2026-01-01&end_date=2026-09-05 -> 422 (range > 93 days)
    - ?start_date=2026-09-05&end_date=2026-09-01 -> 422
    - ?limit=0 -> 422
    """
    print("\n=== SCENARIO 2: GET /api/marketing-os/paid/campaigns ===")
    
    admin_token = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    if not admin_token:
        log_test("Scenario 2", "Admin login", False, "Failed to get admin token")
        return
    
    headers = {"Authorization": f"Bearer {admin_token}"}
    
    # Test 2.1: Default request
    response = requests.get(f"{API_BASE}/marketing-os/paid/campaigns", headers=headers, timeout=30)
    
    if response.status_code != 200:
        log_test("Scenario 2", "Default GET campaigns -> 200", False, 
                 f"Expected 200, got {response.status_code}: {response.text}")
        return
    
    data = response.json()
    log_test("Scenario 2", "Default GET campaigns -> 200", True)
    
    # Check items = []
    passed = data.get("items") == []
    log_test("Scenario 2", "items = []", passed, 
             f"Expected [], got {data.get('items')}")
    
    # Check total = 0
    passed = data.get("total") == 0
    log_test("Scenario 2", "total = 0", passed, 
             f"Expected 0, got {data.get('total')}")
    
    # Check start_date/end_date (default 30-day window ending yesterday)
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=29)
    expected_start = start.isoformat()
    expected_end = end.isoformat()
    
    passed = data.get("start_date") == expected_start
    log_test("Scenario 2", f"start_date = {expected_start}", passed, 
             f"Expected {expected_start}, got {data.get('start_date')}")
    
    passed = data.get("end_date") == expected_end
    log_test("Scenario 2", f"end_date = {expected_end}", passed, 
             f"Expected {expected_end}, got {data.get('end_date')}")
    
    # Test 2.2: ?provider=meta_ads,google_ads -> 200
    response = requests.get(f"{API_BASE}/marketing-os/paid/campaigns?provider=meta_ads,google_ads", 
                           headers=headers, timeout=30)
    passed = response.status_code == 200
    log_test("Scenario 2", "?provider=meta_ads,google_ads -> 200", passed, 
             f"Expected 200, got {response.status_code}")
    
    # Test 2.3: ?provider=tiktok -> 422
    response = requests.get(f"{API_BASE}/marketing-os/paid/campaigns?provider=tiktok", 
                           headers=headers, timeout=30)
    passed = response.status_code == 422
    log_test("Scenario 2", "?provider=tiktok -> 422", passed, 
             f"Expected 422, got {response.status_code}")
    
    # Test 2.4: ?start_date=2026-01-01&end_date=2026-09-05 -> 422 (range > 93 days)
    response = requests.get(f"{API_BASE}/marketing-os/paid/campaigns?start_date=2026-01-01&end_date=2026-09-05", 
                           headers=headers, timeout=30)
    passed = response.status_code == 422
    log_test("Scenario 2", "?start_date=2026-01-01&end_date=2026-09-05 -> 422 (range > 93 days)", passed, 
             f"Expected 422, got {response.status_code}")
    
    # Test 2.5: ?start_date=2026-09-05&end_date=2026-09-01 -> 422
    response = requests.get(f"{API_BASE}/marketing-os/paid/campaigns?start_date=2026-09-05&end_date=2026-09-01", 
                           headers=headers, timeout=30)
    passed = response.status_code == 422
    log_test("Scenario 2", "?start_date=2026-09-05&end_date=2026-09-01 -> 422", passed, 
             f"Expected 422, got {response.status_code}")
    
    # Test 2.6: ?limit=0 -> 422
    response = requests.get(f"{API_BASE}/marketing-os/paid/campaigns?limit=0", 
                           headers=headers, timeout=30)
    passed = response.status_code == 422
    log_test("Scenario 2", "?limit=0 -> 422", passed, 
             f"Expected 422, got {response.status_code}")


def test_scenario_3_sync():
    """
    Scenario 3: POST /api/marketing-os/paid/{provider}/sync
    - Admin body {} -> 200 status "dry_run", live false, plan.provider "meta_ads", plan.days 30, 
      plan.provider_ready false, plan.external_write false, plan.tables includes "marketing_daily_metrics"
    - Body {"dry_run":false,"confirm":true} -> 409 with detail containing "not ready"
    - Same for microsoft_ads and google_ads (dry run 200 / confirm 409)
    - Body {"start_date":"2026-09-05","end_date":"2026-09-01"} -> 400
    - POST /paid/tiktok/sync -> 404
    - Practitioner POST -> 403
    """
    print("\n=== SCENARIO 3: POST /api/marketing-os/paid/{provider}/sync ===")
    
    admin_token = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    if not admin_token:
        log_test("Scenario 3", "Admin login", False, "Failed to get admin token")
        return
    
    headers = {"Authorization": f"Bearer {admin_token}"}
    
    # Test each provider: meta_ads, microsoft_ads, google_ads
    for provider in ["meta_ads", "microsoft_ads", "google_ads"]:
        # Test 3.1: Dry run (default) -> 200
        response = requests.post(f"{API_BASE}/marketing-os/paid/{provider}/sync", 
                                headers=headers, json={}, timeout=30)
        
        if response.status_code != 200:
            log_test("Scenario 3", f"{provider} dry run -> 200", False, 
                     f"Expected 200, got {response.status_code}: {response.text}")
            continue
        
        data = response.json()
        log_test("Scenario 3", f"{provider} dry run -> 200", True)
        
        # Check status = "dry_run"
        passed = data.get("status") == "dry_run"
        log_test("Scenario 3", f"{provider}: status = 'dry_run'", passed, 
                 f"Expected 'dry_run', got {data.get('status')}")
        
        # Check live = false
        passed = data.get("live") == False
        log_test("Scenario 3", f"{provider}: live = false", passed, 
                 f"Expected false, got {data.get('live')}")
        
        plan = data.get("plan", {})
        
        # Check plan.provider
        passed = plan.get("provider") == provider
        log_test("Scenario 3", f"{provider}: plan.provider = '{provider}'", passed, 
                 f"Expected '{provider}', got {plan.get('provider')}")
        
        # Check plan.days = 30
        passed = plan.get("days") == 30
        log_test("Scenario 3", f"{provider}: plan.days = 30", passed, 
                 f"Expected 30, got {plan.get('days')}")
        
        # Check plan.provider_ready = false
        passed = plan.get("provider_ready") == False
        log_test("Scenario 3", f"{provider}: plan.provider_ready = false", passed, 
                 f"Expected false, got {plan.get('provider_ready')}")
        
        # Check plan.external_write = false
        passed = plan.get("external_write") == False
        log_test("Scenario 3", f"{provider}: plan.external_write = false", passed, 
                 f"Expected false, got {plan.get('external_write')}")
        
        # Check plan.tables includes "marketing_daily_metrics"
        tables = plan.get("tables", [])
        passed = "marketing_daily_metrics" in tables
        log_test("Scenario 3", f"{provider}: plan.tables includes 'marketing_daily_metrics'", passed, 
                 f"Expected 'marketing_daily_metrics' in {tables}")
        
        # Test 3.2: Confirm (live) -> 409
        response = requests.post(f"{API_BASE}/marketing-os/paid/{provider}/sync", 
                                headers=headers, json={"dry_run": False, "confirm": True}, timeout=30)
        
        passed = response.status_code == 409
        log_test("Scenario 3", f"{provider} confirm -> 409", passed, 
                 f"Expected 409, got {response.status_code}")
        
        if response.status_code == 409:
            detail = response.json().get("detail", "")
            passed = "not ready" in detail.lower()
            log_test("Scenario 3", f"{provider} 409 detail contains 'not ready'", passed, 
                     f"Expected 'not ready' in detail, got: {detail}")
    
    # Test 3.3: Invalid date range -> 400
    response = requests.post(f"{API_BASE}/marketing-os/paid/meta_ads/sync", 
                            headers=headers, 
                            json={"start_date": "2026-09-05", "end_date": "2026-09-01"}, 
                            timeout=30)
    passed = response.status_code == 400
    log_test("Scenario 3", "Invalid date range -> 400", passed, 
             f"Expected 400, got {response.status_code}")
    
    # Test 3.4: Unknown provider (tiktok) -> 404
    response = requests.post(f"{API_BASE}/marketing-os/paid/tiktok/sync", 
                            headers=headers, json={}, timeout=30)
    passed = response.status_code == 404
    log_test("Scenario 3", "POST /paid/tiktok/sync -> 404", passed, 
             f"Expected 404, got {response.status_code}")
    
    # Test 3.5: Practitioner -> 403
    practitioner_token = login(PRACTITIONER_EMAIL, PRACTITIONER_PASSWORD)
    if not practitioner_token:
        log_test("Scenario 3", "Practitioner login", False, "Failed to get practitioner token")
        return
    
    headers = {"Authorization": f"Bearer {practitioner_token}"}
    response = requests.post(f"{API_BASE}/marketing-os/paid/meta_ads/sync", 
                            headers=headers, json={}, timeout=30)
    passed = response.status_code == 403
    log_test("Scenario 3", "Practitioner POST -> 403", passed, 
             f"Expected 403, got {response.status_code}")


def test_scenario_4_hierarchy():
    """
    Scenario 4: GET /api/marketing-os/paid/meta_ads/hierarchy
    - Admin -> 409 (not connected)
    - Practitioner -> 403
    """
    print("\n=== SCENARIO 4: GET /api/marketing-os/paid/meta_ads/hierarchy ===")
    
    # Test 4.1: Admin -> 409
    admin_token = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    if not admin_token:
        log_test("Scenario 4", "Admin login", False, "Failed to get admin token")
        return
    
    headers = {"Authorization": f"Bearer {admin_token}"}
    response = requests.get(f"{API_BASE}/marketing-os/paid/meta_ads/hierarchy", 
                           headers=headers, timeout=30)
    passed = response.status_code == 409
    log_test("Scenario 4", "Admin GET hierarchy -> 409 (not connected)", passed, 
             f"Expected 409, got {response.status_code}")
    
    # Test 4.2: Practitioner -> 403
    practitioner_token = login(PRACTITIONER_EMAIL, PRACTITIONER_PASSWORD)
    if not practitioner_token:
        log_test("Scenario 4", "Practitioner login", False, "Failed to get practitioner token")
        return
    
    headers = {"Authorization": f"Bearer {practitioner_token}"}
    response = requests.get(f"{API_BASE}/marketing-os/paid/meta_ads/hierarchy", 
                           headers=headers, timeout=30)
    passed = response.status_code == 403
    log_test("Scenario 4", "Practitioner GET hierarchy -> 403", passed, 
             f"Expected 403, got {response.status_code}")


def test_scenario_5_existing_routes():
    """
    Scenario 5: Existing routes still work
    - GET /api/marketing-os/paid/performance -> 200 with providers array containing google_ads, meta_ads, microsoft_ads entries
    - GET /api/marketing-os/paid/meta_ads/readiness -> 200 with status "not_connected"
    - GET /api/marketing-os/paid/microsoft_ads/readiness -> 200 with status "not_connected"
    """
    print("\n=== SCENARIO 5: Existing routes still work ===")
    
    admin_token = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    if not admin_token:
        log_test("Scenario 5", "Admin login", False, "Failed to get admin token")
        return
    
    headers = {"Authorization": f"Bearer {admin_token}"}
    
    # Test 5.1: GET /api/marketing-os/paid/performance
    response = requests.get(f"{API_BASE}/marketing-os/paid/performance", 
                           headers=headers, timeout=30)
    
    if response.status_code != 200:
        log_test("Scenario 5", "GET /paid/performance -> 200", False, 
                 f"Expected 200, got {response.status_code}: {response.text}")
        return
    
    data = response.json()
    log_test("Scenario 5", "GET /paid/performance -> 200", True)
    
    # Check providers array contains google_ads, meta_ads, microsoft_ads
    providers = data.get("providers", [])
    provider_names = {p.get("provider") for p in providers}
    expected_providers = {"google_ads", "meta_ads", "microsoft_ads"}
    passed = expected_providers.issubset(provider_names)
    log_test("Scenario 5", "providers array contains google_ads, meta_ads, microsoft_ads", passed, 
             f"Expected {expected_providers} in {provider_names}")
    
    # Test 5.2: GET /api/marketing-os/paid/meta_ads/readiness
    response = requests.get(f"{API_BASE}/marketing-os/paid/meta_ads/readiness", 
                           headers=headers, timeout=30)
    
    if response.status_code != 200:
        log_test("Scenario 5", "GET /paid/meta_ads/readiness -> 200", False, 
                 f"Expected 200, got {response.status_code}: {response.text}")
    else:
        data = response.json()
        log_test("Scenario 5", "GET /paid/meta_ads/readiness -> 200", True)
        
        passed = data.get("status") == "not_connected"
        log_test("Scenario 5", "meta_ads readiness status = 'not_connected'", passed, 
                 f"Expected 'not_connected', got {data.get('status')}")
    
    # Test 5.3: GET /api/marketing-os/paid/microsoft_ads/readiness
    response = requests.get(f"{API_BASE}/marketing-os/paid/microsoft_ads/readiness", 
                           headers=headers, timeout=30)
    
    if response.status_code != 200:
        log_test("Scenario 5", "GET /paid/microsoft_ads/readiness -> 200", False, 
                 f"Expected 200, got {response.status_code}: {response.text}")
    else:
        data = response.json()
        log_test("Scenario 5", "GET /paid/microsoft_ads/readiness -> 200", True)
        
        passed = data.get("status") == "not_connected"
        log_test("Scenario 5", "microsoft_ads readiness status = 'not_connected'", passed, 
                 f"Expected 'not_connected', got {data.get('status')}")


def test_scenario_6_regression():
    """
    Scenario 6: Regression tests
    - GET /api/marketing-os/search/overview still 200
    - GET /api/marketing-os/search/seo/provider-runs total still 24
    """
    print("\n=== SCENARIO 6: Regression tests ===")
    
    admin_token = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    if not admin_token:
        log_test("Scenario 6", "Admin login", False, "Failed to get admin token")
        return
    
    headers = {"Authorization": f"Bearer {admin_token}"}
    
    # Test 6.1: GET /api/marketing-os/search/overview
    response = requests.get(f"{API_BASE}/marketing-os/search/overview", 
                           headers=headers, timeout=30)
    passed = response.status_code == 200
    log_test("Scenario 6", "GET /search/overview -> 200 (regression)", passed, 
             f"Expected 200, got {response.status_code}")
    
    # Test 6.2: GET /api/marketing-os/search/seo/provider-runs
    response = requests.get(f"{API_BASE}/marketing-os/search/seo/provider-runs", 
                           headers=headers, timeout=30)
    
    if response.status_code != 200:
        log_test("Scenario 6", "GET /seo/provider-runs -> 200", False, 
                 f"Expected 200, got {response.status_code}: {response.text}")
    else:
        data = response.json()
        log_test("Scenario 6", "GET /seo/provider-runs -> 200", True)
        
        total = data.get("total")
        passed = total == 24
        log_test("Scenario 6", "provider-runs total = 24 (regression)", passed, 
                 f"Expected 24, got {total}")


def print_summary():
    """Print test summary"""
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    total = len(test_results)
    passed = sum(1 for r in test_results if r["passed"])
    failed = total - passed
    
    print(f"\nTotal tests: {total}")
    print(f"Passed: {passed} ({100*passed//total if total > 0 else 0}%)")
    print(f"Failed: {failed}")
    
    if failed > 0:
        print("\n" + "="*80)
        print("FAILED TESTS")
        print("="*80)
        for result in test_results:
            if not result["passed"]:
                print(f"\n❌ {result['scenario']} | {result['test']}")
                if result["details"]:
                    print(f"   {result['details']}")
    
    print("\n" + "="*80)


def main():
    """Run all tests"""
    print("="*80)
    print("NMS Marketing OS Paid-Media Phase Testing")
    print("Sandbox environment (no provider credentials)")
    print("="*80)
    
    try:
        test_scenario_1_sync_status()
        test_scenario_2_campaigns()
        test_scenario_3_sync()
        test_scenario_4_hierarchy()
        test_scenario_5_existing_routes()
        test_scenario_6_regression()
    except Exception as e:
        print(f"\n❌ CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print_summary()


if __name__ == "__main__":
    main()
