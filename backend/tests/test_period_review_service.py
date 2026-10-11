from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app import models, schemas
from backend.app.database import Base
from backend.app.services import period_review_service


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
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
