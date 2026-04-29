from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client

router = APIRouter(prefix="/monthly-reviews", tags=["monthly-reviews"])


def _default_period() -> str:
    today = date.today()
    return f"{today.year}-{today.month:02d}"


@router.get("/", response_model=schemas.MonthlyReview)
def get_monthly_review(
    period: str | None = Query(None, description="YYYY-MM"),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    target_period = period or _default_period()
    review = db.query(models.MonthlyReview).filter(
        models.MonthlyReview.client_id == current_client.id,
        models.MonthlyReview.target_period == target_period,
    ).first()

    if review:
        return review

    return schemas.MonthlyReview(
        id=0,
        target_period=target_period,
        reflection="",
        next_actions="",
        created_at=datetime.utcnow(),
        updated_at=None,
    )


@router.put("/", response_model=schemas.MonthlyReview)
def upsert_monthly_review(
    payload: schemas.MonthlyReviewCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    review = db.query(models.MonthlyReview).filter(
        models.MonthlyReview.client_id == current_client.id,
        models.MonthlyReview.target_period == payload.target_period,
    ).first()

    if review:
        review.reflection = payload.reflection
        review.next_actions = payload.next_actions
    else:
        review = models.MonthlyReview(
            client_id=current_client.id,
            target_period=payload.target_period,
            reflection=payload.reflection,
            next_actions=payload.next_actions,
        )
        db.add(review)

    db.commit()
    db.refresh(review)
    return review
