"""Account shelters are projection assumptions, never tax postings."""
from alembic import op
import sqlalchemy as sa

revision = "20261015_0064"
down_revision = "20261015_0063"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("accounts", sa.Column("institution", sa.String(), nullable=False, server_default="none"))
    op.add_column("accounts", sa.Column("withdrawable_from_age", sa.Integer(), nullable=True))
    op.create_check_constraint("ck_accounts_institution", "accounts", "institution IN ('none', 'nisa_tsumitate', 'nisa_growth', 'ideco', 'dc_corporate', 'tokutei_withholding', 'tokutei_self', 'general')")
    op.create_check_constraint("ck_accounts_withdrawable_from_age", "accounts", "withdrawable_from_age IS NULL OR withdrawable_from_age >= 0")


def downgrade():
    op.drop_constraint("ck_accounts_withdrawable_from_age", "accounts", type_="check")
    op.drop_constraint("ck_accounts_institution", "accounts", type_="check")
    op.drop_column("accounts", "withdrawable_from_age")
    op.drop_column("accounts", "institution")
