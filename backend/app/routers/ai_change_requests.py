from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services.ai_change_request_service import (
    apply_change_request,
    approve_change_request,
    create_change_request,
    list_change_requests,
    preview_change_request,
    refresh_preview,
    reject_change_request,
)
from ..utils.jwt import decode_token


router = APIRouter(prefix="/ai/change-requests", tags=["ai-change-requests"])


def _with_request_context(
    payload: schemas.AiChangeRequestPreviewRequest | schemas.AiChangeRequestCreate,
    request: Request,
):
    mcp_client_id = payload.mcp_client_id or request.headers.get("x-mcp-client-id")
    tool_name = payload.tool_name or request.headers.get("x-mcp-tool-name")
    source = "mcp_http" if mcp_client_id and payload.source == "backend" else payload.source
    return payload.model_copy(update={
        "source": source,
        "tool_name": tool_name,
        "mcp_client_id": mcp_client_id,
    })


@router.get("", response_model=list[schemas.AiChangeRequest])
def get_change_requests(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return list_change_requests(db, current_client.id, status_filter=status, limit=limit, offset=offset)


@router.post("/preview", response_model=schemas.AiChangeRequestPreview)
def preview_ai_change_request(
    payload: schemas.AiChangeRequestPreviewRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return preview_change_request(db, current_client.id, _with_request_context(payload, request))


@router.post("", response_model=schemas.AiChangeRequest)
def post_change_request(
    payload: schemas.AiChangeRequestCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return create_change_request(db, current_client.id, current_client.id, _with_request_context(payload, request))


@router.post("/{change_request_id}/approve", response_model=schemas.AiChangeRequest)
def approve_ai_change_request(
    change_request_id: int,
    payload: schemas.AiChangeRequestActionRequest,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    token_payload = decode_token(payload.step_up_token) if payload.step_up_token else None
    return approve_change_request(db, current_client.id, current_client.id, change_request_id, token_payload)


@router.post("/{change_request_id}/apply", response_model=schemas.AiChangeRequest)
def apply_ai_change_request(
    change_request_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return apply_change_request(db, current_client.id, current_client.id, change_request_id)


@router.post("/{change_request_id}/reject", response_model=schemas.AiChangeRequest)
def reject_ai_change_request(
    change_request_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return reject_change_request(db, current_client.id, change_request_id)


@router.post("/{change_request_id}/refresh-preview", response_model=schemas.AiChangeRequest)
def refresh_ai_change_request_preview(
    change_request_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return refresh_preview(db, current_client.id, change_request_id)
