"""A brand-new client has no default budget plan yet; that is not a data problem until it has plan lines."""
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base
from app.services import data_health_service as health


@pytest.fixture
def db():
    engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False) as session:
        session.add(models.Client(id=1, name="new", general_settings={"language": "ja", "currency": "JPY"}))
        session.commit()
        yield session
    engine.dispose()


def default_plan_issue(db):
    return next(issue for issue in health.check_data_health(db, 1)["issues"] if issue["code"] == "budget_plan_defaults")


def test_new_client_without_plan_lines_has_no_default_plan_issue(db):
    issue = default_plan_issue(db)
    assert issue["count"] == 0
    assert issue["items"] == []


def test_plan_lines_without_a_default_plan_are_reported(db):
    db.add(models.MonthlyPlanLine(client_id=1, target_period="2026-10", line_type="income", name="Salary",
                                  amount_minor=100, identity_key=""))
    db.commit()
    issue = default_plan_issue(db)
    assert {"problem": "missing_default_plan", "repairable": True} in issue["items"]
    assert issue["count"] >= 1
