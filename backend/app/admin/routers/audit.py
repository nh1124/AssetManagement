"""Filtered administrator audit reads."""
from datetime import datetime
from fastapi import APIRouter, Depends
from ...database import get_db
from ...domain.admin_permissions import AUDIT_READ
from ...services import admin_audit_service as service
from ..auth import require

router = APIRouter(prefix="/admin/api/audit")


@router.get("")
def audit(actor: str | None = None, action: str | None = None, target_client_id: int | None = None,
          since: datetime | None = None, until: datetime | None = None, limit: int = 100, offset: int = 0,
          context=Depends(require(AUDIT_READ)), db=Depends(get_db)):
    return service.list_logs(db, actor=actor, action_prefix=action, target_client_id=target_client_id,
                             start_at=since, end_at=until, limit=limit, offset=offset)
