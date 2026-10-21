"""Write 物品の取り置き's plan rows after the user confirmed the exact preview (§8-4).

The computation is product_reserve_plan's; apply recomputes it and refuses when the
fingerprint differs, so a change between preview and apply is shown again.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..domain.errors import Conflict
from ..services.budget_plan_store import (
    create_plan_lines,
    find_budget_plan_id,
    resolve_budget_plan_id,
    retire_plan_lines,
    update_plan_lines,
)
from ..services.cache_service import invalidate_client
from ..services.life_scenario_scope import lock_client
from ..services.product_reserve_plan import SOURCE, plan


def preview(db: Session, client_id: int, start_period: str, end_period: str, base: str, held: str) -> dict:
    """Everything making the plan would write; nothing is saved."""
    return plan(db, client_id, start_period, end_period, find_budget_plan_id(db, client_id), base, held)


def apply(db: Session, client_id: int, start_period: str, end_period: str, base: str, held: str, fingerprint: str) -> dict:
    lock_client(db, client_id)
    try:
        existing_plan = find_budget_plan_id(db, client_id)
        planned = plan(db, client_id, start_period, end_period, existing_plan, base, held)
        if planned["fingerprint"] != fingerprint:
            raise Conflict("取り置きか計画の内容が確認後に変わりました。もう一度確認してください。")
        plan_id = existing_plan if existing_plan is not None else resolve_budget_plan_id(db, client_id, commit=False)
        changed = [change for change in planned["changes"] if change["changed"]]
        retires = [change["line_id"] for change in changed if change["retire"]]
        updates = [{"id": change["line_id"], "amount": change["new"], "manual_override": False}
                   for change in changed if not change["retire"] and change["line_id"] is not None]
        creates = [{"plan_id": plan_id, "target_period": change["period"], "line_type": "allocation", "target_type": "capsule",
                    "target_id": change["capsule_id"], "account_id": change["account_id"], "amount": change["new"],
                    "source": SOURCE, "source_kind": SOURCE, "cash_treatment": "auto"}
                   for change in changed if not change["retire"] and change["line_id"] is None]
        try:
            # Retire first so a replacement row never meets the row it replaces.
            if retires:
                retire_plan_lines(db, client_id, retires, commit=False)
            if updates:
                update_plan_lines(db, client_id, updates, commit=False)
            if creates:
                create_plan_lines(db, client_id, creates, commit=False)
        except ValueError as exc:
            raise Conflict(f"計画の行を書き込めませんでした：{exc}") from exc
        db.commit()
    except Exception:
        db.rollback()
        raise
    invalidate_client(client_id)
    return {"applied": len(changed), "periods": planned["periods"], "currency": planned["currency"]}
