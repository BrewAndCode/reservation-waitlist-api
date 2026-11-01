
import hashlib
import json
import logging

from datetime import datetime, timezone

from fastapi import (
    FastAPI,
    HTTPException,
    status,
    Depends,
    Header,
    Query
)

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import get_db
from app.models import (
    Reservation,
    WaitlistEntry,
    ReservationSlot,
    IdempotencyRecord,
)
from app.schemas import ReservationCreate, ReservationResponse


app = FastAPI(
    title="Reservation and Waitlist API",
    description="An API for managing reservations and waitlists.",
    version="2.0.0",
)
# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)

SLOT_CAPACITY = 5


def normalize_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def get_or_create_locked_slot(
    db: Session,
    reservation_time: datetime,
):
    """
    Get or create a slot and lock its row.
    PostgreSQL provides row-level locking.
    """

    if db.bind.dialect.name == "postgresql":
        statement = (
            pg_insert(ReservationSlot)
            .values(
                slot_time=reservation_time,
                capacity=SLOT_CAPACITY,
            )
            .on_conflict_do_nothing(
                index_elements=["slot_time"]
            )
        )

        db.execute(statement)

    slot = (
        db.query(ReservationSlot)
        .filter(
            ReservationSlot.slot_time == reservation_time
        )
        .with_for_update()
        .first()
    )

    if slot is None:
        slot = ReservationSlot(
            slot_time=reservation_time,
            capacity=SLOT_CAPACITY,
        )
        db.add(slot)
        db.flush()

    return slot


def get_confirmed_people(
    db: Session,
    reservation_time: datetime,
) -> int:
    total = (
        db.query(func.coalesce(func.sum(Reservation.party_size), 0))
        .filter(
            Reservation.reservation_time == reservation_time,
            Reservation.status == "confirmed",
        )
        .scalar()
    )

    return int(total or 0)


def find_existing_idempotency_record(
    db: Session,
    key: str,
):
    return (
        db.query(IdempotencyRecord)
        .filter(IdempotencyRecord.idempotency_key == key)
        .first()
    )


def get_idempotent_reservation(
    db: Session,
    record: IdempotencyRecord,
    request_hash: str,
):
    if record.request_hash != request_hash:
        raise HTTPException(
            status_code=409,
            detail="Idempotency key reused with different request data",
        )

    reservation = (
        db.query(Reservation)
        .filter(Reservation.id == record.reservation_id)
        .first()
    )

    if reservation is None:
        raise HTTPException(
            status_code=500,
            detail="Stored reservation could not be found",
        )

    return reservation


# CREATE RESERVATION
@app.post(
    "/reservations",
    response_model=ReservationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_reservation(
    reservation: ReservationCreate,
    db: Session = Depends(get_db),
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key",
        min_length=1,
        max_length=255,
    ),
):
    reservation_time = normalize_time(
        reservation.reservation_time
    )

    if reservation_time <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=400,
            detail="Reservation time must be in the future",
        )

    payload = reservation.model_dump(mode="json")
    payload["reservation_time"] = reservation_time.isoformat()

    canonical_payload = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    )

    request_hash = hashlib.sha256(
        canonical_payload.encode("utf-8")
    ).hexdigest()

    existing_record = find_existing_idempotency_record(
        db,
        idempotency_key,
    )

    if existing_record:
        return get_idempotent_reservation(
            db,
            existing_record,
            request_hash,
        )

    try:
        # Lock this slot before checking its capacity.
        slot = get_or_create_locked_slot(
            db,
            reservation_time,
        )

        confirmed_people = get_confirmed_people(
            db,
            reservation_time,
        )

        available_people = slot.capacity - confirmed_people

        if reservation.party_size <= available_people:
            booking_status = "confirmed"
        else:
            booking_status = "waitlisted"

        db_reservation = Reservation(
            customer_name=reservation.customer_name,
            email=str(reservation.email),
            phone=reservation.phone,
            party_size=reservation.party_size,
            reservation_time=reservation_time,
            status=booking_status,
        )

        db.add(db_reservation)
        db.flush()

        # Create a waitlist entry if capacity is insufficient.
        if booking_status == "waitlisted":
            waitlist_entry = WaitlistEntry(
                reservation_id=db_reservation.id,
                customer_name=reservation.customer_name,
                email=str(reservation.email),
                phone=reservation.phone,
                party_size=reservation.party_size,
                reservation_time=reservation_time,
                status="waiting",
            )

            db.add(waitlist_entry)

        # Store idempotency record in the same transaction.
        idempotency_record = IdempotencyRecord(
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            reservation_id=db_reservation.id,
        )

        db.add(idempotency_record)

        db.commit()
        db.refresh(db_reservation)
        logger.info(
    "Reservation created | ID=%s | Status=%s | Party size=%s",
    db_reservation.id,
    db_reservation.status,
    db_reservation.party_size,
)

        return db_reservation

    except IntegrityError:
        logger.exception(
    "Database integrity error while creating reservation"
)
        db.rollback()

        existing_record = find_existing_idempotency_record(
            db,
            idempotency_key,
        )

        if existing_record:
            return get_idempotent_reservation(
                db,
                existing_record,
                request_hash,
            )

        raise HTTPException(
            status_code=500,
            detail="Could not create reservation",
        )

    except Exception:
        db.rollback()
        raise


# GET SINGLE RESERVATION
@app.get(
    "/reservations/{reservation_id}",
    response_model=ReservationResponse,
)
def get_reservation(
    reservation_id: int,
    db: Session = Depends(get_db),
):
    reservation = (
        db.query(Reservation)
        .filter(Reservation.id == reservation_id)
        .first()
    )

    if reservation is None:
        raise HTTPException(
            status_code=404,
            detail="Reservation not found",
        )

    return reservation


# GET ALL RESERVATIONS
@app.get(
    "/reservations",
    response_model=list[ReservationResponse],
)

def get_all_reservations(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    reservations = (
        db.query(Reservation)
        .order_by(Reservation.id.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return reservations



# GET WAITLIST
@app.get("/waitlist")
def get_waitlist(
    db: Session = Depends(get_db),
):
    return (
        db.query(WaitlistEntry)
        .filter(WaitlistEntry.status == "waiting")
        .order_by(
            WaitlistEntry.created_at.asc(),
            WaitlistEntry.id.asc(),
        )
        .all()
    )


# CANCEL RESERVATION AND PROMOTE WAITLIST

# CANCEL RESERVATION AND PROMOTE WAITLIST
@app.patch(
    "/reservations/{reservation_id}/cancel",
    response_model=ReservationResponse,
)
def cancel_reservation(
    reservation_id: int,
    db: Session = Depends(get_db),
):
    # First, find the reservation to identify its slot.
    reservation = (
        db.query(Reservation)
        .filter(Reservation.id == reservation_id)
        .first()
    )

    if reservation is None:
        raise HTTPException(
            status_code=404,
            detail="Reservation not found",
        )

    try:
        reservation_time = normalize_time(
            reservation.reservation_time
        )

        # Lock the slot first. All booking and cancellation
        # operations for this slot must follow this lock order.
        slot = get_or_create_locked_slot(
            db,
            reservation_time,
        )

        # Re-fetch and lock the reservation after acquiring
        # the slot lock. populate_existing refreshes stale data.
        reservation = (
            db.query(Reservation)
            .filter(Reservation.id == reservation_id)
            .with_for_update()
            .populate_existing()
            .first()
        )

        if reservation is None:
            raise HTTPException(
                status_code=404,
                detail="Reservation not found",
            )

        if reservation.status == "cancelled":
            raise HTTPException(
                status_code=400,
                detail="Reservation is already cancelled",
            )

        reservation.status = "cancelled"

        # Remove the reservation from the active waitlist
        # if it was previously waitlisted.
        cancelled_entry = (
            db.query(WaitlistEntry)
            .filter(
                WaitlistEntry.reservation_id == reservation.id,
                WaitlistEntry.status == "waiting",
            )
            .first()
        )

        if cancelled_entry:
            cancelled_entry.status = "cancelled"

        db.flush()

        # Promote the oldest waiting group if it fits.
        while True:
            confirmed_people = get_confirmed_people(
                db,
                reservation_time,
            )

            available_people = slot.capacity - confirmed_people

            next_entry = (
                db.query(WaitlistEntry)
                .filter(
                    WaitlistEntry.reservation_time == reservation_time,
                    WaitlistEntry.status == "waiting",
                )
                .order_by(
                    WaitlistEntry.created_at.asc(),
                    WaitlistEntry.id.asc(),
                )
                .first()
            )

            if next_entry is None:
                break

            # FIFO: never skip the oldest group.
            if next_entry.party_size > available_people:
                break

            waiting_reservation = (
                db.query(Reservation)
                .filter(
                    Reservation.id == next_entry.reservation_id
                )
                .first()
            )

            if (
                waiting_reservation is None
                or waiting_reservation.status != "waitlisted"
            ):
                next_entry.status = "cancelled"
                db.flush()
                continue

            waiting_reservation.status = "confirmed"
            next_entry.status = "promoted"
            logger.info(
    "Waitlist customer promoted | Reservation ID=%s | Party size=%s",
    waiting_reservation.id,
    waiting_reservation.party_size,
)

            db.flush()

        db.commit()
        db.refresh(reservation)
        logger.info(
    "Reservation cancelled | ID=%s",
    reservation.id,
)

        return reservation

    except HTTPException:
        db.rollback()
        raise

    except Exception as exc:
        logger.exception(
    "Unexpected error while cancelling reservation"
)
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Could not cancel reservation",
        ) from exc
