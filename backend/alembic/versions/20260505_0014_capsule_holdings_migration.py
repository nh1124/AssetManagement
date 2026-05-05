"""capsule holdings data migration

Revision ID: 20260505_0014
Revises: 20260505_0013
Create Date: 2026-05-05
"""
from alembic import op
import sqlalchemy as sa

revision = "20260505_0014"
down_revision = "20260505_0013"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # 1. earmarked account の balance を CapsuleHolding に移行
    conn.execute(sa.text("""
        INSERT INTO capsule_holdings (capsule_id, account_id, held_amount, note, updated_at)
        SELECT
            c.id AS capsule_id,
            c.account_id AS account_id,
            a.balance AS held_amount,
            'Migrated from earmarked account' AS note,
            NOW() AS updated_at
        FROM capsules c
        JOIN accounts a ON c.account_id = a.id
        WHERE c.account_id IS NOT NULL
          AND a.balance > 0
          AND NOT EXISTS (
              SELECT 1 FROM capsule_holdings ch
              WHERE ch.capsule_id = c.id AND ch.account_id = c.account_id
          )
    """))

    # 2. Capsule.account_id を NULL に
    conn.execute(sa.text("""
        UPDATE capsules SET account_id = NULL
        WHERE account_id IS NOT NULL
    """))

    # 3. earmarked account を非アクティブ化（履歴として保持）
    conn.execute(sa.text("""
        UPDATE accounts
        SET is_active = false
        WHERE role = 'earmarked'
          AND name LIKE 'Capsule: %'
    """))


def downgrade():
    pass
