import asyncio
import logging
from datetime import date

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session
from . import models
from .config import settings
from .database import get_db
from .routers import (
    accounts,
    ai_change_requests,
    ai_operations,
    analysis,
    auth,
    automatic_recordings,
    budget_plans,
    capsules,
    clients,
    data_transfer,
    depreciations,
    exchange_rates,
    goal_budget,
    notifications,
    life_events,
    life_scenarios,
    household_members,
    mcp_oauth,
    period_reviews,
    plan,
    plan_reflection,
    products,
    registry_entries,
    reports,
    simulation,
    transaction_batches,
    transactions,
)
from .dependencies import get_current_client
from .routers.ai_operation_audit import AiOperationAuditMiddleware
from .utils.observability import (
    RequestLogMiddleware,
    install_db_audit,
    install_sql_timing,
    setup_logging,
)
from .utils.http import (
    api_docs_urls,
    install_exception_handlers,
    # Compatibility for tests/adapters that registered the original handlers.
    domain_error_handler,
    localized_http_exception_handler,
    localized_validation_error_handler,
)
from .utils.password import verify_password
from .services import mfa_service


setup_logging()
logger = logging.getLogger(__name__)
_automatic_recording_task: asyncio.Task | None = None


app = FastAPI(
    title="Finance IDE API",
    version="4.0.0",
    description="SaaS Refactor - Multi-Client Finance Management",
    **api_docs_urls(settings),
)


install_exception_handlers(app)


def ensure_no_development_password(db) -> None:
    clients = db.query(models.Client).filter(
        models.Client.username.in_(("admin", "dev")),
        models.Client.is_active.is_(True),
    ).all()
    if any(verify_password("adminadmin", client.password_hash or "") for client in clients):
        raise RuntimeError("Invalid production configuration: development password is still active")


async def run_automatic_recording_loop() -> None:
    """Daily run of every automatic recording the registry switches on."""
    from .database import SessionLocal
    from .workflows.automatic_recording_workflow import process_due_all
    from .workflows.plan_reflection_workflow import run_due_all
    from .workflows.fx_workflow import refresh_all

    while True:
        db = SessionLocal()
        try:
            process_due_all(db, today=date.today())
        except Exception:
            db.rollback()
            logger.exception("Automatic recording cycle failed")
        try:
            # 自動反映 at the start of a month (WP27), after the month's automatic transactions are posted.
            run_due_all(db)
        except Exception:
            db.rollback()
            logger.exception("Plan reflection cycle failed")
        try:
            refresh_all(db)
        except Exception:
            db.rollback()
            logger.exception("FX refresh cycle failed")
        finally:
            db.close()
        await asyncio.sleep(24 * 60 * 60)


# Startup Seed Logic
@app.on_event("startup")
async def startup_event():
    from .database import SessionLocal, engine
    from . import models
    from .utils.password import hash_password

    settings.validate_production_settings()
    # Migrations and database privileges run in the migrate service, as the table owner (WP32 W5);
    # this process connects as am_user_app and never runs DDL.
    install_db_audit(SessionLocal)
    install_sql_timing(engine)

    db = SessionLocal()
    try:
        default_client = db.query(models.Client).filter(models.Client.id == 1).first()

        if settings.is_production:
            ensure_no_development_password(db)
            mfa_service.ensure_no_development_totp(db)
        else:
            # 1. Ensure Default Client exists in development only.
            if not default_client:
                print("Seeding dev user for development...")
                default_client = models.Client(
                    name="dev",
                    username="dev",
                    password_hash=hash_password("adminadmin"),
                    general_settings={}
                )
                db.add(default_client)
                db.commit()
                db.refresh(default_client)

                # The sequence assigns the id (1 in a fresh database); forcing id=1 would need
                # setval, which the application role may not run (WP32 W5).
            if default_client.username == "dev":
                mfa_service.ensure_development_mfa(db, default_client)

    finally:
        db.close()

    global _automatic_recording_task
    _automatic_recording_task = asyncio.create_task(run_automatic_recording_loop())


@app.on_event("shutdown")
async def shutdown_event() -> None:
    global _automatic_recording_task
    if _automatic_recording_task:
        _automatic_recording_task.cancel()
        try:
            await _automatic_recording_task
        except asyncio.CancelledError:
            pass
        _automatic_recording_task = None

# Innermost: scopes and audits every MCP request (WP34). It reads the request
# context, so it must sit inside RequestLogMiddleware, which binds it.
app.add_middleware(AiOperationAuditMiddleware)
# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Added last so it is outermost: it times the whole request, CORS included.
app.add_middleware(RequestLogMiddleware)

# Include routers
app.include_router(analysis.router)
app.include_router(transactions.router)
app.include_router(transaction_batches.router)
app.include_router(products.router)
app.include_router(automatic_recordings.router)
app.include_router(depreciations.router)
app.include_router(plan_reflection.router)
app.include_router(plan.router)
app.include_router(registry_entries.router, dependencies=[Depends(get_current_client)])
app.include_router(life_events.router)
app.include_router(life_scenarios.router)
app.include_router(goal_budget.router)
app.include_router(notifications.router)
app.include_router(household_members.router)
app.include_router(budget_plans.router, dependencies=[Depends(get_current_client)])
app.include_router(period_reviews.router)
app.include_router(simulation.router)
app.include_router(accounts.router)
app.include_router(ai_operations.router)
app.include_router(ai_change_requests.router)
app.include_router(clients.router)
app.include_router(data_transfer.router)
app.include_router(auth.router)
app.include_router(mcp_oauth.router)
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
    """Liveness: the process answers. Deliberately does not touch the database,
    because restarting this container does not repair a database outage."""
    return {"status": "healthy"}


@app.get("/health/ready")
def readiness_check(db: Session = Depends(get_db)):
    """Readiness: a request arriving now could be served. Through get_db, the
    same path a request takes to the database."""
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        logger.exception("readiness check failed")
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ready"}
