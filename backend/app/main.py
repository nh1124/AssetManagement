from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from . import models
from .routers import (
    accounts,
    actions,
    ai,
    analysis,
    auth,
    capsules,
    clients,
    data_transfer,
    exchange_rates,
    life_events,
    monthly_reviews,
    period_reviews,
    products,
    recurring,
    reports,
    roadmap,
    simulation,
    simulation_scenarios,
    transactions,
)
from .dependencies import get_current_client

app = FastAPI(
    title="Finance IDE API",
    version="4.0.0",
    description="SaaS Refactor - Multi-Client Finance Management"
)


def run_alembic_migrations() -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    alembic_cfg = Config(str(backend_dir / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    command.upgrade(alembic_cfg, "head")

# Startup Seed Logic
@app.on_event("startup")
def startup_event():
    from .database import SessionLocal
    from . import models
    from .utils.password import hash_password
    from .services.accounting_service import ensure_default_accounts

    run_alembic_migrations()

    db = SessionLocal()
    try:
        # 1. Ensure Default Client exists
        default_client = db.query(models.Client).filter(models.Client.id == 1).first()
        if not default_client:
            print("Seeding default admin user...")
            default_client = models.Client(
                id=1, 
                name="Default User",
                username="admin",
                password_hash=hash_password("adminadmin"),
                ai_config={},
                general_settings={}
            )
            db.add(default_client)
            db.commit()
            db.refresh(default_client)
            
            # Sync Postgres Sequence (since we manually forced ID=1)
            try:
                db.execute(text("SELECT setval('clients_id_seq', (SELECT MAX(id) FROM clients))"))
                db.commit()
            except Exception as e:
                print(f"Sequence sync skipped: {e}")
        else:
            # Ensure admin has valid credentials
            if not default_client.username or not default_client.password_hash:
                default_client.username = "admin"
                default_client.password_hash = hash_password("adminadmin")
                db.commit()

        # 2. Cleanup: Assign any orphan data to Default Client
        # This is safe even after a reset, as it just ensures data integrity.
        for table in [
            "accounts",
            "transactions",
            "products",
            "life_events",
            "simulation_configs",
            "recurring_transactions",
            "monthly_plan_lines",
            "monthly_reviews",
            "period_reviews",
            "milestones",
            "capsules",
            "exchange_rates",
        ]:
            try:
                db.execute(text(f"UPDATE {table} SET client_id = 1 WHERE client_id IS NULL"))
            except Exception:
                pass
        db.commit()
        ensure_default_accounts(db, client_id=1)

    finally:
        db.close()

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
app.include_router(life_events.router)
app.include_router(monthly_reviews.router)
app.include_router(period_reviews.router)
app.include_router(simulation.router)
app.include_router(simulation_scenarios.router)
app.include_router(accounts.router)
app.include_router(actions.router, dependencies=[Depends(get_current_client)])
app.include_router(ai.router)
app.include_router(clients.router)
app.include_router(data_transfer.router)
app.include_router(auth.router)
app.include_router(recurring.router, dependencies=[Depends(get_current_client)])
app.include_router(roadmap.router, dependencies=[Depends(get_current_client)])
app.include_router(capsules.router, dependencies=[Depends(get_current_client)])
app.include_router(reports.router, dependencies=[Depends(get_current_client)])
app.include_router(exchange_rates.router, dependencies=[Depends(get_current_client)])

@app.get("/me")
def get_me(current_client: models.Client = Depends(get_current_client)):
    """Get current authenticated user. Pattern from VisionArk."""
    return {
        "id": current_client.id,
        "name": current_client.name,
        "username": current_client.username,
        "email": current_client.email,
        "general_settings": current_client.general_settings or {},
    }

@app.get("/")
def root():
    return {"message": "Finance IDE API v4.0", "status": "running"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}
