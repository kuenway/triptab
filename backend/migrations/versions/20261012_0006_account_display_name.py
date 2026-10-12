"""Allow an absent account display name without inventing identity.

Revision ID: 20261012_0006
Revises: 20261011_0005
"""

import sqlalchemy as sa
from alembic import op

revision = "20261012_0006"
down_revision = "20261011_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("users", "display_name", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    # Never synthesize names or discard accounts to satisfy the previous schema.
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM users WHERE display_name IS NULL)")
    ):
        raise RuntimeError("Cannot downgrade while account display names are null")
    op.alter_column("users", "display_name", existing_type=sa.Text(), nullable=False)
