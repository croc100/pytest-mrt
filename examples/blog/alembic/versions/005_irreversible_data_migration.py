"""uppercase all usernames — DANGEROUS: no reverse

Revision ID: 005
Revises: 004

⚠  This migration intentionally demonstrates another dangerous pattern.
   The data transformation (uppercasing usernames) has no reverse —
   once applied, original casing is permanently lost.
"""
revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None

from alembic import op


def upgrade() -> None:
    # ✗ BAD: one-way transformation — original data cannot be recovered
    op.execute("UPDATE users SET username = UPPER(username)")


def downgrade() -> None:
    # Structural rollback is possible but data is already gone
    pass
