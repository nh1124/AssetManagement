"""A month can be closed only once it has ended, in the client's own time zone."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base
from app.domain.errors import Invalid
from app.services import period_close_service as service

# 2026-10-31 20:00 UTC is already 2026-11-01 in Tokyo.
NOW = datetime(2026, 10, 31, 20, 0, tzinfo=timezone.utc)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as session:
        session.add_all([models.Client(id=1, name="東京", general_settings={"timezone": "Asia/Tokyo"}),
                         models.Client(id=2, name="設定なし", general_settings={})])
        session.commit()
        yield session
    engine.dispose()


@pytest.mark.parametrize("client_id, period", [(1, "2026-11"), (1, "2027-01"), (2, "2026-10")])
def test_the_running_month_and_later_cannot_be_closed(db, client_id, period):
    with pytest.raises(Invalid):
        service.close_period(db, client_id, period, now=NOW)
    assert not service.is_closed(db, client_id, period)


def test_a_finished_month_closes_in_the_clients_time_zone(db):
    # October has ended in Tokyo, though not yet in UTC.
    service.close_period(db, 1, "2026-10", now=NOW)
    assert service.is_closed(db, 1, "2026-10")
