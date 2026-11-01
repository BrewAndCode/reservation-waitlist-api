from sqlalchemy import UniqueConstraint
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    String,
    DateTime,
    CheckConstraint,
    
    
)

from app.database import Base


class Reservation(Base):
    __tablename__ = "reservations"

    __table_args__ = (
        CheckConstraint(
            "party_size >= 1",
            name="check_reservation_party_size"
        ),
    )

    id = Column(Integer, primary_key=True)

    customer_name = Column(String(100), nullable=False)
    email = Column(String(255), nullable=False, index=True)
    phone = Column(String(15), nullable=True)

    party_size = Column(Integer, nullable=False)

    reservation_time = Column(
        DateTime(timezone=True),
        nullable=False
    )

    status = Column(
        String(20),
        default="confirmed",
        nullable=False
    )



class WaitlistEntry(Base):
    __tablename__ = "waitlist"

    __table_args__ = (
        CheckConstraint(
            "party_size >= 1",
            name="check_waitlist_party_size"
        ),
    )

    id = Column(Integer, primary_key=True)

    reservation_id = Column(
        Integer,
        ForeignKey("reservations.id"),
        unique=True,
        nullable=False
    )

    customer_name = Column(String(100), nullable=False)
    email = Column(String(255), nullable=False, index=True)
    phone = Column(String(15), nullable=True)
    party_size = Column(Integer, nullable=False)

    reservation_time = Column(
        DateTime(timezone=True),
        nullable=False
    )

    status = Column(
        String(20),
        default="waiting",
        nullable=False
    )

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )


class ReservationSlot(Base):
    __tablename__ = "reservation_slots"

    id = Column(Integer, primary_key=True)

    slot_time = Column(
        DateTime(timezone=True),
        unique=True,
        nullable=False,
        index=True
    )

    capacity = Column(
        Integer,
        default=5,
        nullable=False
    )

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "capacity >= 1",
            name="check_slot_capacity"
        ),
    )


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    id = Column(Integer, primary_key=True, index=True)

    idempotency_key = Column(
        String(255),
        unique=True,
        nullable=False
    )

    request_hash = Column(
        String(64),
        nullable=False
    )

    reservation_id = Column(
        Integer,
        ForeignKey("reservations.id"),
        nullable=False
    )

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

