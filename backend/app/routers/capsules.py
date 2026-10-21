from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import database, dependencies, models, schemas
from ..services import capsule_service
from ..services.ai_policy_service import assert_direct_ledger_write_allowed
from ..services.capsule_service import (
    capsule_to_dict,
    funding_source_to_dict,
)
from ..workflows import capsule_workflow
from .transactions import _serialize_transaction

from ..workflows import plan_reflection_workflow
router = APIRouter(
    prefix="/capsules",
    tags=["Capsules"],
    dependencies=[Depends(dependencies.get_current_client)],
)


class CapsuleContributionRequest(BaseModel):
    amount: float
    from_account_id: int
    contribution_date: Optional[date] = None


def _rule_to_dict(rule: models.CapsuleRule) -> dict:
    return {
        "id": rule.id,
        "capsule_id": rule.capsule_id,
        "capsule_name": rule.capsule.name if rule.capsule else None,
        "trigger_type": rule.trigger_type,
        "trigger_category": rule.trigger_category,
        "trigger_description": rule.trigger_description,
        "trigger_account_id": rule.trigger_account_id,
        "source_mode": rule.source_mode,
        "source_account_id": rule.source_account_id,
        "destination_account_id": rule.destination_account_id,
        "source_account_name": rule.source_account.name if rule.source_account else None,
        "amount_type": rule.amount_type,
        "amount_value": rule.amount_value,
        "is_active": rule.is_active,
        "created_at": rule.created_at,
    }


@router.get("/", response_model=List[schemas.Capsule])
def read_capsules(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    return capsule_service.list_capsule_details(db, current_client.id, skip, limit)


@router.post("/", response_model=schemas.Capsule)
def create_capsule(
    capsule: schemas.CapsuleCreate,
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    db_capsule = capsule_service.create_capsule(db, current_client.id, capsule)
    result = capsule_to_dict(db, db_capsule)
    plan_reflection_workflow.after_change(db, current_client.id)
    return result


@router.get("/{capsule_id}/funding-sources", response_model=List[schemas.CapsuleFundingSource])
def read_capsule_funding_sources(
    capsule_id: int,
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    sources = capsule_service.list_funding_sources(db, current_client.id, capsule_id)
    if sources is None:
        raise HTTPException(status_code=404, detail="Capsule not found")
    # The same serializer capsule_to_dict uses, so the plan reads identically
    # whether it arrives from here or on the capsule itself.
    return [funding_source_to_dict(source) for source in sources]


@router.put("/{capsule_id}/funding-sources", response_model=List[schemas.CapsuleFundingSource])
def set_capsule_funding_sources(
    capsule_id: int,
    payloads: List[schemas.CapsuleFundingSourceInput],
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    result = [
        funding_source_to_dict(source)
        for source in capsule_service.set_funding_sources(
            db, current_client.id, capsule_id, payloads,
        )
    ]
    plan_reflection_workflow.after_change(db, current_client.id)
    return result


@router.put("/{capsule_id}", response_model=schemas.Capsule)
def update_capsule(
    capsule_id: int,
    capsule_update: schemas.CapsuleUpdate,
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    db_capsule = capsule_service.update_capsule(db, current_client.id, capsule_id, capsule_update)
    if db_capsule is None:
        raise HTTPException(status_code=404, detail="Capsule not found")
    result = capsule_to_dict(db, db_capsule)
    plan_reflection_workflow.after_change(db, current_client.id)
    return result


@router.delete("/{capsule_id}")
def delete_capsule(
    capsule_id: int,
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    """Delete a capsule and its rules. Its account and balance are untouched.

    X7 removed the transfer_account_id this used to accept and ignore. The
    response names the account the capsule was reserving into, because that
    account is what the caller still has.
    """
    deleted = capsule_service.delete_capsule(db, current_client.id, capsule_id)
    if deleted is None:
        raise HTTPException(status_code=404, detail="Capsule not found")
    result = {"message": "Capsule deleted successfully", **asdict(deleted)}
    plan_reflection_workflow.after_change(db, current_client.id)
    return result


def _ledger_write(db: Session, client_id: int, request: Request | None) -> None:
    """Drawdowns, claim adjustments and contributions post journal legs: an AI needs the direct-write policy."""
    assert_direct_ledger_write_allowed(db, client_id, mcp_client_id=request.headers.get("x-mcp-client-id") if request else None)


@router.post("/{capsule_id}/drawdown", response_model=schemas.CapsuleDrawdownResult)
def record_capsule_drawdown(
    capsule_id: int, payload: schemas.CapsuleDrawdownRequest,
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
    request: Request = None,
):
    _ledger_write(db, current_client.id, request)
    transaction, drawdown = capsule_service.record_drawdown(
        db, current_client.id, capsule_id, **payload.model_dump(),
    )
    return {"transaction": _serialize_transaction(transaction),
            "drawdown": capsule_service.drawdown_to_dict(drawdown)}


@router.get("/{capsule_id}/drawdowns", response_model=List[schemas.CapsuleDrawdown])
def read_capsule_drawdowns(
    capsule_id: int,
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    return [capsule_service.drawdown_to_dict(row)
            for row in capsule_service.list_drawdowns(db, current_client.id, capsule_id)]


@router.post("/{capsule_id}/account-claim")
def set_capsule_account_claim(
    capsule_id: int, payload: schemas.CapsuleAccountClaimRequest,
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
    request: Request = None,
):
    _ledger_write(db, current_client.id, request)
    return capsule_workflow.set_account_claim(
        db, current_client.id, capsule_id, **payload.model_dump(),
    )


@router.post("/{capsule_id}/contribute")
def contribute_to_capsule(
    capsule_id: int,
    payload: CapsuleContributionRequest = Body(...),
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
    request: Request = None,
):
    _ledger_write(db, current_client.id, request)
    return capsule_workflow.contribute(
        db, current_client.id, capsule_id,
        amount=payload.amount, from_account_id=payload.from_account_id,
    )


@router.post("/process_contributions")
def process_monthly_contributions(
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    return {
        "message": "This endpoint is deprecated. Use CapsuleRules for automatic allocation.",
        "updated_capsules": 0,
        "total_added": 0.0,
    }



@router.get("/rules", response_model=List[schemas.CapsuleRule])
def read_capsule_rules(
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    return [_rule_to_dict(rule) for rule in capsule_service.list_rules(db, current_client.id)]


@router.post("/rules", response_model=schemas.CapsuleRule)
def create_capsule_rule(
    payload: schemas.CapsuleRuleCreate,
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    rule = capsule_service.create_rule(db, current_client.id, payload)
    return _rule_to_dict(rule)


@router.put("/rules/{rule_id}", response_model=schemas.CapsuleRule)
def update_capsule_rule(
    rule_id: int,
    payload: schemas.CapsuleRuleUpdate,
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    rule = capsule_service.update_rule(db, current_client.id, rule_id, payload)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    return _rule_to_dict(rule)


@router.delete("/rules/{rule_id}")
def delete_capsule_rule(
    rule_id: int,
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    if not capsule_service.delete_rule(db, current_client.id, rule_id):
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"message": "Rule deleted"}
