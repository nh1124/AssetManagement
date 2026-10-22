import asyncio
import logging
from datetime import date

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException
from . import models
from .config import settings
from .database import get_db
from .dependencies import request_language
from .domain.errors import DomainError, detail_for, status_for
from .domain.messages import Message, localize
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
    period_reviews,
    period_closes,
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
from .utils.observability import (
    RequestLogMiddleware,
    install_db_audit,
    install_sql_timing,
    setup_logging,
)
from .utils.password import verify_password


setup_logging()
logger = logging.getLogger(__name__)
_automatic_recording_task: asyncio.Task | None = None

app = FastAPI(
    title="Finance IDE API",
    version="4.0.0",
    description="SaaS Refactor - Multi-Client Finance Management"
)


# WP29: an error's text follows the language the screen asked for (Accept-Language);
# a request that names no language gets every message as written, as before.
@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError):
    # Reuse FastAPI's serializer so bytes, headers and bodyless codes agree.
    return await http_exception_handler(
        request,
        HTTPException(status_code=status_for(exc), detail=detail_for(exc, request_language(request))),
    )


@app.exception_handler(StarletteHTTPException)
async def localized_http_exception_handler(request: Request, exc: StarletteHTTPException):
    language = request_language(request)
    if language is not None:
        exc = StarletteHTTPException(exc.status_code, detail=localize(exc.detail, language), headers=exc.headers)
    return await http_exception_handler(request, exc)


@app.exception_handler(RequestValidationError)
async def localized_validation_error_handler(request: Request, exc: RequestValidationError):
    # A schema validator's own Message replaces pydantic's "Value error, …" line;
    # pydantic's built-in messages (missing field, wrong type) stay as pydantic writes them.
    language = request_language(request)
    if language is not None:
        errors = []
        for error in exc.errors():
            cause = (error.get("ctx") or {}).get("error")
            text = cause.args[0] if isinstance(cause, ValueError) and len(cause.args) == 1 else None
            errors.append({**error, "msg": text.in_language(language)} if isinstance(text, Message) else error)
        exc = RequestValidationError(errors, body=exc.body)
    return await request_validation_exception_handler(request, exc)


def ensure_runtime_schema_guards(db) -> None:
    """Patch critical additive columns when a hot-reloaded app outruns Alembic."""
    dialect = db.bind.dialect.name if db.bind is not None else ""
    if dialect == "postgresql":
        db.execute(text("ALTER TABLE monthly_plan_lines ADD COLUMN IF NOT EXISTS source_kind VARCHAR NOT NULL DEFAULT 'manual'"))
        db.execute(text("ALTER TABLE monthly_plan_lines ADD COLUMN IF NOT EXISTS identity_key VARCHAR NOT NULL DEFAULT ''"))
        db.execute(text("ALTER TABLE monthly_plan_lines ADD COLUMN IF NOT EXISTS manual_override BOOLEAN NOT NULL DEFAULT false"))
        db.execute(text("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS liability_closing_day INTEGER"))
        db.execute(text("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS liability_payment_day INTEGER"))
        db.execute(text("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS liability_payment_month_offset INTEGER NOT NULL DEFAULT 0"))
        db.execute(text("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS liability_payment_policy VARCHAR NOT NULL DEFAULT 'full'"))
        db.execute(text("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS liability_minimum_payment_minor BIGINT"))
        db.execute(text("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS liability_fixed_payment_amount_minor BIGINT"))
        db.execute(text("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS liability_installment_months INTEGER"))
        db.execute(text("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS liability_revolving_rate DOUBLE PRECISION"))
        db.execute(text(
            """
            CREATE TABLE IF NOT EXISTS ai_change_requests (
                id SERIAL PRIMARY KEY,
                client_id INTEGER NOT NULL REFERENCES clients(id),
                created_by_client_id INTEGER REFERENCES clients(id),
                ai_client_id INTEGER REFERENCES clients(id),
                mcp_client_id VARCHAR,
                source VARCHAR NOT NULL,
                tool_name VARCHAR,
                resource VARCHAR NOT NULL,
                action VARCHAR NOT NULL,
                risk VARCHAR NOT NULL,
                status VARCHAR NOT NULL DEFAULT 'pending',
                target_ref JSON NOT NULL,
                input_payload JSON NOT NULL,
                before_snapshot JSON NOT NULL,
                after_snapshot JSON NOT NULL,
                diff JSON NOT NULL,
                validation JSON NOT NULL,
                idempotency_key VARCHAR NOT NULL,
                precondition_hash VARCHAR,
                requires_mfa BOOLEAN NOT NULL DEFAULT false,
                approved_by_client_id INTEGER REFERENCES clients(id),
                approved_at TIMESTAMP,
                applied_at TIMESTAMP,
                expires_at TIMESTAMP,
                result JSON NOT NULL,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                CONSTRAINT _client_ai_change_request_idempotency_uc UNIQUE (client_id, idempotency_key)
            )
            """
        ))
        db.execute(text("CREATE INDEX IF NOT EXISTS ix_ai_change_requests_client_id ON ai_change_requests (client_id)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS ix_ai_change_requests_status ON ai_change_requests (status)"))
        db.execute(text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_monthly_plan_lines_active_identity
            ON monthly_plan_lines (client_id, identity_key)
            WHERE is_active = true AND identity_key <> ''
            """
        ))
        db.commit()


def ensure_no_default_admin_password(db) -> None:
    admin_client = db.query(models.Client).filter(
        models.Client.username == "admin",
        models.Client.is_active.is_(True),
    ).first()
    if admin_client and verify_password("adminadmin", admin_client.password_hash or ""):
        raise RuntimeError("Invalid production configuration: default admin password is still active")


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
    # Migrations run once, in the container's start command (alembic upgrade head) before uvicorn (§8-9).
    install_db_audit(SessionLocal)
    install_sql_timing(engine)

    db = SessionLocal()
    try:
        ensure_runtime_schema_guards(db)
        default_client = db.query(models.Client).filter(models.Client.id == 1).first()

        if settings.is_production:
            ensure_no_default_admin_password(db)
        else:
            # 1. Ensure Default Client exists in development only.
            if not default_client:
                print("Seeding default admin user for development...")
                default_client = models.Client(
                    id=1,
                    name="Default User",
                    username="admin",
                    password_hash=hash_password("adminadmin"),
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
                # Ensure admin has valid credentials in development only.
                if not default_client.username or not default_client.password_hash:
                    default_client.username = "admin"
                    default_client.password_hash = hash_password("adminadmin")
                    db.commit()

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
app.include_router(period_closes.router)
app.include_router(simulation.router)
app.include_router(accounts.router)
app.include_router(ai_operations.router)
app.include_router(ai_change_requests.router)
app.include_router(clients.router)
app.include_router(data_transfer.router)
app.include_router(auth.router)
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
