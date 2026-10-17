from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app import models
from backend.app.database import Base
from backend.app.services.client_settings_service import merge_general_settings


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()





def test_merge_general_settings_preserves_existing_keys_and_returns_merged_dict(db):
    client = models.Client(
        id=1, name="test",
        general_settings={"currency": "JPY", "language": "ja", "ai_operation": {"mcp_write_mode": "change_request"}},
    )
    db.add(client)
    db.commit()

    merged = merge_general_settings(db, client, {"currency": "USD", "theme": "dark"})
    expected = {
        "currency": "USD", "language": "ja", "theme": "dark",
        "ai_operation": {"mcp_write_mode": "change_request"},
    }
    assert merged == expected
    db.expire_all()
    saved = db.get(models.Client, client.id)
    assert saved.general_settings == expected
