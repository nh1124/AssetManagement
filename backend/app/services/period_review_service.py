from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from .. import models, schemas


def default_range() -> tuple[date, date]:
    today = date.today()
    start = date(today.year, today.month, 1)
    if today.month == 12:
        end = date(today.year, 12, 31)
    else:
        end = date(today.year, today.month + 1, 1) - date.resolution
    return start, end


def period_label(start_date: date, end_date: date, label: str | None = None) -> str:
    if label:
        return label
    if start_date.day == 1 and start_date.year == end_date.year and start_date.month == end_date.month:
        return f"{start_date.year}-{start_date.month:02d}"
    return f"{start_date.isoformat()} - {end_date.isoformat()}"


def list_reviews(
    db: Session, client_id: int, *, limit: int = 50,
) -> list[models.PeriodReview]:
    # Saved rows distinguish review history from an unsaved range's empty form.
    return db.query(models.PeriodReview).filter(
        models.PeriodReview.client_id == client_id,
    ).order_by(
        models.PeriodReview.start_date.desc(),
        models.PeriodReview.end_date.desc(),
        models.PeriodReview.id.desc(),
    ).limit(limit).all()


def get_review(
    db: Session, client_id: int, start_date: date, end_date: date,
) -> models.PeriodReview | None:
    return db.query(models.PeriodReview).filter(
        models.PeriodReview.client_id == client_id,
        models.PeriodReview.start_date == start_date,
        models.PeriodReview.end_date == end_date,
    ).first()


def upsert_review(
    db: Session, client_id: int, payload: schemas.PeriodReviewCreate, *, commit: bool = True,
) -> models.PeriodReview:
    review = get_review(db, client_id, payload.start_date, payload.end_date)
    if review:
        review.label = period_label(payload.start_date, payload.end_date, payload.label)
        review.reflection = payload.reflection
        review.next_actions = payload.next_actions
    else:
        review = models.PeriodReview(
            client_id=client_id,
            start_date=payload.start_date,
            end_date=payload.end_date,
            label=period_label(payload.start_date, payload.end_date, payload.label),
            reflection=payload.reflection,
            next_actions=payload.next_actions,
        )
        db.add(review)

    if commit:
        db.commit()
        db.refresh(review)
    else:
        db.flush()
    return review
