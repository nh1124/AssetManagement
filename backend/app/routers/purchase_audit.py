from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..dependencies import get_current_client
from ..services.purchase_audit_service import audit_purchase

router = APIRouter(tags=["purchase_audit"])


class PurchaseAuditRequest(BaseModel):
    name: str
    price: float
    lifespan_months: int = 12
    category: str = "Other"


@router.post("/purchase-audit")
def purchase_audit(
    request: PurchaseAuditRequest,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return audit_purchase(
        db=db,
        client_id=current_client.id,
        price=request.price,
        lifespan_months=request.lifespan_months,
        name=request.name,
    )
