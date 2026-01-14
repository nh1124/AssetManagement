from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import date
from typing import List, Optional
from . import models, schemas
from .database import SessionLocal, engine

# Create tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Finance IDE API", version="2.2.0")

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/")
def root():
    return {"message": "Finance IDE API v2.2", "status": "running"}

# Analysis endpoints
@app.get("/analysis/summary", response_model=schemas.AnalysisSummary)
def get_analysis_summary(db: Session = Depends(get_db)):
    # TODO: Calculate from actual data
    # Mock data for now
    total_cash = 1500000
    cc_unpaid = 45000
    next_month_budget = 137000
    effective_cash = total_cash - cc_unpaid - next_month_budget
    
    return {
        "net_worth": 4800000,
        "monthly_pl": 150000,
        "liability_total": 1245000,
        "effective_cash": effective_cash,
        "cfo_briefing": "Financial health stable. Net worth up 2.3% this month."
    }

# Transaction endpoints with date filtering
@app.get("/transactions/", response_model=List[schemas.Transaction])
def get_transactions(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    limit: int = Query(50, le=100),
    db: Session = Depends(get_db)
):
    query = db.query(models.Transaction)
    
    if start_date:
        query = query.filter(models.Transaction.date >= start_date)
    if end_date:
        query = query.filter(models.Transaction.date <= end_date)
    
    return query.order_by(models.Transaction.date.desc()).limit(limit).all()

@app.post("/transactions/", response_model=schemas.Transaction)
def create_transaction(transaction: schemas.TransactionCreate, db: Session = Depends(get_db)):
    db_transaction = models.Transaction(**transaction.model_dump())
    db.add(db_transaction)
    db.commit()
    db.refresh(db_transaction)
    return db_transaction

# Product endpoints
@app.get("/products/", response_model=List[schemas.Product])
def get_products(
    category: Optional[str] = Query(None),
    is_asset: Optional[bool] = Query(None),
    db: Session = Depends(get_db)
):
    query = db.query(models.Product)
    
    if category:
        query = query.filter(models.Product.category == category)
    if is_asset is not None:
        query = query.filter(models.Product.is_asset == is_asset)
    
    return query.all()

@app.post("/products/", response_model=schemas.Product)
def create_product(product: schemas.ProductCreate, db: Session = Depends(get_db)):
    db_product = models.Product(**product.model_dump())
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    return db_product

# Budget endpoints
@app.get("/budgets/", response_model=List[schemas.Budget])
def get_budgets(month: Optional[str] = Query(None), db: Session = Depends(get_db)):
    query = db.query(models.Budget)
    if month:
        query = query.filter(models.Budget.month == month)
    return query.all()

@app.post("/budgets/", response_model=schemas.Budget)
def create_budget(budget: schemas.BudgetCreate, db: Session = Depends(get_db)):
    db_budget = models.Budget(**budget.model_dump())
    db.add(db_budget)
    db.commit()
    db.refresh(db_budget)
    return db_budget

# Life Event endpoints
@app.get("/life-events/", response_model=List[schemas.LifeEvent])
def get_life_events(db: Session = Depends(get_db)):
    return db.query(models.LifeEvent).all()

@app.post("/life-events/", response_model=schemas.LifeEvent)
def create_life_event(event: schemas.LifeEventCreate, db: Session = Depends(get_db)):
    db_event = models.LifeEvent(**event.model_dump())
    db.add(db_event)
    db.commit()
    db.refresh(db_event)
    return db_event

# Simulation Config endpoints
@app.get("/simulation/config", response_model=schemas.SimulationConfig)
def get_simulation_config(db: Session = Depends(get_db)):
    config = db.query(models.SimulationConfig).first()
    if not config:
        # Return defaults
        return schemas.SimulationConfig(
            id=0,
            annual_return=5.0,
            monthly_savings=100000,
            tax_rate=20.0,
            is_nisa=True
        )
    return config

@app.put("/simulation/config", response_model=schemas.SimulationConfig)
def update_simulation_config(config: schemas.SimulationConfigCreate, db: Session = Depends(get_db)):
    db_config = db.query(models.SimulationConfig).first()
    if db_config:
        for key, value in config.model_dump().items():
            setattr(db_config, key, value)
    else:
        db_config = models.SimulationConfig(**config.model_dump())
        db.add(db_config)
    
    db.commit()
    db.refresh(db_config)
    return db_config
