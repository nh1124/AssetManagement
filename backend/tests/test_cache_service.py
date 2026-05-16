from __future__ import annotations

from backend.app.services.cache_service import get_or_set, invalidate_client


def test_cache_returns_copy_and_invalidates_by_client() -> None:
    invalidate_client()
    calls = []

    first = get_or_set(
        "client:1:analysis_summary",
        60,
        lambda: calls.append("called") or {"items": []},
    )
    first["items"].append("mutated")
    second = get_or_set(
        "client:1:analysis_summary",
        60,
        lambda: calls.append("called") or {"items": []},
    )

    assert calls == ["called"]
    assert second == {"items": []}

    invalidate_client(1)
    third = get_or_set(
        "client:1:analysis_summary",
        60,
        lambda: calls.append("called") or {"items": ["fresh"]},
    )

    assert calls == ["called", "called"]
    assert third == {"items": ["fresh"]}
