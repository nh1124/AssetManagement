"""Shared fixtures for goal and scenario tests: a three-client database, accounts, an HTTP helper."""
import asyncio
from datetime import date

import httpx
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base
from app.services.ledger_service import create_account, create_transaction


def goal_scenario_id(db, client_id):
    db.flush()
    scenario = db.query(models.LifeScenario).filter_by(client_id=client_id, is_goal=True).first()
    if scenario is None:
        scenario = models.LifeScenario(client_id=client_id, name="基本シナリオ", is_goal=True)
        db.add(scenario)
        db.flush()
    return scenario.id


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as session:
        session.add_all([models.Client(id=1, name="本人", general_settings={"currency": "JPY"}),
                         models.Client(id=2, name="別人", general_settings={"currency": "JPY"}),
                         models.Client(id=3, name="空", general_settings={"currency": "JPY"})])
        session.commit()
        yield session
    engine.dispose()


def account(db, name="口座", client_id=1, kind="asset", balance=0):
    row = create_account(db, client_id, {"name": name, "account_type": kind})
    if balance:
        income = create_account(db, client_id, {"name": name + "給与", "account_type": "income"})
        create_transaction(db, client_id=client_id, date=date(2020, 1, 1), description="開始残高",
                           amount_minor=balance, currency="JPY", from_account_id=income.id, to_account_id=row.id)
        db.commit()
    return row


def request(app, method, url, **kwargs):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            pending = asyncio.create_task(client.request(method, url, **kwargs))
            # Timers wake the sandbox selector for sync HTTP handlers.
            for _ in range(3000):
                if pending.done():
                    return await pending
                await asyncio.sleep(.01)
            pending.cancel()
            pytest.fail("HTTP scenario request timed out")
    return asyncio.run(run())
