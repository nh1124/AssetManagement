from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from typing import List, Optional
from .. import models
from ..database import get_db
from ..security import encrypt_key, decrypt_key
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

@router.get("/", response_model=List[ClientResponse])
def get_clients(db: Session = Depends(get_db)):
    """Get all clients with masked AI config. Matches VisionArk's get_settings pattern."""
    clients = db.query(models.Client).all()
    results = []
    for c in clients:
        # Mask API keys
        ai_config = dict(c.ai_config) if c.ai_config else {}
        masked_config = ai_config.copy()
        for key in ["gemini_api_key", "openai_api_key"]:
            if masked_config.get(key):
                masked_config[key] = "********"
        
        results.append({
            "id": c.id, 
            "name": c.name, 
            "ai_config": masked_config,
            "general_settings": c.general_settings or {},
            "has_key": "gemini_api_key" in ai_config
        })
    return results


@router.post("/")
def create_client(name: str, db: Session = Depends(get_db)):
    """Create a new client."""
    db_client = models.Client(name=name, ai_config={}, general_settings={})
    db.add(db_client)
    db.commit()
    db.refresh(db_client)
    return db_client

@router.put("/{client_id}/key")
def update_client_key(client_id: int, key_data: ClientKeyUpdate, db: Session = Depends(get_db)):
    """Update (and encrypt) a client's Gemini API key in ai_config JSON. Matches VisionArk patch/ai."""
    from sqlalchemy.orm.attributes import flag_modified
    
    db_client = db.query(models.Client).filter(models.Client.id == client_id).first()
    if not db_client:
        raise HTTPException(status_code=404, detail="Client not found")
    
    # Update ai_config JSON blob
    config = dict(db_client.ai_config) if db_client.ai_config else {}
    config["gemini_api_key"] = encrypt_key(key_data.gemini_api_key)
    db_client.ai_config = config
    
    # Required for SQLAlchemy to detect JSON changes
    flag_modified(db_client, "ai_config")
    
    db.commit()
    return {"message": "API key updated and encrypted successfully in ai_config"}
