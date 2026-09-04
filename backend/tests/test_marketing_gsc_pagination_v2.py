from marketing_os.search.gsc_sync import (
    MAX_PROVIDER_PAGES,
    _fetch_all_search_analytics,
)


class FakePagedGSC:
    def __init__(self, total_rows):
        self.total_rows = total_rows
        self.calls = []

    def fetch_search_analytics(
        self,
        *,
        start_date,
        end_date,
        dimensions,
        row_limit=1000,
        start_row=0,
        data_state="final",
    ):
        self.calls.append(
            {
                "start_date": start_date,
                "end_date": end_date,
                "dimensions": list(dimensions),
                "row_limit": row_limit,
                "start_row": start_row,
                "data_state": data_state,
            }
        )

        remaining = max(
            0,
            self.total_rows - start_row,
        )
        count = min(row_limit, remaining)

        key = dimensions[0]

        rows = []

        for i in range(count):
            absolute = start_row + i

            value = (
                f"keyword {absolute}"
                if key == "query"
                else f"value-{absolute}"
            )

            rows.append(
                {
                    "keys": [value],
                    "clicks": 1,
                    "impressions": 10,
                    "ctr": 0.1,
                    "position": 5.0,
                }
            )

        return {"rows": rows}


def test_gsc_pagination_fetches_more_than_first_1000_rows():
    adapter = FakePagedGSC(total_rows=3315)

    rows, metadata = _fetch_all_search_analytics(
        adapter,
        start_date="2026-08-05",
        end_date="2026-09-02",
        dimensions=["query"],
        row_limit=1000,
    )

    assert len(rows) == 3315
    assert metadata["rows"] == 3315
    assert metadata["pages"] == 4
    assert metadata["complete"] is True
    assert metadata["next_start_row"] is None

    assert [
        call["start_row"]
        for call in adapter.calls
    ] == [0, 1000, 2000, 3000]


def test_gsc_pagination_exact_full_page_confirms_exhaustion():
    adapter = FakePagedGSC(total_rows=2000)

    rows, metadata = _fetch_all_search_analytics(
        adapter,
        start_date="2026-08-01",
        end_date="2026-09-01",
        dimensions=["query"],
        row_limit=1000,
    )

    assert len(rows) == 2000

    # A third zero-row request is required to prove that a result
    # ending exactly on a page boundary is complete.
    assert [
        call["start_row"]
        for call in adapter.calls
    ] == [0, 1000, 2000]

    assert metadata["pages"] == 3
    assert metadata["complete"] is True


def test_gsc_pagination_marks_safety_ceiling_incomplete():
    adapter = FakePagedGSC(
        total_rows=MAX_PROVIDER_PAGES + 100
    )

    rows, metadata = _fetch_all_search_analytics(
        adapter,
        start_date="2026-08-01",
        end_date="2026-09-01",
        dimensions=["query"],
        row_limit=1,
    )

    assert len(rows) == MAX_PROVIDER_PAGES
    assert metadata["pages"] == MAX_PROVIDER_PAGES
    assert metadata["complete"] is False
    assert metadata["next_start_row"] == MAX_PROVIDER_PAGES
