#!/usr/bin/env python3
"""
Backend testing for NMS Marketing OS SEO phase-2 routes.
Tests read-only cached SEO intelligence + governed refresh dry-run.
"""

import json
import requests
from typing import Optional

# Base URL from frontend/.env
BASE_URL = "https://seo-command-center-24.preview.emergentagent.com/api"

# Test credentials
ADMIN_EMAIL = "admin@natmedsol.local"
ADMIN_PASSWORD = "Admin!2345"
PRACTITIONER_EMAIL = "ravello@natmedsol.local"
PRACTITIONER_PASSWORD = "Ravello!2345"


class TestClient:
    def __init__(self):
        self.admin_token: Optional[str] = None
        self.practitioner_token: Optional[str] = None
        self.session = requests.Session()
        
    def login(self, email: str, password: str) -> str:
        """Login and return access token"""
        response = self.session.post(
            f"{BASE_URL}/auth/login",
            json={"email": email, "password": password}
        )
        print(f"Login {email}: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            token = data.get("access_token")
            print(f"  Token obtained: {token[:20]}..." if token else "  No token in response")
            return token
        else:
            print(f"  Login failed: {response.text}")
            return None
    
    def get(self, path: str, token: str, params: dict = None) -> requests.Response:
        """GET request with Bearer token"""
        headers = {"Authorization": f"Bearer {token}"}
        return self.session.get(f"{BASE_URL}{path}", headers=headers, params=params)
    
    def post(self, path: str, token: str, json_data: dict = None) -> requests.Response:
        """POST request with Bearer token"""
        headers = {"Authorization": f"Bearer {token}"}
        return self.session.post(f"{BASE_URL}{path}", headers=headers, json=json_data)
    
    def put(self, path: str, token: str, json_data: dict = None) -> requests.Response:
        """PUT request with Bearer token"""
        headers = {"Authorization": f"Bearer {token}"}
        return self.session.put(f"{BASE_URL}{path}", headers=headers, json=json_data)
    
    def delete(self, path: str, token: str) -> requests.Response:
        """DELETE request with Bearer token"""
        headers = {"Authorization": f"Bearer {token}"}
        return self.session.delete(f"{BASE_URL}{path}", headers=headers)


def test_seo_phase2():
    """Test all SEO phase-2 backend routes"""
    client = TestClient()
    
    print("\n" + "="*80)
    print("SEO PHASE-2 BACKEND TESTING")
    print("="*80)
    
    # Login
    print("\n--- LOGIN ---")
    admin_token = client.login(ADMIN_EMAIL, ADMIN_PASSWORD)
    practitioner_token = client.login(PRACTITIONER_EMAIL, PRACTITIONER_PASSWORD)
    
    if not admin_token:
        print("❌ CRITICAL: Admin login failed. Cannot proceed.")
        return
    
    print(f"✅ Admin token: {admin_token[:30]}...")
    if practitioner_token:
        print(f"✅ Practitioner token: {practitioner_token[:30]}...")
    
    # Record initial provider-runs total
    print("\n--- INITIAL PROVIDER-RUNS COUNT ---")
    resp = client.get("/marketing-os/search/seo/provider-runs", admin_token)
    print(f"GET /seo/provider-runs: {resp.status_code}")
    if resp.status_code == 200:
        initial_total = resp.json().get("total", 0)
        print(f"  Initial total: {initial_total}")
    else:
        print(f"  ❌ Failed to get initial count: {resp.text}")
        initial_total = None
    
    # TEST 1: GET /api/marketing-os/search/overview
    print("\n--- TEST 1: GET /api/marketing-os/search/overview ---")
    resp = client.get("/marketing-os/search/overview", admin_token)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"Response keys: {list(data.keys())}")
        
        # Check metrics
        metrics = data.get("metrics", {})
        print(f"\nMetrics keys: {list(metrics.keys())}")
        
        # organic_competitors
        oc = metrics.get("organic_competitors", {})
        print(f"\norganic_competitors: {oc}")
        if oc.get("value") == 3 and oc.get("source") == "dataforseo":
            print("  ✅ organic_competitors: value=3, source=dataforseo")
        else:
            print(f"  ❌ organic_competitors: expected value=3, source=dataforseo, got {oc}")
        
        # competitor_common_keywords
        cck = metrics.get("competitor_common_keywords", {})
        print(f"\ncompetitor_common_keywords: {cck}")
        if cck.get("value") == 930:
            print("  ✅ competitor_common_keywords: value=930")
        else:
            print(f"  ❌ competitor_common_keywords: expected value=930, got {cck}")
        
        # keyword_opportunities
        ko = metrics.get("keyword_opportunities", {})
        print(f"\nkeyword_opportunities: {ko}")
        if ko.get("value") == 80:
            print("  ✅ keyword_opportunities: value=80")
        else:
            print(f"  ❌ keyword_opportunities: expected value=80, got {ko}")
        
        # backlink_count
        bc = metrics.get("backlink_count", {})
        print(f"\nbacklink_count: {bc}")
        if bc.get("value") == 1842 and bc.get("source") == "dataforseo":
            print("  ✅ backlink_count: value=1842, source=dataforseo")
        else:
            print(f"  ❌ backlink_count: expected value=1842, source=dataforseo, got {bc}")
        
        # referring_domain_count
        rdc = metrics.get("referring_domain_count", {})
        print(f"\nreferring_domain_count: {rdc}")
        if rdc.get("value") == 263:
            print("  ✅ referring_domain_count: value=263")
        else:
            print(f"  ❌ referring_domain_count: expected value=263, got {rdc}")
        
        # backlink_new_links_sampled
        bnls = metrics.get("backlink_new_links_sampled", {})
        print(f"\nbacklink_new_links_sampled: {bnls}")
        if bnls.get("value") == 14:
            print("  ✅ backlink_new_links_sampled: value=14")
        else:
            print(f"  ❌ backlink_new_links_sampled: expected value=14, got {bnls}")
        
        # backlink_lost_links_sampled
        blls = metrics.get("backlink_lost_links_sampled", {})
        print(f"\nbacklink_lost_links_sampled: {blls}")
        if blls.get("value") == 8:
            print("  ✅ backlink_lost_links_sampled: value=8")
        else:
            print(f"  ❌ backlink_lost_links_sampled: expected value=8, got {blls}")
        
        # rt_tracked_keywords
        rtk = metrics.get("rt_tracked_keywords", {})
        print(f"\nrt_tracked_keywords: {rtk}")
        if rtk.get("value") == 5 and rtk.get("source") == "dataforseo_serp":
            print("  ✅ rt_tracked_keywords: value=5, source=dataforseo_serp")
        else:
            print(f"  ❌ rt_tracked_keywords: expected value=5, source=dataforseo_serp, got {rtk}")
        
        # rt_top_20, rt_improved, rt_declined
        rt20 = metrics.get("rt_top_20", {})
        print(f"\nrt_top_20: {rt20}")
        if isinstance(rt20.get("value"), (int, float)):
            print(f"  ✅ rt_top_20: numeric value={rt20.get('value')}")
        else:
            print(f"  ❌ rt_top_20: expected numeric, got {rt20}")
        
        rti = metrics.get("rt_improved", {})
        print(f"\nrt_improved: {rti}")
        if isinstance(rti.get("value"), (int, float)):
            print(f"  ✅ rt_improved: numeric value={rti.get('value')}")
        else:
            print(f"  ❌ rt_improved: expected numeric, got {rti}")
        
        rtd = metrics.get("rt_declined", {})
        print(f"\nrt_declined: {rtd}")
        if isinstance(rtd.get("value"), (int, float)):
            print(f"  ✅ rt_declined: numeric value={rtd.get('value')}")
        else:
            print(f"  ❌ rt_declined: expected numeric, got {rtd}")
        
        # organic_keywords
        ok = metrics.get("organic_keywords", {})
        print(f"\norganic_keywords: {ok}")
        if ok.get("value") == 1017 and ok.get("source") == "dataforseo":
            print("  ✅ organic_keywords: value=1017, source=dataforseo")
        else:
            print(f"  ❌ organic_keywords: expected value=1017, source=dataforseo, got {ok}")
        
        # gsc_search_queries
        gsc = metrics.get("gsc_search_queries", {})
        print(f"\ngsc_search_queries: {gsc}")
        if gsc.get("source") == "google_search_console" and gsc.get("connected") == False:
            print("  ✅ gsc_search_queries: source=google_search_console, connected=false")
        else:
            print(f"  ❌ gsc_search_queries: expected source=google_search_console, connected=false, got {gsc}")
        
        # provider_dataset
        pd = data.get("provider_dataset", {})
        print(f"\nprovider_dataset: {pd}")
        if pd.get("status") == "incomplete" and pd.get("next_offset") == 1000:
            print("  ✅ provider_dataset: status=incomplete, next_offset=1000")
        else:
            print(f"  ❌ provider_dataset: expected status=incomplete, next_offset=1000, got {pd}")
    else:
        print(f"❌ Failed: {resp.text}")
    
    # TEST 2: GET /seo/keyword-gap/competitors
    print("\n--- TEST 2: GET /seo/keyword-gap/competitors ---")
    resp = client.get("/marketing-os/search/seo/keyword-gap/competitors", admin_token)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        items = data.get("items", [])
        candidates = data.get("candidates", [])
        print(f"  Items count: {len(items)}")
        print(f"  Candidates count: {len(candidates)}")
        
        # Check for specific competitors
        item_domains = [i.get("competitor_domain") for i in items]
        candidate_domains = [c.get("competitor_domain") for c in candidates]
        print(f"  Item domains: {item_domains}")
        print(f"  Candidate domains: {candidate_domains}")
        
        if "rival-naturopath.com" in item_domains and "desertwellnessclinic.com" in item_domains:
            print("  ✅ Items contain rival-naturopath.com and desertwellnessclinic.com")
            # Check keyword_rows
            for item in items:
                if item.get("competitor_domain") in ["rival-naturopath.com", "desertwellnessclinic.com"]:
                    if item.get("keyword_rows") == 80:
                        print(f"    ✅ {item.get('competitor_domain')}: keyword_rows=80")
                    else:
                        print(f"    ❌ {item.get('competitor_domain')}: expected keyword_rows=80, got {item.get('keyword_rows')}")
        else:
            print(f"  ❌ Expected rival-naturopath.com and desertwellnessclinic.com in items")
        
        if "azivtherapy.com" in candidate_domains:
            print("  ✅ Candidates contain azivtherapy.com")
        else:
            print(f"  ❌ Expected azivtherapy.com in candidates")
    else:
        print(f"❌ Failed: {resp.text}")
    
    # TEST 3: GET /seo/keyword-gap with various parameters
    print("\n--- TEST 3: GET /seo/keyword-gap ---")
    
    # 3a: Basic query
    print("\n3a: competitor_domain=rival-naturopath.com&limit=10")
    resp = client.get("/marketing-os/search/seo/keyword-gap", admin_token, 
                     params={"competitor_domain": "rival-naturopath.com", "limit": 10})
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"  has_snapshot: {data.get('has_snapshot')}")
        print(f"  total: {data.get('total')}")
        print(f"  items count: {len(data.get('items', []))}")
        
        if data.get("has_snapshot") == True:
            print("  ✅ has_snapshot=true")
        else:
            print(f"  ❌ has_snapshot: expected true, got {data.get('has_snapshot')}")
        
        if data.get("total") == 80:
            print("  ✅ total=80")
        else:
            print(f"  ❌ total: expected 80, got {data.get('total')}")
        
        # Check counts
        counts = data.get("counts", {})
        print(f"  counts: {counts}")
        if counts.get("missing") == 40:
            print("  ✅ counts.missing=40")
        else:
            print(f"  ❌ counts.missing: expected 40, got {counts.get('missing')}")
        
        # Check items structure
        items = data.get("items", [])
        if len(items) == 10:
            print("  ✅ 10 items returned")
            first_item = items[0]
            required_keys = ["keyword", "gap_type", "target_rank", "competitor_rank", 
                           "search_volume", "cpc", "intent", "keyword_difficulty"]
            missing_keys = [k for k in required_keys if k not in first_item]
            if not missing_keys:
                print(f"  ✅ Items have all required keys")
            else:
                print(f"  ❌ Items missing keys: {missing_keys}")
        else:
            print(f"  ❌ Expected 10 items, got {len(items)}")
    else:
        print(f"❌ Failed: {resp.text}")
    
    # 3b: gap_type=missing
    print("\n3b: gap_type=missing")
    resp = client.get("/marketing-os/search/seo/keyword-gap", admin_token,
                     params={"competitor_domain": "rival-naturopath.com", "gap_type": "missing"})
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"  total: {data.get('total')}")
        items = data.get("items", [])
        
        if data.get("total") == 40:
            print("  ✅ total=40 for gap_type=missing")
        else:
            print(f"  ❌ total: expected 40, got {data.get('total')}")
        
        # Check all items have target_rank=null
        all_null = all(item.get("target_rank") is None for item in items)
        if all_null:
            print("  ✅ All items have target_rank=null")
        else:
            print(f"  ❌ Some items have non-null target_rank")
    else:
        print(f"❌ Failed: {resp.text}")
    
    # 3c: gap_type=bogus (should return 422)
    print("\n3c: gap_type=bogus (expect 422)")
    resp = client.get("/marketing-os/search/seo/keyword-gap", admin_token,
                     params={"competitor_domain": "rival-naturopath.com", "gap_type": "bogus"})
    print(f"Status: {resp.status_code}")
    if resp.status_code == 422:
        print("  ✅ Returns 422 for invalid gap_type")
    else:
        print(f"  ❌ Expected 422, got {resp.status_code}")
    
    # 3d: search=functional
    print("\n3d: search=functional")
    resp = client.get("/marketing-os/search/seo/keyword-gap", admin_token,
                     params={"competitor_domain": "rival-naturopath.com", "search": "functional"})
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"  total: {data.get('total')}")
        items = data.get("items", [])
        
        if data.get("total") < 80:
            print(f"  ✅ total < 80 (filtered)")
        else:
            print(f"  ❌ total should be < 80, got {data.get('total')}")
        
        # Check all keywords contain 'functional'
        all_match = all("functional" in item.get("keyword", "").lower() for item in items)
        if all_match:
            print("  ✅ All keywords contain 'functional'")
        else:
            print(f"  ❌ Some keywords don't contain 'functional'")
    else:
        print(f"❌ Failed: {resp.text}")
    
    # 3e: sort=cpc&direction=asc
    print("\n3e: sort=cpc&direction=asc")
    resp = client.get("/marketing-os/search/seo/keyword-gap", admin_token,
                     params={"competitor_domain": "rival-naturopath.com", "sort": "cpc", 
                            "direction": "asc", "limit": 10})
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        items = data.get("items", [])
        if len(items) >= 2:
            first_cpc = items[0].get("cpc", 0)
            second_cpc = items[1].get("cpc", 0)
            print(f"  First CPC: {first_cpc}, Second CPC: {second_cpc}")
            if first_cpc <= second_cpc:
                print("  ✅ Sorted by CPC ascending")
            else:
                print(f"  ❌ Not sorted correctly")
    else:
        print(f"❌ Failed: {resp.text}")
    
    # 3f: offset=70&limit=10
    print("\n3f: offset=70&limit=10")
    resp = client.get("/marketing-os/search/seo/keyword-gap", admin_token,
                     params={"competitor_domain": "rival-naturopath.com", "offset": 70, "limit": 10})
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        items = data.get("items", [])
        has_more = data.get("has_more", True)
        print(f"  items count: {len(items)}")
        print(f"  has_more: {has_more}")
        
        if len(items) == 10:
            print("  ✅ 10 items returned")
        else:
            print(f"  ❌ Expected 10 items, got {len(items)}")
        
        if has_more == False:
            print("  ✅ has_more=false")
        else:
            print(f"  ❌ has_more: expected false, got {has_more}")
    else:
        print(f"❌ Failed: {resp.text}")
    
    # 3g: competitor_domain=unknown.com
    print("\n3g: competitor_domain=unknown.com")
    resp = client.get("/marketing-os/search/seo/keyword-gap", admin_token,
                     params={"competitor_domain": "unknown.com"})
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"  has_snapshot: {data.get('has_snapshot')}")
        print(f"  total: {data.get('total')}")
        
        if data.get("has_snapshot") == False and data.get("total") == 0:
            print("  ✅ has_snapshot=false, total=0 for unknown competitor")
        else:
            print(f"  ❌ Expected has_snapshot=false, total=0")
    else:
        print(f"❌ Expected 200, got {resp.status_code}: {resp.text}")
    
    # TEST 4: GET /seo/backlinks/summary
    print("\n--- TEST 4: GET /seo/backlinks/summary ---")
    resp = client.get("/marketing-os/search/seo/backlinks/summary", admin_token)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        summary = data.get("summary", {})
        print(f"  summary: {summary}")
        
        if summary.get("backlinks") == 1842:
            print("  ✅ summary.backlinks=1842")
        else:
            print(f"  ❌ summary.backlinks: expected 1842, got {summary.get('backlinks')}")
        
        if summary.get("referring_domains") == 263:
            print("  ✅ summary.referring_domains=263")
        else:
            print(f"  ❌ summary.referring_domains: expected 263, got {summary.get('referring_domains')}")
        
        # Check dofollow + nofollow consistency
        dofollow = summary.get("dofollow_links", 0)
        nofollow = summary.get("nofollow_links", 0)
        print(f"  dofollow_links: {dofollow}, nofollow_links: {nofollow}")
        
        if nofollow == 402:
            print("  ✅ nofollow_links=402")
        else:
            print(f"  ❌ nofollow_links: expected 402, got {nofollow}")
        
        sampled = summary.get("sampled", {})
        print(f"  sampled: {sampled}")
        
        if sampled.get("new_sampled") == 14:
            print("  ✅ sampled.new_sampled=14")
        else:
            print(f"  ❌ sampled.new_sampled: expected 14, got {sampled.get('new_sampled')}")
        
        if sampled.get("lost_sampled") == 8:
            print("  ✅ sampled.lost_sampled=8")
        else:
            print(f"  ❌ sampled.lost_sampled: expected 8, got {sampled.get('lost_sampled')}")
        
        if sampled.get("sampled_rows") == 120:
            print("  ✅ sampled.sampled_rows=120")
        else:
            print(f"  ❌ sampled.sampled_rows: expected 120, got {sampled.get('sampled_rows')}")
    else:
        print(f"❌ Failed: {resp.text}")
    
    # TEST 5: GET /seo/backlinks with various filters
    print("\n--- TEST 5: GET /seo/backlinks ---")
    
    # 5a: limit=25
    print("\n5a: limit=25")
    resp = client.get("/marketing-os/search/seo/backlinks", admin_token, params={"limit": 25})
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"  total: {data.get('total')}")
        print(f"  has_more: {data.get('has_more')}")
        
        if data.get("total") == 120:
            print("  ✅ total=120")
        else:
            print(f"  ❌ total: expected 120, got {data.get('total')}")
        
        if data.get("has_more") == True:
            print("  ✅ has_more=true")
        else:
            print(f"  ❌ has_more: expected true, got {data.get('has_more')}")
    else:
        print(f"❌ Failed: {resp.text}")
    
    # 5b: status=new
    print("\n5b: status=new")
    resp = client.get("/marketing-os/search/seo/backlinks", admin_token, params={"status": "new"})
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"  total: {data.get('total')}")
        
        if data.get("total") == 14:
            print("  ✅ total=14 for status=new")
        else:
            print(f"  ❌ total: expected 14, got {data.get('total')}")
    else:
        print(f"❌ Failed: {resp.text}")
    
    # 5c: status=lost
    print("\n5c: status=lost")
    resp = client.get("/marketing-os/search/seo/backlinks", admin_token, params={"status": "lost"})
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"  total: {data.get('total')}")
        
        if data.get("total") == 8:
            print("  ✅ total=8 for status=lost")
        else:
            print(f"  ❌ total: expected 8, got {data.get('total')}")
    else:
        print(f"❌ Failed: {resp.text}")
    
    # 5d: dofollow=false
    print("\n5d: dofollow=false")
    resp = client.get("/marketing-os/search/seo/backlinks", admin_token, params={"dofollow": "false"})
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"  total: {data.get('total')}")
        
        if data.get("total") == 24:
            print("  ✅ total=24 for dofollow=false")
        else:
            print(f"  ❌ total: expected 24, got {data.get('total')}")
    else:
        print(f"❌ Failed: {resp.text}")
    
    # 5e: status=bogus (expect 422)
    print("\n5e: status=bogus (expect 422)")
    resp = client.get("/marketing-os/search/seo/backlinks", admin_token, params={"status": "bogus"})
    print(f"Status: {resp.status_code}")
    if resp.status_code == 422:
        print("  ✅ Returns 422 for invalid status")
    else:
        print(f"  ❌ Expected 422, got {resp.status_code}")
    
    # 5f: search=directory
    print("\n5f: search=directory")
    resp = client.get("/marketing-os/search/seo/backlinks", admin_token, params={"search": "directory"})
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        items = data.get("items", [])
        print(f"  items count: {len(items)}")
        
        # Check all source_domain contain 'directory'
        all_match = all("directory" in item.get("source_domain", "").lower() for item in items)
        if all_match and len(items) > 0:
            print("  ✅ All source_domain contain 'directory'")
        elif len(items) == 0:
            print("  ⚠️  No items returned (may be expected if no directory backlinks)")
        else:
            print(f"  ❌ Some source_domain don't contain 'directory'")
    else:
        print(f"❌ Failed: {resp.text}")
    
    # TEST 6: Tracked keywords CRUD
    print("\n--- TEST 6: Tracked keywords ---")
    
    # 6a: GET tracked keywords
    print("\n6a: GET /seo/tracked-keywords")
    resp = client.get("/marketing-os/search/seo/tracked-keywords", admin_token)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        initial_count = data.get("total", 0)
        summary = data.get("summary", {})
        print(f"  total: {initial_count}")
        print(f"  summary: {summary}")
        
        if initial_count == 5:
            print("  ✅ total=5")
        else:
            print(f"  ❌ total: expected 5, got {initial_count}")
        
        if summary.get("tracked") == 5:
            print("  ✅ summary.tracked=5")
        else:
            print(f"  ❌ summary.tracked: expected 5, got {summary.get('tracked')}")
        
        # Check items structure
        items = data.get("items", [])
        if items:
            first_item = items[0]
            required_keys = ["latest_position", "position_change", "observation_count"]
            missing_keys = [k for k in required_keys if k not in first_item]
            if not missing_keys:
                print(f"  ✅ Items have required keys")
                if first_item.get("observation_count") == 3:
                    print(f"  ✅ observation_count=3")
                else:
                    print(f"  ❌ observation_count: expected 3, got {first_item.get('observation_count')}")
            else:
                print(f"  ❌ Items missing keys: {missing_keys}")
    else:
        print(f"❌ Failed: {resp.text}")
    
    # 6b: POST new tracked keyword
    print("\n6b: POST /seo/tracked-keywords")
    new_keyword_data = {
        "keyword": "qa test keyword",
        "device": "mobile"
    }
    resp = client.post("/marketing-os/search/seo/tracked-keywords", admin_token, json_data=new_keyword_data)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 201:
        data = resp.json()
        new_keyword_id = data.get("id")
        normalized_keyword = data.get("normalized_keyword")
        print(f"  ✅ Created keyword with id: {new_keyword_id}")
        print(f"  normalized_keyword: {normalized_keyword}")
        
        if normalized_keyword == "qa test keyword":
            print("  ✅ normalized_keyword='qa test keyword'")
        else:
            print(f"  ❌ normalized_keyword: expected 'qa test keyword', got {normalized_keyword}")
    else:
        print(f"❌ Failed: {resp.text}")
        new_keyword_id = None
    
    # 6c: GET again to verify count increased
    print("\n6c: GET /seo/tracked-keywords (verify count)")
    resp = client.get("/marketing-os/search/seo/tracked-keywords", admin_token)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        new_count = data.get("total", 0)
        print(f"  total: {new_count}")
        
        if new_count == 6:
            print("  ✅ total=6 (increased by 1)")
        else:
            print(f"  ❌ total: expected 6, got {new_count}")
    else:
        print(f"❌ Failed: {resp.text}")
    
    # 6d: POST same keyword again (idempotent)
    print("\n6d: POST same keyword again (idempotent)")
    resp = client.post("/marketing-os/search/seo/tracked-keywords", admin_token, json_data=new_keyword_data)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 201:
        print("  ✅ Returns 201 (idempotent)")
        
        # Verify count stays 6
        resp2 = client.get("/marketing-os/search/seo/tracked-keywords", admin_token)
        if resp2.status_code == 200:
            count = resp2.json().get("total", 0)
            if count == 6:
                print("  ✅ total stays 6 (idempotent)")
            else:
                print(f"  ❌ total: expected 6, got {count}")
    else:
        print(f"❌ Failed: {resp.text}")
    
    # 6e: GET keyword history
    if new_keyword_id:
        print(f"\n6e: GET /seo/tracked-keywords/{new_keyword_id}/history")
        resp = client.get(f"/marketing-os/search/seo/tracked-keywords/{new_keyword_id}/history", admin_token)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            total = data.get("total", 0)
            print(f"  total: {total}")
            
            if total == 0:
                print("  ✅ total=0 (new keyword has no history)")
            else:
                print(f"  ❌ total: expected 0, got {total}")
        else:
            print(f"❌ Failed: {resp.text}")
    
    # 6f: DELETE keyword
    if new_keyword_id:
        print(f"\n6f: DELETE /seo/tracked-keywords/{new_keyword_id}")
        resp = client.delete(f"/marketing-os/search/seo/tracked-keywords/{new_keyword_id}", admin_token)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            is_active = data.get("is_active")
            print(f"  is_active: {is_active}")
            
            if is_active == False:
                print("  ✅ is_active=false")
            else:
                print(f"  ❌ is_active: expected false, got {is_active}")
        else:
            print(f"❌ Failed: {resp.text}")
    
    # 6g: GET again to verify count back to 5
    print("\n6g: GET /seo/tracked-keywords (verify count back to 5)")
    resp = client.get("/marketing-os/search/seo/tracked-keywords", admin_token)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        final_count = data.get("total", 0)
        print(f"  total: {final_count}")
        
        if final_count == 5:
            print("  ✅ total=5 (back to original)")
        else:
            print(f"  ❌ total: expected 5, got {final_count}")
    else:
        print(f"❌ Failed: {resp.text}")
    
    # 6h: POST with invalid device (expect 422)
    print("\n6h: POST with device='tablet' (expect 422)")
    invalid_keyword = {
        "keyword": "test invalid device",
        "device": "tablet"
    }
    resp = client.post("/marketing-os/search/seo/tracked-keywords", admin_token, json_data=invalid_keyword)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 422:
        print("  ✅ Returns 422 for invalid device")
    else:
        print(f"  ❌ Expected 422, got {resp.status_code}")
    
    # TEST 7: GET /seo/schedules
    print("\n--- TEST 7: GET /seo/schedules ---")
    resp = client.get("/marketing-os/search/seo/schedules", admin_token)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"  scheduler_enabled: {data.get('scheduler_enabled')}")
        print(f"  provider_ready: {data.get('provider_ready')}")
        items = data.get("items", [])
        print(f"  items count: {len(items)}")
        
        if data.get("scheduler_enabled") == False:
            print("  ✅ scheduler_enabled=false")
        else:
            print(f"  ❌ scheduler_enabled: expected false, got {data.get('scheduler_enabled')}")
        
        if data.get("provider_ready") == False:
            print("  ✅ provider_ready=false")
        else:
            print(f"  ❌ provider_ready: expected false, got {data.get('provider_ready')}")
        
        if len(items) == 7:
            print("  ✅ 7 items (report types)")
        else:
            print(f"  ❌ items: expected 7, got {len(items)}")
        
        # Check all enabled=false, persisted=false
        all_disabled = all(not item.get("enabled") for item in items)
        all_not_persisted = all(not item.get("persisted") for item in items)
        
        if all_disabled:
            print("  ✅ All items have enabled=false")
        else:
            print(f"  ❌ Some items have enabled=true")
        
        if all_not_persisted:
            print("  ✅ All items have persisted=false")
        else:
            print(f"  ❌ Some items have persisted=true")
    else:
        print(f"❌ Failed: {resp.text}")
    
    # TEST 7b: PUT schedule (admin only)
    print("\n--- TEST 7b: PUT /seo/schedules/ranked_keywords ---")
    schedule_data = {
        "enabled": False,
        "cadence_hours": 168,
        "max_pages": 2,
        "max_requests": 2,
        "max_total_cost": 0.5,
        "retry_ceiling": 2,
        "limit_per_page": 1000
    }
    resp = client.put("/marketing-os/search/seo/schedules/ranked_keywords", admin_token, json_data=schedule_data)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"  ✅ Schedule updated")
        print(f"  persisted: {data.get('persisted')}")
        
        if data.get("persisted") == True:
            print("  ✅ persisted=true")
        else:
            print(f"  ❌ persisted: expected true, got {data.get('persisted')}")
    else:
        print(f"❌ Failed: {resp.text}")
    
    # 7c: PUT with invalid cadence_hours (expect 422)
    print("\n7c: PUT with cadence_hours=1 (expect 422)")
    invalid_schedule = {**schedule_data, "cadence_hours": 1}
    resp = client.put("/marketing-os/search/seo/schedules/ranked_keywords", admin_token, json_data=invalid_schedule)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 422:
        print("  ✅ Returns 422 for invalid cadence_hours")
    else:
        print(f"  ❌ Expected 422, got {resp.status_code}")
    
    # 7d: PUT with practitioner token (expect 403)
    if practitioner_token:
        print("\n7d: PUT with practitioner token (expect 403)")
        resp = client.put("/marketing-os/search/seo/schedules/ranked_keywords", practitioner_token, json_data=schedule_data)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 403:
            print("  ✅ Returns 403 for non-admin")
        else:
            print(f"  ❌ Expected 403, got {resp.status_code}")
    
    # TEST 8: GET /seo/refresh/readiness
    print("\n--- TEST 8: GET /seo/refresh/readiness ---")
    resp = client.get("/marketing-os/search/seo/refresh/readiness", admin_token)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"  status: {data.get('status')}")
        print(f"  scheduler_enabled: {data.get('scheduler_enabled')}")
        print(f"  supported_reports: {data.get('supported_reports')}")
        
        if data.get("status") == "not_connected":
            print("  ✅ status='not_connected'")
        else:
            print(f"  ❌ status: expected 'not_connected', got {data.get('status')}")
        
        if data.get("scheduler_enabled") == False:
            print("  ✅ scheduler_enabled=false")
        else:
            print(f"  ❌ scheduler_enabled: expected false, got {data.get('scheduler_enabled')}")
        
        supported = data.get("supported_reports", [])
        expected_reports = ["keyword_gap", "backlinks", "serp_rank"]
        has_expected = all(r in supported for r in expected_reports)
        
        if has_expected and len(supported) == 7:
            print(f"  ✅ supported_reports has 7 entries including {expected_reports}")
        else:
            print(f"  ❌ supported_reports: {supported}")
    else:
        print(f"❌ Failed: {resp.text}")
    
    # TEST 9: POST /seo/refresh (dry-run and validation)
    print("\n--- TEST 9: POST /seo/refresh ---")
    
    # 9a: Dry-run with ranked_keywords
    print("\n9a: POST /seo/refresh (dry-run, ranked_keywords)")
    refresh_data = {
        "report_type": "ranked_keywords",
        "start_offset": 1000,
        "limit": 1000,
        "max_pages": 1
    }
    resp = client.post("/marketing-os/search/seo/refresh", admin_token, json_data=refresh_data)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"  status: {data.get('status')}")
        print(f"  live: {data.get('live')}")
        plan = data.get("plan", {})
        print(f"  plan.start_offset: {plan.get('start_offset')}")
        print(f"  plan.max_requests: {plan.get('max_requests')}")
        print(f"  plan.provider_ready: {plan.get('provider_ready')}")
        
        if data.get("status") == "dry_run":
            print("  ✅ status='dry_run'")
        else:
            print(f"  ❌ status: expected 'dry_run', got {data.get('status')}")
        
        if data.get("live") == False:
            print("  ✅ live=false")
        else:
            print(f"  ❌ live: expected false, got {data.get('live')}")
        
        if plan.get("start_offset") == 1000:
            print("  ✅ plan.start_offset=1000")
        else:
            print(f"  ❌ plan.start_offset: expected 1000, got {plan.get('start_offset')}")
        
        if plan.get("max_requests") == 1:
            print("  ✅ plan.max_requests=1")
        else:
            print(f"  ❌ plan.max_requests: expected 1, got {plan.get('max_requests')}")
        
        tables = plan.get("tables", [])
        if "marketing_seo_organic_keyword_snapshots" in tables:
            print("  ✅ plan.tables includes marketing_seo_organic_keyword_snapshots")
        else:
            print(f"  ❌ plan.tables: {tables}")
        
        if plan.get("provider_ready") == False:
            print("  ✅ plan.provider_ready=false")
        else:
            print(f"  ❌ plan.provider_ready: expected false, got {plan.get('provider_ready')}")
    else:
        print(f"❌ Failed: {resp.text}")
    
    # 9b: Try live run (expect 409 - provider not ready)
    print("\n9b: POST /seo/refresh (dry_run=false, confirm=true, expect 409)")
    live_refresh = {**refresh_data, "dry_run": False, "confirm": True}
    resp = client.post("/marketing-os/search/seo/refresh", admin_token, json_data=live_refresh)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 409:
        print("  ✅ Returns 409 (provider not ready)")
    else:
        print(f"  ❌ Expected 409, got {resp.status_code}")
    
    # 9c: keyword_gap without options (expect 400)
    print("\n9c: POST /seo/refresh (keyword_gap without options, expect 400)")
    gap_refresh = {
        "report_type": "keyword_gap",
        "start_offset": 0,
        "limit": 1000,
        "max_pages": 1
    }
    resp = client.post("/marketing-os/search/seo/refresh", admin_token, json_data=gap_refresh)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 400:
        print("  ✅ Returns 400 (missing options)")
    else:
        print(f"  ❌ Expected 400, got {resp.status_code}")
    
    # 9d: Invalid report_type (expect 400)
    print("\n9d: POST /seo/refresh (report_type='bogus', expect 400)")
    bogus_refresh = {
        "report_type": "bogus",
        "start_offset": 0,
        "limit": 1000,
        "max_pages": 1
    }
    resp = client.post("/marketing-os/search/seo/refresh", admin_token, json_data=bogus_refresh)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 400:
        print("  ✅ Returns 400 (invalid report_type)")
    else:
        print(f"  ❌ Expected 400, got {resp.status_code}")
    
    # 9e: max_pages=50 (expect 422)
    print("\n9e: POST /seo/refresh (max_pages=50, expect 422)")
    large_refresh = {**refresh_data, "max_pages": 50}
    resp = client.post("/marketing-os/search/seo/refresh", admin_token, json_data=large_refresh)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 422:
        print("  ✅ Returns 422 (max_pages too large)")
    else:
        print(f"  ❌ Expected 422, got {resp.status_code}")
    
    # 9f: Practitioner token (expect 403)
    if practitioner_token:
        print("\n9f: POST /seo/refresh with practitioner token (expect 403)")
        resp = client.post("/marketing-os/search/seo/refresh", practitioner_token, json_data=refresh_data)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 403:
            print("  ✅ Returns 403 (admin only)")
        else:
            print(f"  ❌ Expected 403, got {resp.status_code}")
    
    # 9g: No token (expect 401)
    print("\n9g: POST /seo/refresh without token (expect 401)")
    resp = client.session.post(f"{BASE_URL}/marketing-os/search/seo/refresh", json=refresh_data)
    print(f"Status: {resp.status_code}")
    if resp.status_code in [401, 403]:
        print("  ✅ Returns 401/403 (unauthorized)")
    else:
        print(f"  ❌ Expected 401/403, got {resp.status_code}")
    
    # TEST 10: GET /search-console/runs
    print("\n--- TEST 10: GET /search-console/runs ---")
    resp = client.get("/marketing-os/search/search-console/runs", admin_token)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"  connected: {data.get('connected')}")
        items = data.get("items", [])
        print(f"  items count: {len(items)}")
        
        if data.get("connected") == True:
            print("  ✅ connected=true")
        else:
            print(f"  ❌ connected: expected true, got {data.get('connected')}")
        
        if len(items) == 0:
            print("  ✅ items=[] (no GSC runs in sandbox)")
        else:
            print(f"  ❌ items: expected [], got {len(items)} items")
    else:
        print(f"❌ Failed: {resp.text}")
    
    # TEST 11: GET /seo/provider-runs with filters
    print("\n--- TEST 11: GET /seo/provider-runs ---")
    
    # 11a: report_type=keyword_gap
    print("\n11a: GET /seo/provider-runs?report_type=keyword_gap")
    resp = client.get("/marketing-os/search/seo/provider-runs", admin_token, 
                     params={"report_type": "keyword_gap"})
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        total = data.get("total", 0)
        print(f"  total: {total}")
        
        if total == 4:
            print("  ✅ total=4 for keyword_gap")
        else:
            print(f"  ❌ total: expected 4, got {total}")
    else:
        print(f"❌ Failed: {resp.text}")
    
    # 11b: report_type=serp_rank
    print("\n11b: GET /seo/provider-runs?report_type=serp_rank")
    resp = client.get("/marketing-os/search/seo/provider-runs", admin_token,
                     params={"report_type": "serp_rank"})
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        total = data.get("total", 0)
        print(f"  total: {total}")
        
        if total == 15:
            print("  ✅ total=15 for serp_rank")
        else:
            print(f"  ❌ total: expected 15, got {total}")
    else:
        print(f"❌ Failed: {resp.text}")
    
    # 11c: report_type=backlinks
    print("\n11c: GET /seo/provider-runs?report_type=backlinks")
    resp = client.get("/marketing-os/search/seo/provider-runs", admin_token,
                     params={"report_type": "backlinks"})
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        total = data.get("total", 0)
        items = data.get("items", [])
        print(f"  total: {total}")
        
        if total == 1:
            print("  ✅ total=1 for backlinks")
        else:
            print(f"  ❌ total: expected 1, got {total}")
        
        if items:
            first_item = items[0]
            print(f"  complete: {first_item.get('complete')}")
            print(f"  next_offset: {first_item.get('next_offset')}")
            print(f"  provider_total_count: {first_item.get('provider_total_count')}")
            
            if first_item.get("complete") == False:
                print("  ✅ complete=false")
            else:
                print(f"  ❌ complete: expected false, got {first_item.get('complete')}")
            
            if first_item.get("next_offset") == 120:
                print("  ✅ next_offset=120")
            else:
                print(f"  ❌ next_offset: expected 120, got {first_item.get('next_offset')}")
            
            if first_item.get("provider_total_count") == 1842:
                print("  ✅ provider_total_count=1842")
            else:
                print(f"  ❌ provider_total_count: expected 1842, got {first_item.get('provider_total_count')}")
    else:
        print(f"❌ Failed: {resp.text}")
    
    # TEST 12: Final provider-runs count (must remain 24)
    print("\n--- TEST 12: FINAL PROVIDER-RUNS COUNT ---")
    resp = client.get("/marketing-os/search/seo/provider-runs", admin_token)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        final_total = resp.json().get("total", 0)
        print(f"  Final total: {final_total}")
        print(f"  Initial total: {initial_total}")
        
        if final_total == 24 and initial_total == 24:
            print("  ✅ Provider-runs total remains 24 (no provider calls happened)")
        else:
            print(f"  ❌ Provider-runs total changed: {initial_total} -> {final_total}")
    else:
        print(f"❌ Failed: {resp.text}")
    
    print("\n" + "="*80)
    print("TESTING COMPLETE")
    print("="*80)


if __name__ == "__main__":
    test_seo_phase2()
