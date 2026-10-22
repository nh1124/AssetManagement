from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..dependencies import get_current_client
from ..domain.transfer import EXPORT_VERSION, validate_import_payload
from ..services.data_health_service import check_data_health
from ..services.data_transfer_service import export_client, import_client

router = APIRouter(prefix="/data", tags=["data"])


class ImportPayload(BaseModel):
    version: int | None = None
    exported_at: str | None = None
    manifest: dict[str, Any] | None = None
    client: dict[str, Any] | None = None
    data: dict[str, list[dict[str, Any]]]


@router.get("/export")
def export_client_data(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return export_client(db, current_client)


@router.post("/import/validate")
def validate_import_client_data(
    payload: ImportPayload,
    current_client: models.Client = Depends(get_current_client),
):
    validation = validate_import_payload(payload.data, payload.version, payload.manifest)
    return {
        **validation,
        "client": {
            "target_client_id": current_client.id,
            "source_client_id": (payload.client or {}).get("id"),
            "source_name": (payload.client or {}).get("name"),
        },
    }


@router.post("/import")
def import_client_data(
    payload: ImportPayload,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return import_client(
        db, current_client, data=payload.data, version=payload.version, manifest=payload.manifest
    )


@router.get("/health")
def data_health_check(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return check_data_health(db, current_client.id, audience="user")
