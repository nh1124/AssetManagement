from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from .. import models
from ..database import get_db
from ..dependencies import get_current_client
from ..services.cache_service import invalidate_client
from ..services.client_settings_service import merge_general_settings, set_gemini_api_key
from pydantic import BaseModel

router = APIRouter(prefix="/clients", tags=["clients"])

class ClientResponse(BaseModel):
    id: int
    name: str
    ai_config: dict
    general_settings: dict
    has_key: bool  # Legacy helper for frontend

    class Config:
        from_attributes = True


class ClientKeyUpdate(BaseModel):
    gemini_api_key: str


class ClientCreatePayload(BaseModel):
    name: str
    seed_defaults: bool = True


class ClientSettingsUpdate(BaseModel):
    general_settings: dict


def _client_response(client: models.Client) -> dict:
    ai_config = dict(client.ai_config) if client.ai_config else {}
    masked_config = ai_config.copy()
    for key in ["gemini_api_key", "openai_api_key"]:
        if masked_config.get(key):
            masked_config[key] = "********"

    return {
        "id": client.id,
        "name": client.name,
        "ai_config": masked_config,
        "general_settings": client.general_settings or {},
        "has_key": "gemini_api_key" in ai_config,
    }


@router.get("/", response_model=List[ClientResponse])
def get_clients(current_client: models.Client = Depends(get_current_client)):
    """Return only the authenticated client."""
    return [_client_response(current_client)]


@router.post("/", response_model=ClientResponse)
def create_client(
    payload: ClientCreatePayload,
    current_client: models.Client = Depends(get_current_client),
):
    """Create a new client."""
    raise HTTPException(status_code=403, detail="Create a user through registration, then sign in as that user")

@router.put("/{client_id}/key")
def update_client_key(
    client_id: int,
    key_data: ClientKeyUpdate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """Update (and encrypt) a client's Gemini API key in ai_config JSON. Matches VisionArk patch/ai."""
    if current_client.id != client_id:
        raise HTTPException(status_code=403, detail="Cannot edit another client key")
    set_gemini_api_key(db, current_client, key_data.gemini_api_key)
    invalidate_client(current_client.id)
    return {"message": "API key updated and encrypted successfully in ai_config"}


@router.put("/{client_id}/settings")
def update_client_settings(
    client_id: int,
    payload: ClientSettingsUpdate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    if current_client.id != client_id:
        raise HTTPException(status_code=403, detail="Cannot edit another client settings")
    settings = merge_general_settings(db, current_client, payload.general_settings)
    invalidate_client(current_client.id)
    return settings
