"""initial schema

Revision ID: c3b9cf87e360
Revises: 
Create Date: 2026-10-31 15:26:53.578886

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3b9cf87e360'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None



def upgrade() -> None:
    op.create_table(
        "reservations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("party_size", sa.Integer(), nullable=False),
        sa.Column(
            "reservation_time",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="confirmed",
        ),
        sa.CheckConstraint(
            "party_size >= 1",
            name="check_reservation_party_size",
        ),
    )

    op.create_index(
        "ix_reservations_email",
        "reservations",
        ["email"],
    )

    op.create_table(
        "waitlist",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "reservation_id",
            sa.Integer(),
            sa.ForeignKey("reservations.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("customer_name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("party_size", sa.Integer(), nullable=False),
        sa.Column(
            "reservation_time",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="waiting",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "party_size >= 1",
            name="check_waitlist_party_size",
        ),
    )

    op.create_index(
        "ix_waitlist_email",
        "waitlist",
        ["email"],
    )

    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "idempotency_key",
            sa.String(length=255),
            nullable=False,
            unique=True,
        ),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "reservation_id",
            sa.Integer(),
            sa.ForeignKey("reservations.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("idempotency_records")
    op.drop_index("ix_waitlist_email", table_name="waitlist")
    op.drop_table("waitlist")
    op.drop_index("ix_reservations_email", table_name="reservations")
    op.drop_table("reservations")
