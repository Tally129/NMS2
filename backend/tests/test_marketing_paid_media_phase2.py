"""Meta Ads + Microsoft Ads adapters, governed mutations, cross-channel sync.
Pure tests with injected fake transports — no network, no PostgreSQL."""

from __future__ import annotations

import asyncio

import pytest

from marketing_os.integrations import meta_ads as meta
from marketing_os.integrations import microsoft_ads as ms
from marketing_os.services import paid_sync


def run(c):
    return asyncio.run(c)


# ------------------------------------------------------------------ Meta


class MetaHttp:
    def __init__(self):
        self.calls = []
        self.state = {"123": {"id": "123", "name": "Lead Gen", "status": "ACTIVE", "effective_status": "ACTIVE", "daily_budget": "5000"}}

    def __call__(self, method, path, params=None, data=None):
        self.calls.append((method, path, dict(params or {}), dict(data or {})))
        if path.endswith("/campaigns"):
            return {"data": [{"id": "123", "name": "Lead Gen", "effective_status": "ACTIVE", "objective": "OUTCOME_LEADS", "daily_budget": "5000"}], "paging": {}}
        if path.endswith("/insights"):
            if params.get("after"):
                return {"data": [{"campaign_id": "123", "campaign_name": "Lead Gen", "objective": "OUTCOME_LEADS", "spend": "20.00", "impressions": "1000",
                                  "reach": "800", "frequency": "1.25", "clicks": "40", "inline_link_clicks": "30", "ctr": "4.0", "cpc": "0.5", "cpm": "20",
                                  "actions": [{"action_type": "lead", "value": "4"}, {"action_type": "link_click", "value": "30"}],
                                  "date_start": "2026-09-02", "date_stop": "2026-09-02"}], "paging": {}}
            return {"data": [{"campaign_id": "123", "campaign_name": "Lead Gen", "objective": "OUTCOME_LEADS", "spend": "10.50", "impressions": "500",
                              "clicks": "20", "ctr": "4.0", "actions": [{"action_type": "lead", "value": "2"}], "action_values": [{"action_type": "purchase", "value": "0"}],
                              "date_start": "2026-09-01", "date_stop": "2026-09-01"}],
                    "paging": {"cursors": {"after": "c2"}, "next": "https://graph.facebook.com/next"}}
        if method == "GET":
            return dict(self.state[path])
        if method == "POST":
            self.state[path].update({k: v for k, v in data.items()}); self.state[path]["effective_status"] = self.state[path].get("status")
            return {"success": True}
        raise AssertionError(path)


def test_meta_performance_paginates_and_normalizes_without_fabricating():
    http = MetaHttp()
    adapter = meta.MetaAdsIntegration(account={"external_account_id": "999"}, http=http)
    out = run(adapter.fetch_performance(start_date="2026-09-01", end_date="2026-09-02"))
    assert out["provider"] == "meta_ads" and out["account_id"] == "act_999" and len(out["rows"]) == 2
    r0, r1 = out["rows"]
    assert r0["campaign_id"] == "123" and r0["conversions"] == 2 and r0["leads"] == 2 and r0["status"] == "ACTIVE"
    assert r0["daily_budget"] == 50.0  # minor units -> account currency
    assert r1["raw"]["reach"] == "800" and r1["raw"]["frequency"] == "1.25" and r1["conversions"] == 4
    assert r1["campaign_type"] == "meta_outcome_leads" and r1["metric_date"] == "2026-09-02"
    assert r0.get("roas") in (None, 0.0)  # derived from reported purchase value 0; provider purchase_roas absent
    insight_calls = [c for c in http.calls if c[1].endswith("/insights")]
    assert len(insight_calls) == 2 and insight_calls[1][2]["after"] == "c2"


def test_meta_governed_pause_dry_run_then_live_with_readback():
    http = MetaHttp()
    adapter = meta.MetaAdsIntegration(account={"external_account_id": "999"}, http=http)
    dry = run(adapter.execute_action(action="campaign.pause", resource_id="123", dry_run=True))
    assert dry["dry_run"] is True and dry["external_write"] is False and dry["would_send"] == {"status": "PAUSED"}
    assert not [c for c in http.calls if c[0] == "POST"]
    live = run(adapter.execute_action(action="campaign.pause", resource_id="123"))
    assert live["external_write"] is True and live["after"]["status"] == "PAUSED" and live["readback_verified"] is True
    budget = run(adapter.execute_action(action="campaign.budget_update", resource_id="123", params={"daily_budget": "75.5"}))
    assert budget["sent"] == {"daily_budget": "7550"} and budget["readback_verified"] is True
    with pytest.raises(meta.MetaAdsError):
        run(adapter.execute_action(action="campaign.delete", resource_id="123"))
    with pytest.raises(meta.MetaAdsError):
        run(adapter.execute_action(action="adset.budget_update", resource_id="123", params={"daily_budget": "0"}))


def test_meta_provider_error_surfaces(monkeypatch):
    def boom(method, path, params=None, data=None):
        raise meta.MetaAdsError("meta_ads 400: (#100) Invalid parameter (code 100)")
    adapter = meta.MetaAdsIntegration(account={"external_account_id": "1"}, http=boom)
    with pytest.raises(meta.MetaAdsError):
        run(adapter.fetch_campaigns())
    monkeypatch.delenv(meta.ACCESS_TOKEN_ENV, raising=False)
    assert meta.credential_readiness()["connected"] is False


# ------------------------------------------------------------- Microsoft


CSV = "TimePeriod,CampaignId,CampaignName,CampaignStatus,CampaignType,Impressions,Clicks,Ctr,AverageCpc,Spend,Conversions,ConversionRate,CostPerConversion,Revenue,ReturnOnAdSpend\n" \
      "2026-09-01,555,Bing Search,Active,Search,1000,50,5.00%,1.20,60.00,3,6.00%,20.00,300.00,5.00\n" \
      "2026-09-02,555,Bing Search,Active,Search,900,45,5.00%,1.00,45.00,0,0.00%,0.00,0.00,0.00\n"


class MsHttp:
    def __init__(self):
        self.calls = []; self.polls = 0; self.status = "Active"; self.budget = 40.0

    def __call__(self, method, url, headers=None, json=None, data=None):
        self.calls.append((method, url, json))
        if url == ms.TOKEN_URL:
            return 200, {"access_token": "tok"}
        if url.endswith("GenerateReport/Submit"):
            return 200, {"ReportRequestId": "R1"}
        if url.endswith("GenerateReport/Poll"):
            self.polls += 1
            return 200, {"ReportRequestStatus": {"Status": "Pending" if self.polls < 2 else "Success", "ReportDownloadUrl": "https://dl/report.csv"}}
        if url == "https://dl/report.csv":
            return 200, CSV
        if url.endswith("Campaigns/QueryByIds"):
            return 200, {"Campaigns": [{"Id": 555, "Name": "Bing Search", "Status": self.status, "DailyBudget": self.budget}]}
        if url.endswith("/Campaigns"):
            upd = json["Campaigns"][0]
            self.status = upd.get("Status", self.status); self.budget = upd.get("DailyBudget", self.budget)
            return 200, {"PartialErrors": []}
        raise AssertionError(url)


def test_microsoft_report_flow_submit_poll_download_normalize():
    http = MsHttp()
    adapter = ms.MicrosoftAdsIntegration(account={"external_account_id": "777"}, http=http, sleep=lambda s: None)
    out = run(adapter.fetch_performance(start_date="2026-09-01", end_date="2026-09-02"))
    assert out["report_request_id"] == "R1" and len(out["rows"]) == 2 and http.polls == 2
    r = out["rows"][0]
    assert r["provider"] == "microsoft_ads" and r["campaign_id"] == "555" and r["spend"] == 60.0 and r["conversions"] == 3
    assert r["ctr"] == pytest.approx(0.05) and r["roas"] == 5.0 and r["raw"]["ConversionRate"] == "6.00%"
    assert out["rows"][1]["conversions"] == 0
    submit = [c for c in http.calls if c[1].endswith("Submit")][0][2]["ReportRequest"]
    assert submit["Aggregation"] == "Daily" and submit["Time"]["CustomDateRangeStart"] == {"Year": 2026, "Month": 9, "Day": 1}


def test_microsoft_governed_mutations_with_readback():
    http = MsHttp()
    adapter = ms.MicrosoftAdsIntegration(account={"external_account_id": "777"}, http=http, sleep=lambda s: None)
    dry = run(adapter.execute_action(action="campaign.pause", resource_id="555", dry_run=True))
    assert dry["would_send"] == {"Id": 555, "Status": "Paused"} and dry["external_write"] is False
    live = run(adapter.execute_action(action="campaign.pause", resource_id="555"))
    assert live["after"]["Status"] == "Paused" and live["readback_verified"] is True
    b = run(adapter.execute_action(action="campaign.budget_update", resource_id="555", params={"daily_budget": 55}))
    assert b["sent"]["DailyBudget"] == 55.0 and b["readback_verified"] is True
    with pytest.raises(ms.MicrosoftAdsError):
        run(adapter.execute_action(action="keyword.pause", resource_id="1"))


def test_microsoft_errors_and_readiness(monkeypatch):
    def bad(method, url, headers=None, json=None, data=None):
        return (401, {"error": "invalid_grant"}) if url == ms.TOKEN_URL else (500, "boom")
    adapter = ms.MicrosoftAdsIntegration(account={"external_account_id": "777"}, http=bad)
    with pytest.raises(ms.MicrosoftAdsError):
        run(adapter.fetch_campaigns())
    for name in (ms.DEV_TOKEN_ENV, ms.CLIENT_ID_ENV):
        monkeypatch.delenv(name, raising=False)
    assert ms.credential_readiness()["connected"] is False


# ------------------------------------------------------- cross-channel sync


class _Res:
    def __init__(self, row=None, scalar=None):
        self._row, self._scalar = row, scalar
    def mappings(self): return self
    def first(self): return self._row
    def scalar(self): return self._scalar


class FakePg:
    def __init__(self):
        self.calls = []; self.committed = 0; self.rolled = 0
    async def execute(self, stmt, params=None):
        sql = str(stmt); self.calls.append((sql, dict(params or {})))
        if "FROM marketing_channel_accounts" in sql:
            return _Res(row={"id": "acct-1", "provider": "meta_ads", "external_account_id": "999", "account_name": "NMS", "status": "active",
                             "currency": "USD", "timezone": "UTC", "read_enabled": True, "write_enabled": False, "last_sync_at": None, "configuration": {}})
        return _Res()
    async def commit(self): self.committed += 1
    async def rollback(self): self.rolled += 1


def test_sync_persists_normalized_rows_and_keeps_provider_metrics_in_raw(monkeypatch):
    stored = []
    async def fake_persist(pg, payload):
        stored.append(dict(payload)); return payload
    monkeypatch.setattr(paid_sync, "persist_daily_performance", fake_persist)
    adapter = meta.MetaAdsIntegration(account={"external_account_id": "999"}, http=MetaHttp())
    pg = FakePg()
    plan = paid_sync.plan_sync(provider="meta_ads", start_date="2026-09-01", end_date="2026-09-02")
    out = run(paid_sync.sync_provider_performance(pg, plan=plan, adapter=adapter, actor={"id": "u1"}))
    assert out["status"] == "completed", out["error"]
    assert out["rows_received"] == 2 == out["rows_stored"] and pg.committed == 1
    assert stored[0]["provider"] == "meta_ads" and stored[0]["external_campaign_id"] == "123" and stored[0]["channel_account_id"] == "acct-1"
    assert stored[1]["raw_metrics"]["raw"]["reach"] == "800" and stored[0]["conversions"] == 2
    assert any("UPDATE marketing_channel_accounts SET last_sync_at" in c[0] for c in pg.calls)


def test_sync_provider_failure_rolls_back_and_reports():
    class Boom:
        async def fetch_performance(self, **kw): raise meta.MetaAdsError("meta_ads 190: token expired (code 190)")
    pg = FakePg()
    plan = paid_sync.plan_sync(provider="meta_ads", start_date="2026-09-01", end_date="2026-09-02")
    out = run(paid_sync.sync_provider_performance(pg, plan=plan, adapter=Boom()))
    assert out["status"] == "error" and "token expired" in out["error"] and pg.rolled == 1 and pg.committed == 0


def test_plan_sync_validates_range_and_provider():
    with pytest.raises(ValueError):
        paid_sync.plan_sync(provider="tiktok", start_date="2026-09-01", end_date="2026-09-02")
    with pytest.raises(ValueError):
        paid_sync.plan_sync(provider="google_ads", start_date="2026-01-01", end_date="2026-09-02")  # > 93 days
    with pytest.raises(ValueError):
        paid_sync.plan_sync(provider="google_ads", start_date="2026-09-02", end_date="2026-09-01")
    plan = paid_sync.plan_sync(provider="microsoft_ads", start_date="2026-09-01", end_date="2026-09-02")
    assert plan["days"] == 2 and plan["external_write"] is False and plan["provider_ready"] is False


def test_scheduler_tick_noop_when_disabled(monkeypatch):
    monkeypatch.setenv(paid_sync.SYNC_ENABLED_ENV, "false")
    out = run(paid_sync.run_due_paid_syncs(session_factory=lambda: (_ for _ in ()).throw(AssertionError("no db"))))
    assert out["enabled"] is False and out["ran"] == []
