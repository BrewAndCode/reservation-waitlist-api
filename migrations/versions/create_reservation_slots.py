"""create reservation slots table

Revision ID: d123456789ab
Revises: b6eedcfab159
"""

from alembic import op
import sqlalchemy as sa


revision = "d123456789ab"
down_revision = "b6eedcfab159"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reservation_slots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "slot_time",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "capacity >= 1",
            name="check_slot_capacity",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_reservation_slots_slot_time",
        "reservation_slots",
        ["slot_time"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reservation_slots_slot_time",
        table_name="reservation_slots",
    )
    op.drop_table("reservation_slots")