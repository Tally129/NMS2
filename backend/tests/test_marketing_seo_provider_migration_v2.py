"""Static/structural tests for SEO Intelligence V2 migration.

These tests do NOT connect to PostgreSQL.
They do NOT run Alembic against any database.
They replace the Alembic operations proxy with an in-memory recorder.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "2026_09_05_0330-f5a7b9c1d3e5_add_seo_provider_intelligence_v2.py"
)


class FakeOp:
    def __init__(self):
        self.created_tables = {}
        self.created_indexes = []
        self.dropped_tables = []

    def create_table(self, name, *elements, **kwargs):
        self.created_tables[name] = list(elements)

    def create_index(self, name, table_name, columns, **kwargs):
        self.created_indexes.append(
            {
                "name": name,
                "table": table_name,
                "columns": list(columns),
                "kwargs": kwargs,
            }
        )

    def drop_table(self, name, **kwargs):
        self.dropped_tables.append(name)


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "seo_provider_migration_v2",
        MIGRATION,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def run_upgrade():
    module = load_migration()
    fake = FakeOp()
    module.op = fake
    module.upgrade()
    return module, fake


def get_columns(elements):
    return {
        element.name: element
        for element in elements
        if isinstance(element, sa.Column)
    }


def get_unique_constraints(elements):
    return [
        element
        for element in elements
        if isinstance(element, sa.UniqueConstraint)
    ]


def get_check_constraints(elements):
    return [
        element
        for element in elements
        if isinstance(element, sa.CheckConstraint)
    ]


def unique_column_names(constraint):
    """Return UniqueConstraint column names before or after Table binding."""

    resolved = tuple(
        column.name
        for column in constraint.columns
    )

    if resolved:
        return resolved

    pending = getattr(
        constraint,
        "_pending_colargs",
        (),
    )

    names = []

    for value in pending:
        if isinstance(value, str):
            names.append(value)
        else:
            names.append(value.name)

    return tuple(names)


def test_revision_contract():
    module = load_migration()

    assert module.revision == "f5a7b9c1d3e5"
    assert module.down_revision == "e4f6a8c0d2b4"
    assert module.branch_labels is None
    assert module.depends_on is None


def test_upgrade_creates_exact_four_tables():
    _, fake = run_upgrade()

    assert set(fake.created_tables) == {
        "marketing_seo_provider_runs",
        "marketing_seo_domain_snapshots",
        "marketing_seo_organic_keyword_snapshots",
        "marketing_seo_competitor_snapshots",
    }


def test_provider_run_ledger_has_cost_and_completeness_fields():
    _, fake = run_upgrade()

    columns = get_columns(
        fake.created_tables["marketing_seo_provider_runs"]
    )

    required = {
        "id",
        "site_id",
        "provider",
        "report_type",
        "status",
        "target",
        "location",
        "language",
        "device",
        "requested_limit",
        "requested_offset",
        "provider_total_count",
        "provider_items_count",
        "rows_normalized",
        "provider_cost",
        "provider_task_cost",
        "complete",
        "next_offset",
        "provider_status_code",
        "provider_task_status_code",
        "error",
        "started_at",
        "finished_at",
        "created_at",
        "updated_at",
    }

    assert required.issubset(columns)


def test_provider_run_schema_contains_no_credentials():
    _, fake = run_upgrade()

    columns = get_columns(
        fake.created_tables["marketing_seo_provider_runs"]
    )

    forbidden_fragments = {
        "password",
        "secret",
        "token",
        "credential",
        "login",
        "authorization",
        "api_key",
        "apikey",
    }

    for name in columns:
        lowered = name.lower()

        assert not any(
            fragment in lowered
            for fragment in forbidden_fragments
        ), name


def test_all_provider_tables_reference_marketing_site():
    _, fake = run_upgrade()

    for table_name, elements in fake.created_tables.items():
        columns = get_columns(elements)

        assert "site_id" in columns, table_name

        foreign_keys = list(columns["site_id"].foreign_keys)

        assert len(foreign_keys) == 1
        assert (
            foreign_keys[0].target_fullname
            == "marketing_search_sites.id"
        )
        assert foreign_keys[0].ondelete == "CASCADE"


def test_snapshot_provider_run_fks_are_nullable_set_null():
    _, fake = run_upgrade()

    for table_name in (
        "marketing_seo_domain_snapshots",
        "marketing_seo_organic_keyword_snapshots",
        "marketing_seo_competitor_snapshots",
    ):
        columns = get_columns(fake.created_tables[table_name])

        provider_run = columns["provider_run_id"]

        assert provider_run.nullable is True

        foreign_keys = list(provider_run.foreign_keys)

        assert len(foreign_keys) == 1
        assert (
            foreign_keys[0].target_fullname
            == "marketing_seo_provider_runs.id"
        )
        assert foreign_keys[0].ondelete == "SET NULL"


def test_domain_snapshot_unique_scope_preserves_market_dimensions():
    _, fake = run_upgrade()

    elements = fake.created_tables[
        "marketing_seo_domain_snapshots"
    ]

    constraints = get_unique_constraints(elements)

    matching = [
        constraint
        for constraint in constraints
        if constraint.name
        == "uq_marketing_seo_domain_snapshot_scope"
    ]

    assert len(matching) == 1

    assert unique_column_names(matching[0]) == (
        "site_id",
        "captured_date",
        "provider",
        "location",
        "language",
        "device",
    )


def test_organic_keyword_snapshot_is_separate_provider_universe():
    _, fake = run_upgrade()

    elements = fake.created_tables[
        "marketing_seo_organic_keyword_snapshots"
    ]

    columns = get_columns(elements)

    assert {
        "keyword",
        "normalized_keyword",
        "intent",
        "search_volume",
        "keyword_difficulty",
        "cpc",
        "current_rank",
        "ranking_url",
        "serp_features",
        "location",
        "language",
        "device",
        "provider",
        "captured_date",
    }.issubset(columns)

    constraints = get_unique_constraints(elements)

    matching = [
        constraint
        for constraint in constraints
        if constraint.name
        == "uq_marketing_seo_organic_keyword_snapshot_scope"
    ]

    assert len(matching) == 1

    assert unique_column_names(matching[0]) == (
        "site_id",
        "normalized_keyword",
        "location",
        "language",
        "device",
        "captured_date",
        "provider",
    )


def test_competitor_snapshot_scope_preserves_market_dimensions():
    _, fake = run_upgrade()

    elements = fake.created_tables[
        "marketing_seo_competitor_snapshots"
    ]

    constraints = get_unique_constraints(elements)

    matching = [
        constraint
        for constraint in constraints
        if constraint.name
        == "uq_marketing_seo_competitor_snapshot_scope"
    ]

    assert len(matching) == 1

    assert unique_column_names(matching[0]) == (
        "site_id",
        "normalized_domain",
        "captured_date",
        "provider",
        "location",
        "language",
        "device",
    )


def test_keyword_difficulty_constraint_exists():
    _, fake = run_upgrade()

    elements = fake.created_tables[
        "marketing_seo_organic_keyword_snapshots"
    ]

    constraints = {
        constraint.name
        for constraint in get_check_constraints(elements)
    }

    assert "ck_marketing_seo_keyword_difficulty" in constraints
    assert "ck_marketing_seo_keyword_rank_positive" in constraints
    assert "ck_marketing_seo_keyword_volume_nonnegative" in constraints
    assert "ck_marketing_seo_keyword_cpc_nonnegative" in constraints


def test_expected_indexes_are_created():
    _, fake = run_upgrade()

    names = {
        item["name"]
        for item in fake.created_indexes
    }

    expected = {
        "ix_marketing_seo_provider_runs_site_id",
        "ix_marketing_seo_provider_runs_provider",
        "ix_marketing_seo_provider_runs_report_type",
        "ix_marketing_seo_provider_runs_status",
        "ix_marketing_seo_provider_runs_finished_at",
        "ix_marketing_seo_domain_snapshots_site_id",
        "ix_marketing_seo_domain_snapshots_captured_date",
        "ix_marketing_seo_domain_snapshots_provider",
        "ix_marketing_seo_organic_keywords_site_id",
        "ix_marketing_seo_organic_keywords_normalized_keyword",
        "ix_marketing_seo_organic_keywords_captured_date",
        "ix_marketing_seo_organic_keywords_current_rank",
        "ix_marketing_seo_organic_keywords_provider",
        "ix_marketing_seo_competitor_snapshots_site_id",
        "ix_marketing_seo_competitor_snapshots_domain",
        "ix_marketing_seo_competitor_snapshots_captured_date",
        "ix_marketing_seo_competitor_snapshots_provider",
    }

    assert expected.issubset(names)


def test_migration_does_not_modify_existing_search_or_gsc_tables():
    text = MIGRATION.read_text()

    forbidden_operations = (
        'op.alter_column("marketing_search_keywords"',
        'op.drop_table("marketing_search_keywords"',
        'op.alter_column("marketing_search_competitors"',
        'op.drop_table("marketing_search_competitors"',
        'op.alter_column("marketing_gsc_',
        'op.drop_table("marketing_gsc_',
    )

    for operation in forbidden_operations:
        assert operation not in text


def test_downgrade_drops_children_before_provider_run_parent():
    module = load_migration()
    fake = FakeOp()
    module.op = fake

    module.downgrade()

    assert fake.dropped_tables == [
        "marketing_seo_competitor_snapshots",
        "marketing_seo_organic_keyword_snapshots",
        "marketing_seo_domain_snapshots",
        "marketing_seo_provider_runs",
    ]
