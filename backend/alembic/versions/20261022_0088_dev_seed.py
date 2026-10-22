"""Rename the development seed account to dev, preserving user-owned identities.

Revision ID: 20261022_0088
Revises: 20261021_0087
"""
from alembic import op

revision = "20261022_0088"
down_revision = "20261021_0087"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        UPDATE clients SET username = 'dev'
        WHERE id = 1 AND username = 'admin'
        AND NOT EXISTS (SELECT 1 FROM clients WHERE username = 'dev')
    """)
    op.execute("""
        UPDATE clients SET name = 'dev'
        WHERE id = 1 AND name = 'Default User'
        AND NOT EXISTS (SELECT 1 FROM clients WHERE name = 'dev')
    """)


def downgrade():
    op.execute("""
        UPDATE clients SET username = 'admin'
        WHERE id = 1 AND username = 'dev'
        AND NOT EXISTS (SELECT 1 FROM clients WHERE username = 'admin')
    """)
    op.execute("""
        UPDATE clients SET name = 'Default User'
        WHERE id = 1 AND name = 'dev'
        AND NOT EXISTS (SELECT 1 FROM clients WHERE name = 'Default User')
    """)
