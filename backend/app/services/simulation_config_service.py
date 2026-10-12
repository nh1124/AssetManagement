from __future__ import annotations

from sqlalchemy.orm import Session

from .money_storage import minor_fields, money_client_currency

from .. import models, schemas


def get_config(db: Session, client_id: int) -> models.SimulationConfig | None:
    return db.query(models.SimulationConfig).filter(
        models.SimulationConfig.client_id == client_id
    ).first()


def upsert_config(
    db: Session, client_id: int, payload: schemas.SimulationConfigCreate, *, commit: bool = True,
) -> models.SimulationConfig:
    config = get_config(db, client_id)
    if config:
        for key, value in minor_fields(payload.model_dump(), money_client_currency(db, client_id), "monthly_savings").items():
            setattr(config, key, value)
    else:
        config = models.SimulationConfig(**minor_fields(payload.model_dump(), money_client_currency(db, client_id), 'monthly_savings'), client_id=client_id)
        db.add(config)

    if commit:
        db.commit()
        db.refresh(config)
    else:
        db.flush()
    return config
