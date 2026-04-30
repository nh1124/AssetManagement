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
You can also extract RECURRING payment rules if the input implies a repeating intent (e.g., "monthly subscription", "yearly fee").

Return a JSON array of objects.

Field definitions:
- type: "Expense" | "Income" | "Transfer" | "LiabilityPayment" | "Borrowing" | "CreditExpense" | "CreditAssetPurchase" | "Product"
- date: "YYYY-MM-DD" (Default to today if not found)
- amount: number
- currency: "JPY" | "USD" | "EUR" (Default to JPY)
- category: string (Food, Transport, Entertainment, etc.)
- description: string
- from_account: "cash" | "bank" | "credit" | null
- to_account: "expense" | "savings" | "investment" | null
- is_recurring: boolean (true if this is a recurring rule)
- frequency: "Monthly" | "Yearly" (Required if is_recurring is true)
- day_of_month: number (1-31, Required if is_recurring is true)

Return format (JSON ONLY array):
[
  {
    "type": "Expense",
    "amount": 1500,
    "currency": "JPY",
    "category": "Food",
    "description": "Lunch at Yoshinoya",
    "date": "2026-01-14",
    "is_recurring": false
  },
  {
    "type": "Expense",
    "amount": 1200,
    "currency": "USD",
    "category": "Software",
    "description": "Netflix Subscription",
    "is_recurring": true,
    "frequency": "Monthly",
    "day_of_month": 15
  }
]
"""


# Helper for Gemini Call
async def call_gemini(api_key: str, prompt: str, schema: str = "application/json") -> dict:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                url,
                json={
                    "contents": [{"parts": [{"text": prompt}]}], 
                    "generationConfig": {
                        "temperature": 0.2,
                        "response_mime_type": schema
                    }
                },
                timeout=60.0
            )
            response.raise_for_status()
            data = response.json()
            text = data['candidates'][0]['content']['parts'][0]['text']
            return json.loads(text)
        except Exception as e:
            print(f"Gemini Error: {e}")
            raise HTTPException(status_code=500, detail=f"AI Service Error: {str(e)}")

@router.post("/")
async def analyze_transaction(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Analyze transaction text/images."""
    api_key = current_client.gemini_api_key
    if not api_key:
        raise HTTPException(status_code=400, detail="Gemini API Key not set")

    parts = payload.get("parts", [])
    # Re-construct complex prompt logic if needed or just use the helper for simple text
    # Since payload has 'parts' which might be images, we keep original logic for this specific large endpoint
    # OR we can just use the helper if we assume text-only for now, but the original supported images.
    # Let's keep the original implementation for the main analyze endpoint to avoid breaking image support, 
    # but use the helper for the NEW endpoints.
    
    # ... (Original implementation omitted for brevity in this replace block, expecting separate functions)
    # Actually, I am REPLACING the file content from line 40. I should preserve the image support.
    
    current_parts = [{"text": SYSTEM_PROMPT}] + parts
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                url,
                json={
                    "contents": [{"parts": current_parts}],
                    "generationConfig": {"temperature": 0.1, "response_mime_type": "application/json"}
                },
                timeout=30.0
            )
            response.raise_for_status()
            return json.loads(response.json()['candidates'][0]['content']['parts'][0]['text'])
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


@router.post("/suggest-budget")
async def suggest_budget(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Analyze spending history and suggest a budget."""
    api_key = current_client.gemini_api_key
    if not api_key:
        raise HTTPException(status_code=400, detail="Gemini API Key not set")
        
    # 1. Fetch Spending History (Last 90 days)
    from datetime import datetime, timedelta
    start_date = datetime.now() - timedelta(days=90)
    
    transactions = db.query(models.Transaction).filter(
        models.Transaction.client_id == current_client.id,
        models.Transaction.date >= start_date,
        models.Transaction.type == "Expense"
    ).all()
    
    # Summarize by category
    summary = {}
    for t in transactions:
        cat = t.category or "Uncategorized"
        summary[cat] = summary.get(cat, 0) + t.amount
        
    # Calculate monthly average
    avg_summary = {k: round(v / 3) for k, v in summary.items()}
    
    prompt = f"""
    You are a financial advisor. Here is the client's average monthly spending by category (in JPY):
    {json.dumps(avg_summary, ensure_ascii=False)}
    
    Please suggest a realistic but optimized budget for each category to help them save more.
    Identify areas where they might be overspending.
    
    Return JSON array:
    [
        {{ "category": "Food", "current_avg": 50000, "suggested_limit": 45000, "reason": "Slight reduction possible" }}
    ]
    """
    
    result = await call_gemini(api_key, prompt)
    return result

@router.post("/optimize-allocations")
async def optimize_allocations(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Suggest asset allocations based on goals."""
    api_key = current_client.gemini_api_key
    if not api_key:
        raise HTTPException(status_code=400, detail="Gemini API Key not set")

    # 1. Fetch Goals
    goals = db.query(models.LifeEvent).filter(models.LifeEvent.client_id == current_client.id).all()
    goals_data = [{
        "id": g.id, "name": g.name, "target": g.target_amount, "date": str(g.target_date), "priority": g.priority
    } for g in goals]
    
    # 2. Fetch Assets
    assets = db.query(models.Account).filter(
        models.Account.client_id == current_client.id, 
        models.Account.account_type == "asset"
    ).all()
    assets_data = [{
        "id": a.id, "name": a.name, "balance": a.balance, "return_rate": a.expected_return
    } for a in assets]
    
    prompt = f"""
    Act as a portfolio manager.
    Goals: {json.dumps(goals_data)}
    Assets: {json.dumps(assets_data)}
    
    Allocate assets to goals to maximize probability of success for high priority goals.
    An asset can be split across multiple goals. Total allocation of an asset must not exceed 100%.
    
    Return JSON array:
    [
        {{ "account_id": 1, "life_event_id": 2, "percentage": 50, "reason": "High yield asset for long term goal" }}
    ]
    """
    
    result = await call_gemini(api_key, prompt)
    return result
