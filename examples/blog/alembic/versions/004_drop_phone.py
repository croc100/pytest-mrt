"""drop phone column — DANGEROUS: data loss on rollback

Revision ID: 004
Revises: 003

⚠  This migration intentionally demonstrates a dangerous pattern.
   pytest-mrt will catch this: phone numbers are permanently lost
   when this migration is applied, even though downgrade re-adds the column.
"""
revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None

import sqlalchemy as sa
from alembic import op


def upgrade() -> None:
    # ✗ BAD: existing phone numbers are gone after this
    op.drop_column("users", "phone")


def downgrade() -> None:
    # Column structure comes back, but all phone data is permanently lost
    op.add_column("users", sa.Column("phone", sa.String(20), nullable=True))
