"""Marketing OS capability registry.

This registry describes the current implementation state of each
Marketing OS subsystem.

A capability being ready does NOT imply permission to perform external
writes. External advertising, publishing, campaign creation, and budget
mutation remain governed by marketing_os.policy.DEFAULT_POLICY.
"""

CAPABILITIES = {
    "concierge": {
        "status": "foundation_ready",
        "write_enabled": False,
        "public_enabled": False,
    },

    "marketing_director": {
        "status": "ready",
        "mode": "advisory",
        "recommendations_persisted": True,
        "write_enabled": False,
    },

    "goals": {
        "status": "ready",
        "internal_write_enabled": True,
        "external_write_enabled": False,
    },

    "budgets": {
        "status": "ready",
        "internal_write_enabled": True,
        "automatic_budget_changes": False,
        "external_write_enabled": False,
    },

    "analytics": {
        "status": "foundation_ready",
        "daily_metrics_enabled": True,
        "fractional_conversions_enabled": True,
        "external_write_enabled": False,
    },

    "attribution": {
        "status": "ready",
        "model": "last_touch",
        "non_phi_required": True,
        "external_write_enabled": False,
    },

    "recommendations": {
        "status": "ready",
        "persistent": True,
        "human_approval_required": True,
        "external_write_enabled": False,
    },

    "approvals": {
        "status": "ready",
        "decisions": [
            "approved",
            "rejected",
        ],
        "approved_action_status": "blocked",
        "approved_action_dry_run": True,
        "external_write_enabled": False,
    },

    "action_ledger": {
        "status": "ready",
        "execution_enabled": False,
        "default_status": "blocked",
        "dry_run": True,
        "external_write_enabled": False,
    },

    "seo": {
        "status": "planned",
        "write_enabled": False,
    },

    "search_intelligence": {
        "status": "foundation_ready",
        "mode": "read_only",
        "overview_enabled": True,
        "keyword_tracking_enabled": True,
        "site_audit_enabled": True,
        "site_audit_read_only": True,
        "recommendations_mode": "advisory",
        "external_write_enabled": False,
        "write_enabled": False,
        "phi_stored": False,
        "connected_providers": {
            "rank_provider": False,
            "search_console": False,
            "backlink_provider": False,
        },
    },

    "google_search_console": {
        "status": "read_integration_ready",
        "mode": "read_only",
        "scope": "https://www.googleapis.com/auth/webmasters.readonly",
        "performance_sync_enabled": True,
        "rank_tracking_enabled": True,
        "recommendations_mode": "advisory",
        "external_write_enabled": False,
        "write_enabled": False,
        "phi_stored": False,
        "position_is_serp_rank": False,
    },

    "backlinks": {
        "status": "planned",
        "write_enabled": False,
    },

    "competitors": {
        "status": "planned",
        "write_enabled": False,
    },

    "google_ads": {
        "status": "read_integration_ready",
        "account_registration_enabled": True,
        "performance_sync_enabled": True,
        "write_enabled": False,
    },

    "meta_ads": {
        "status": "not_connected",
        "write_enabled": False,
    },

    "tiktok_ads": {
        "status": "not_connected",
        "write_enabled": False,
    },
}
