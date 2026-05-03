from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client

router = APIRouter(prefix="/period-reviews", tags=["period-reviews"])


def _default_range() -> tuple[date, date]:
    today = date.today()
    start = date(today.year, today.month, 1)
    if today.month == 12:
        end = date(today.year, 12, 31)
    else:
        end = date(today.year, today.month + 1, 1) - date.resolution
    return start, end


def _label(start_date: date, end_date: date, label: str | None = None) -> str:
    if label:
        return label
    if start_date.day == 1 and start_date.year == end_date.year and start_date.month == end_date.month:
        return f"{start_date.year}-{start_date.month:02d}"
    return f"{start_date.isoformat()} - {end_date.isoformat()}"


@router.get("/", response_model=schemas.PeriodReview)
def get_period_review(
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    if start_date is None or end_date is None:
        start_date, end_date = _default_range()
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date must be on or after start_date")

    review = db.query(models.PeriodReview).filter(
        models.PeriodReview.client_id == current_client.id,
        models.PeriodReview.start_date == start_date,
        models.PeriodReview.end_date == end_date,
    ).first()

    if review:
        return review

    return schemas.PeriodReview(
        id=0,
        start_date=start_date,
        end_date=end_date,
        label=_label(start_date, end_date),
        reflection="",
        next_actions="",
        created_at=datetime.utcnow(),
        updated_at=None,
    )


@router.put("/", response_model=schemas.PeriodReview)
def upsert_period_review(
    payload: schemas.PeriodReviewCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    if payload.end_date < payload.start_date:
        raise HTTPException(status_code=400, detail="end_date must be on or after start_date")

    review = db.query(models.PeriodReview).filter(
        models.PeriodReview.client_id == current_client.id,
        models.PeriodReview.start_date == payload.start_date,
        models.PeriodReview.end_date == payload.end_date,
    ).first()

    if review:
        review.label = _label(payload.start_date, payload.end_date, payload.label)
        review.reflection = payload.reflection
        review.next_actions = payload.next_actions
    else:
        review = models.PeriodReview(
            client_id=current_client.id,
            start_date=payload.start_date,
            end_date=payload.end_date,
            label=_label(payload.start_date, payload.end_date, payload.label),
            reflection=payload.reflection,
            next_actions=payload.next_actions,
        )
        db.add(review)

    db.commit()
    db.refresh(review)
    return review
