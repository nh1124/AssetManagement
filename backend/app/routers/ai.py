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

SYSTEM_PROMPT = """
You are a Finance AI Assistant. Analyze the user's input (text and/or receipt images) and extract ALL transactions, debt payments, or product updates.
Return a JSON array of objects.

Field definitions:
- type: "Expense" | "Income" | "Transfer" | "Debt" | "Product"
- date: "YYYY-MM-DD" (Default to today if not found)
- amount: number
- currency: "JPY" | "USD" | "EUR" (Default to JPY)
- category: string (Food, Transport, Entertainment, etc.)
- description: string
- from_account: "cash" | "bank" | "credit" | null
- to_account: "expense" | "savings" | "investment" | null

Return format (JSON ONLY array):
[
  {
    "type": "Expense",
    "amount": 1500,
    "currency": "JPY",
    "category": "Food",
    "description": "Lunch at Yoshinoya",
    "date": "2026-01-14"
  }
]
"""

@router.post("/")
async def analyze_transaction(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """
    Backend Gemini AI Analysis.
    Extracts multiple records from input and returns a JSON list.
    """
    api_key = current_client.gemini_api_key
    if not api_key:
        raise HTTPException(status_code=400, detail="Gemini API Key not set for this client")

    parts = payload.get("parts", [])
    if not parts:
        raise HTTPException(status_code=400, detail="Empty parts provided")

    # Prepend the system prompt
    current_parts = [{"text": SYSTEM_PROMPT}] + parts

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                url,
                json={
                    "contents": [{"parts": current_parts}], 
                    "generationConfig": {
                        "temperature": 0.1,
                        "response_mime_type": "application/json"
                    }
                },
                timeout=30.0
            )
            response.raise_for_status()
            raw_data = response.json()
            
            # Extract text and parse JSON to ensure it's a list
            try:
                text_content = raw_data['candidates'][0]['content']['parts'][0]['text']
                parsed_list = json.loads(text_content)
                if not isinstance(parsed_list, list):
                    parsed_list = [parsed_list]
                return parsed_list
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                print(f"Parsing error: {e}")
                raise HTTPException(status_code=500, detail="Failed to parse AI response into valid records")

        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail=f"Gemini API error: {e.response.text}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Unexpected error calling Gemini: {str(e)}")
