"""A client has one budget plan (§8-10): the extra plans and their rows go.

Alternative budget plans were an old-UI feature no screen reaches any more. Each
client keeps its default plan -- or, when none is marked default, its first plan by
sort order and id, which becomes the default -- and every other plan is deleted
with the monthly plan lines it holds. Earmarks keep their monthly amounts: they
are the user's settings, and which plan last summed into them is not recorded.

Revision ID: 20261021_0084
Revises: 20261021_0083
"""
from alembic import op

revision = "20261021_0084"
down_revision = "20261021_0083"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    plans = bind.exec_driver_sql(
        "SELECT id, client_id, is_default FROM budget_plans ORDER BY client_id, sort_order, id").all()
    keep: dict[int, int] = {}
    for plan_id, client_id, is_default in plans:
        if client_id not in keep or (is_default and not _is_default(plans, keep[client_id])):
            keep[client_id] = plan_id
    extra = [plan_id for plan_id, _, _ in plans if plan_id not in keep.values()]
    for plan_id in keep.values():
        bind.exec_driver_sql("UPDATE budget_plans SET is_default = TRUE WHERE id = %s" % int(plan_id))
    if extra:
        ids = ", ".join(str(int(plan_id)) for plan_id in extra)
        bind.exec_driver_sql(f"DELETE FROM monthly_plan_lines WHERE plan_id IN ({ids})")
        bind.exec_driver_sql(f"DELETE FROM budget_plans WHERE id IN ({ids})")


def _is_default(plans, plan_id: int) -> bool:
    return next(bool(is_default) for pid, _, is_default in plans if pid == plan_id)


def downgrade():
    # The deleted plans and rows are gone; restore them from the pre-migration backup.
    pass
