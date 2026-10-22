"""Capability-filtered installation overview."""
from fastapi import APIRouter, Depends
from ...database import get_db
from ...domain.admin_permissions import ACCOUNTS_READ
from ...workflows import admin_account_workflow as workflow
from ..auth import require

router = APIRouter(prefix="/admin/api/overview")


@router.get("")
def overview(context=Depends(require(ACCOUNTS_READ)), db=Depends(get_db)):
    return workflow.overview(db, context.permissions)
