from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import Optional
from . import models
from .database import get_db
from .utils.jwt import decode_token

bearer_scheme = HTTPBearer(auto_error=False)

async def get_current_client(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    x_client_id: Optional[str] = Header(None, alias="X-Client-Id"),
    db: Session = Depends(get_db)
) -> models.Client:
    """
    Dependency to resolve the active client. 
    Matches VisionArk's resolve_identity pattern: 
    1. Try Authorization: Bearer <JWT>
    2. Try X-Client-Id header (Legacy/Migration)
    """
    client_id = None

    # 1. Try JWT
    if credentials:
        payload = decode_token(credentials.credentials)
        if payload:
            client_id = payload.get("sub")
    
    # 2. Fallback to Header
    if not client_id and x_client_id:
        try:
            client_id = int(x_client_id)
        except ValueError:
            pass
            
    if not client_id:
        raise HTTPException(status_code=401, detail="Authentication required (JWT or X-Client-Id)")
        
    client = db.query(models.Client).filter(models.Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
        
    return client

