"""add bio column to users — safe migration

Revision ID: 003
Revises: 002
"""
revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None

import sqlalchemy as sa
from alembic import op


def upgrade() -> None:
    # Safe: nullable column, proper downgrade
    op.add_column("users", sa.Column("bio", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("users", "bio")
