from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from . import models, schemas, database
from .database import engine, get_db
from fastapi.middleware.cors import CORSMiddleware

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Asset Management API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Welcome to Asset Management API"}

@app.get("/analysis/summary", response_model=schemas.AnalysisSummary)
def get_summary(db: Session = Depends(get_db)):
    assets = db.query(models.Asset).all()
    liabilities = db.query(models.Liability).all()
    
    net_worth = sum(a.value for a in assets) - sum(l.balance for l in liabilities)
    liability_total = sum(l.balance for l in liabilities)
    
    # Simplified P/L for now (last 30 days transactions)
    # In a real app, this would be more complex
    monthly_pl = 0.0 
    
    return {
        "net_worth": net_worth,
        "monthly_pl": monthly_pl,
        "liability_total": liability_total
    }

# Standard CRUD would go here (or in routers)
# For brevity in the skeleton, I'll add basic Transaction CRUD

@app.get("/transactions/", response_model=List[schemas.Transaction])
def read_transactions(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    transactions = db.query(models.Transaction).offset(skip).limit(limit).all()
    return transactions

@app.post("/transactions/", response_model=schemas.Transaction)
def create_transaction(transaction: schemas.TransactionCreate, db: Session = Depends(get_db)):
    db_transaction = models.Transaction(**transaction.dict())
    db.add(db_transaction)
    db.commit()
    db.refresh(db_transaction)
    return db_transaction
