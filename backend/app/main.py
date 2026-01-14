from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from . import models
from .database import engine
from .routers import transactions, products, budgets, life_events, simulation, analysis, accounts, ai, clients, auth
from .dependencies import get_current_client

# Create tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Finance IDE API",
    version="4.0.0",
    description="SaaS Refactor - Multi-Client Finance Management"
)

# Startup Seed Logic
@app.on_event("startup")
def startup_event():
    from .database import SessionLocal
    from . import models
    from .utils.password import hash_password

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
        for table in ["accounts", "transactions", "products", "life_events", "budgets", "simulation_configs"]:
            try:
                db.execute(text(f"UPDATE {table} SET client_id = 1 WHERE client_id IS NULL"))
            except Exception:
                pass
        db.commit()

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
app.include_router(budgets.router)
app.include_router(life_events.router)
app.include_router(simulation.router)
app.include_router(accounts.router)
app.include_router(ai.router)
app.include_router(clients.router)
app.include_router(auth.router)

@app.get("/me")
def get_me(current_client: models.Client = Depends(get_current_client)):
    """Get current authenticated user. Pattern from VisionArk."""
    return {
        "id": current_client.id,
        "name": current_client.name,
        "username": current_client.username,
        "email": current_client.email
    }

@app.get("/")
def root():
    return {"message": "Finance IDE API v4.0", "status": "running"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}
