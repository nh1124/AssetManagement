from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from .. import schemas
from ..database import get_db
from ..services import analysis_service

router = APIRouter(prefix="/analysis", tags=["analysis"])

@router.get("/summary", response_model=schemas.AnalysisSummary)
def get_analysis_summary(db: Session = Depends(get_db)):
    return analysis_service.get_summary(db)
