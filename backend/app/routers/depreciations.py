"""HTTP adapters for write-downs recorded by hand from the ledger."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services.ai_policy_service import assert_direct_ledger_write_allowed
from ..workflows import depreciation_workflow as workflow

router = APIRouter(prefix="/depreciations", tags=["depreciations"])


def _row(row: models.ProductDepreciation) -> dict:
    return {"id": row.id, "product_id": row.product_id, "period": row.period, "transaction_id": row.transaction_id}


@router.get("/preview")
def preview(
    product_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """The next period, its amount and the product's accounts, for the ledger's form."""
    return workflow.preview(db, current_client.id, product_id)


@router.post("")
def record(
    payload: schemas.DepreciationRecord,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
    request: Request = None,
):
    assert_direct_ledger_write_allowed(
        db, current_client.id, mcp_client_id=request.headers.get("x-mcp-client-id") if request else None, risk="medium",
    )
    return _row(workflow.record(db, current_client.id, payload))


@router.put("/{depreciation_id}")
def amend(
    depreciation_id: int,
    payload: schemas.DepreciationAmend,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
    request: Request = None,
):
    assert_direct_ledger_write_allowed(
        db, current_client.id, mcp_client_id=request.headers.get("x-mcp-client-id") if request else None, risk="medium",
    )
    return _row(workflow.amend(db, current_client.id, depreciation_id, payload))
