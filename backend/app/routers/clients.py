from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from ..domain.messages import Message
from .. import models
from ..database import get_db
from ..dependencies import get_current_client
from ..services.cache_service import invalidate_client
from ..services.client_settings_service import merge_general_settings
from pydantic import BaseModel

router = APIRouter(prefix="/clients", tags=["clients"])

class ClientResponse(BaseModel):
    id: int
    name: str
    general_settings: dict

    class Config:
        from_attributes = True



class ClientSettingsUpdate(BaseModel):
    general_settings: dict


def _client_response(client: models.Client) -> dict:
    return {
        "id": client.id,
        "name": client.name,
        "general_settings": client.general_settings or {},
    }


@router.get("/", response_model=List[ClientResponse])
def get_clients(current_client: models.Client = Depends(get_current_client)):
    """Return only the authenticated client."""
    return [_client_response(current_client)]



@router.put("/{client_id}/settings")
def update_client_settings(
    client_id: int,
    payload: ClientSettingsUpdate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    if current_client.id != client_id:
        raise HTTPException(status_code=403, detail=Message("Cannot edit another client settings", ja="ほかのクライアントの設定は変更できません。"))
    settings = merge_general_settings(db, current_client, payload.general_settings)
    invalidate_client(current_client.id)
    return settings
