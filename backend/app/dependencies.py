from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import Optional
from . import models
from .database import get_db
from .domain.messages import LANGUAGES, Message
from .utils.jwt import decode_token, token_is_current

bearer_scheme = HTTPBearer(auto_error=False)
AUTHENTICATION_REQUIRED = Message("Authentication required", ja="サインインしてください。")


def request_language(request: Request) -> Optional[str]:
    """The UI language the request asks for in Accept-Language: "ja", "en", or None.

    The studio and the mobile app send their active language (WP29). None -- no
    header, "*", or neither language -- keeps every message as written, which is
    what the MCP server and other callers have always received.
    """
    best, best_quality = None, 0.0
    for part in request.headers.get("accept-language", "").split(","):
        tag, _, parameters = part.partition(";")
        quality = 1.0
        parameters = parameters.strip()
        if parameters.startswith("q="):
            try:
                quality = float(parameters[2:])
            except ValueError:
                quality = 0.0
        language = tag.strip().lower().split("-", 1)[0]
        if language in LANGUAGES and quality > best_quality:
            best, best_quality = language, quality
    return best

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
        if payload and payload.get("type") == "access":
            client_id = payload.get("sub")

    if not client_id:
        raise HTTPException(status_code=401, detail=AUTHENTICATION_REQUIRED)

    client = db.query(models.Client).filter(models.Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail=Message("Client not found", ja="クライアントが見つかりません。"))
    # A token outlives the decision to deactivate its owner by up to a day.
    if client.is_active is False:
        raise HTTPException(status_code=401, detail=AUTHENTICATION_REQUIRED)

    if not token_is_current(payload, client.tokens_valid_after):
        raise HTTPException(status_code=401, detail=AUTHENTICATION_REQUIRED)

    return client

