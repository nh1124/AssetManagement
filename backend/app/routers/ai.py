from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from typing import List, Optional
import httpx
import json
from .. import models
from ..database import get_db
from ..dependencies import get_current_client
from ..security import decrypt_key

router = APIRouter(prefix="/api/analyze", tags=["ai"])

@router.post("/")
async def analyze_transaction(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """
    Backend Gemini AI Analysis.
    Retrieves the client's API key from the DB, decrypts it, and calls Gemini.
    """
    api_key = current_client.gemini_api_key
    if not api_key:
        raise HTTPException(status_code=400, detail="Gemini API Key not set or decryption failed for this client")


    # Construct the Gemini prompt
    parts = payload.get("parts", [])
    if not parts:
        raise HTTPException(status_code=400, detail="Empty parts provided")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                url,
                json={"contents": [{"parts": parts}], "generationConfig": {"temperature": 0.1}},
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail=f"Gemini API error: {e.response.text}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Unexpected error calling Gemini: {str(e)}")
