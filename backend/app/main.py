from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from . import models
from .database import engine
from .routers import transactions, products, budgets, life_events, simulation, analysis

# Create tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Finance IDE API",
    version="2.2.0",
    description="Personal Finance Management API with CFO Logic"
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(analysis.router)
app.include_router(transactions.router)
app.include_router(products.router)
app.include_router(budgets.router)
app.include_router(life_events.router)
app.include_router(simulation.router)

@app.get("/")
def root():
    return {"message": "Finance IDE API v2.2", "status": "running"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}
