from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import Optional
from . import models
from .database import get_db
from .utils.jwt import decode_token

bearer_scheme = HTTPBearer(auto_error=False)

async def get_current_client(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db)
) -> models.Client:
    """
    Resolve the authenticated client from the bearer token only.

    Client identity is a login boundary. Do not accept caller-controlled
    headers or local storage values as a way to switch tenants.
    """
    client_id = None
    if credentials:
        payload = decode_token(credentials.credentials)
        if payload:
            client_id = payload.get("sub")

    if not client_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    client = db.query(models.Client).filter(models.Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    return client

