from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services.period_review_service import default_range, get_review, list_reviews, period_label, upsert_review

router = APIRouter(prefix="/period-reviews", tags=["period-reviews"])


@router.get("/list", response_model=list[schemas.PeriodReview])
def list_period_reviews(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return list_reviews(db, current_client.id, limit=limit)


@router.get("/", response_model=schemas.PeriodReview)
def get_period_review(
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    if start_date is None or end_date is None:
        start_date, end_date = default_range()
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date must be on or after start_date")

    review = get_review(db, current_client.id, start_date, end_date)

    if review:
        return review

    return schemas.PeriodReview(
        id=0,
        start_date=start_date,
        end_date=end_date,
        label=period_label(start_date, end_date),
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

    return upsert_review(db, current_client.id, payload)
