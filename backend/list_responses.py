"""Shared list-response contracts.

New paginated endpoints should return:
{
    "items": [...],
    "total": 0,
    "limit": 100,
    "offset": 0,
    "has_more": false
}

The frontend maintains backward compatibility with legacy array responses
through api.getList() and normalizeApiList().
"""
from __future__ import annotations

from typing import Generic, List, TypeVar

from pydantic import BaseModel, Field


T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    items: List[T] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1)
    offset: int = Field(default=0, ge=0)
    has_more: bool = False


def paginated_payload(
    items: list,
    *,
    total: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """Build the standard frontend-safe pagination envelope."""
    safe_items = list(items or [])
    safe_total = len(safe_items) if total is None else max(0, int(total))
    safe_limit = max(1, int(limit))
    safe_offset = max(0, int(offset))

    return {
        "items": safe_items,
        "total": safe_total,
        "limit": safe_limit,
        "offset": safe_offset,
        "has_more": safe_offset + len(safe_items) < safe_total,
    }
