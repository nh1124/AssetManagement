from __future__ import annotations

import asyncio
from datetime import date

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models, schemas
from backend.app.database import Base
from backend.app.routers import period_reviews
from backend.app.services import period_review_service


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    session.add(models.Client(id=1, name="test", ai_config={}, general_settings={}))
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_upsert_review_creates_then_updates_one_row_for_the_same_range(db):
    start, end = date(2026, 10, 1), date(2026, 10, 31)
    assert period_review_service.get_review(db, 1, start, end) is None
    created = period_review_service.upsert_review(
        db, 1, schemas.PeriodReviewCreate(
            start_date=start, end_date=end, reflection="First reflection", next_actions="First actions",
        ),
    )
    review_id = created.id
    assert created.label == "2026-10"
    assert db.query(models.PeriodReview).count() == 1

    updated = period_review_service.upsert_review(
        db, 1, schemas.PeriodReviewCreate(
            start_date=start, end_date=end, label="October review",
            reflection="Revised reflection", next_actions="Revised actions",
        ),
    )
    db.expire_all()
    saved = period_review_service.get_review(db, 1, start, end)
    assert updated.id == review_id == saved.id
    assert db.query(models.PeriodReview).count() == 1
    assert (saved.label, saved.reflection, saved.next_actions) == (
        "October review", "Revised reflection", "Revised actions",
    )
    assert (saved.client_id, saved.start_date, saved.end_date) == (1, start, end)
    assert period_review_service.get_review(db, 2, start, end) is None
    assert period_review_service.get_review(db, 1, start, date(2026, 10, 30)) is None


def test_period_label_names_months_and_ranges_and_explicit_labels_win():
    cases = [
        (date(2026, 10, 1), date(2026, 10, 31), "2026-10"),
        (date(2026, 10, 2), date(2026, 10, 31), "2026-10-02 - 2026-10-31"),
        (date(2026, 10, 1), date(2026, 11, 1), "2026-10-01 - 2026-11-01"),
        (date(2026, 12, 1), date(2027, 12, 31), "2026-12-01 - 2027-12-31"),
        # Preserve the existing partial-month label during this move.
        (date(2026, 10, 1), date(2026, 10, 15), "2026-10"),
    ]
    for start, end, expected in cases:
        assert period_review_service.period_label(start, end) == expected
        assert period_review_service.period_label(start, end, "Custom label") == "Custom label"


def test_default_range_returns_current_month_boundaries_including_december(monkeypatch):
    for today, expected in [
        (date(2026, 10, 11), (date(2026, 10, 1), date(2026, 10, 31))),
        (date(2026, 12, 15), (date(2026, 12, 1), date(2026, 12, 31))),
        (date(2026, 2, 15), (date(2026, 2, 1), date(2026, 2, 28))),
        (date(2024, 2, 15), (date(2024, 2, 1), date(2024, 2, 29))),
    ]:
        class FrozenDate(date):
            @classmethod
            def today(cls):
                return today

        monkeypatch.setattr(period_review_service, "date", FrozenDate)
        assert period_review_service.default_range() == expected


def save_review(db, start, end, *, client_id=1, label=""):
    return period_review_service.upsert_review(
        db, client_id, schemas.PeriodReviewCreate(
            start_date=start, end_date=end, label=label,
            reflection="Saved reflection", next_actions="Saved actions",
        ),
    )


def test_list_reviews_returns_empty_without_fabricating_a_review(db):
    assert period_review_service.list_reviews(db, 1) == []
    assert db.query(models.PeriodReview).count() == 0


def test_list_reviews_orders_by_start_then_end_descending(db):
    ranges = [
        (date(2026, 10, 1), date(2026, 10, 31)),
        (date(2026, 9, 1), date(2026, 12, 31)),
        (date(2026, 10, 1), date(2026, 10, 15)),
        (date(2026, 11, 1), date(2026, 11, 30)),
    ]
    saved = [save_review(db, start, end) for start, end in ranges]
    reviews = period_review_service.list_reviews(db, 1)
    assert [row.id for row in reviews] == [saved[i].id for i in (3, 0, 2, 1)]


def test_list_reviews_limit_keeps_only_the_newest_periods(db):
    saved = [save_review(db, date(2026, month, 1), date(2026, month, 28))
             for month in (9, 10, 11)]
    assert [row.id for row in period_review_service.list_reviews(db, 1, limit=2)] == [
        saved[2].id, saved[1].id,
    ]


def test_list_reviews_is_client_scoped_before_applying_limit(db):
    db.add(models.Client(id=2, name="other", ai_config={}, general_settings={}))
    db.commit()
    own = save_review(db, date(2026, 9, 1), date(2026, 9, 30))
    other = save_review(db, date(2026, 10, 1), date(2026, 10, 31), client_id=2)
    assert [row.id for row in period_review_service.list_reviews(db, 1, limit=1)] == [own.id]
    assert [row.id for row in period_review_service.list_reviews(db, 2)] == [other.id]


@pytest.mark.parametrize("start,end,label", [
    (date(2026, 10, 1), date(2026, 10, 31), ""),
    (date(2026, 10, 2), date(2026, 11, 5), ""),
    (date(2026, 10, 1), date(2026, 10, 31), "Custom review"),
])
def test_list_reviews_preserves_period_label(db, start, end, label):
    save_review(db, start, end, label=label)
    review, = period_review_service.list_reviews(db, 1)
    assert review.label == period_review_service.period_label(start, end, label)


def request_review_list(db, query=""):
    app = FastAPI()
    app.include_router(period_reviews.router)
    app.dependency_overrides[period_reviews.get_db] = lambda: db
    app.dependency_overrides[period_reviews.get_current_client] = lambda: db.get(models.Client, 1)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://testserver") as http:
            return await http.get(f"/period-reviews/list{query}")

    return asyncio.run(run())


@pytest.mark.parametrize("query,status", [
    ("", 200), ("?limit=1", 200), ("?limit=200", 200),
    ("?limit=0", 422), ("?limit=201", 422), ("?limit=invalid", 422),
])
def test_list_route_validates_limit_and_returns_empty_list(db, query, status):
    response = request_review_list(db, query)
    assert response.status_code == status, response.text
    if status == 200:
        assert response.json() == []


def test_list_route_serializes_saved_reviews_and_applies_limit(db):
    save_review(db, date(2026, 9, 1), date(2026, 9, 30))
    newest = save_review(db, date(2026, 10, 2), date(2026, 11, 5))
    response = request_review_list(db, "?limit=1")
    assert response.status_code == 200, response.text
    assert response.json() == [schemas.PeriodReview.model_validate(newest).model_dump(mode="json")]
