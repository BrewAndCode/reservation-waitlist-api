
import hashlib
import json

from datetime import datetime, timezone

from fastapi import (
    FastAPI,
    HTTPException,
    status,
    Depends,
    Header
)

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models import Reservation, IdempotencyRecord
from app.schemas import ReservationCreate, ReservationResponse


app = FastAPI(
    title="Reservation and Waitlist API",
    description="An API for managing reservations and waitlists.",
    version="1.0.0",
)


@app.get("/")
def root():
    return {
        "message": "Reservation and Waitlist API is running",
        "status": "healthy"
    }


# CREATE RESERVATION WITH IDEMPOTENCY
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
        max_length=255
    )
):

    # 1. Normalize reservation time
    reservation_time = reservation.reservation_time

    if reservation_time.tzinfo is None:
        reservation_time = reservation_time.replace(
            tzinfo=timezone.utc
        )

    if reservation_time <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=400,
            detail="Reservation time must be in the future"
        )

    # 2. Generate request fingerprint
    payload = reservation.model_dump(mode="json")

    payload["reservation_time"] = (
        reservation_time
        .astimezone(timezone.utc)
        .isoformat()
    )

    canonical_payload = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":")
    )

    request_hash = hashlib.sha256(
        canonical_payload.encode("utf-8")
    ).hexdigest()

    # 3. Check existing idempotency key
    existing_record = (
        db.query(IdempotencyRecord)
        .filter(
            IdempotencyRecord.idempotency_key == idempotency_key
        )
        .first()
    )

    if existing_record:

        if existing_record.request_hash != request_hash:
            raise HTTPException(
                status_code=409,
                detail="Idempotency key reused with different request data"
            )

        existing_reservation = db.query(Reservation).filter(
            Reservation.id == existing_record.reservation_id
        ).first()

        if existing_reservation is None:
            raise HTTPException(
                status_code=500,
                detail="Stored reservation could not be found"
            )

        return existing_reservation

    # 4. Create reservation
    db_reservation = Reservation(
        customer_name=reservation.customer_name,
        email=reservation.email,
        party_size=reservation.party_size,
        reservation_time=reservation_time,
        status="confirmed"
    )

    try:
        db.add(db_reservation)

        # Generate reservation ID before commit
        db.flush()

        # Create idempotency record
        idempotency_record = IdempotencyRecord(
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            reservation_id=db_reservation.id
        )

        db.add(idempotency_record)

        # Save both records atomically
        db.commit()

        db.refresh(db_reservation)

        return db_reservation

    except IntegrityError:

        db.rollback()

        # Handle concurrent request with the same key
        existing_record = (
            db.query(IdempotencyRecord)
            .filter(
                IdempotencyRecord.idempotency_key == idempotency_key
            )
            .first()
        )

        if existing_record:

            if existing_record.request_hash != request_hash:
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency key reused with different request data"
                )

            existing_reservation = db.query(Reservation).filter(
                Reservation.id == existing_record.reservation_id
            ).first()

            if existing_reservation:
                return existing_reservation

        raise HTTPException(
            status_code=500,
            detail="Could not create reservation"
        )

    except Exception:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail="Could not create reservation"
        )


# GET SINGLE RESERVATION
@app.get(
    "/reservations/{reservation_id}",
    response_model=ReservationResponse,
)
def get_reservation(
    reservation_id: int,
    db: Session = Depends(get_db)
):

    reservation = db.query(Reservation).filter(
        Reservation.id == reservation_id
    ).first()

    if reservation is None:
        raise HTTPException(
            status_code=404,
            detail="Reservation not found"
        )

    return reservation


# GET ALL RESERVATIONS
@app.get(
    "/reservations",
    response_model=list[ReservationResponse],
)
def get_all_reservations(
    db: Session = Depends(get_db)
):

    reservations = db.query(Reservation).all()

    return reservations


# CANCEL RESERVATION
@app.patch(
    "/reservations/{reservation_id}/cancel",
    response_model=ReservationResponse,
)
def cancel_reservation(
    reservation_id: int,
    db: Session = Depends(get_db)
):

    reservation = db.query(Reservation).filter(
        Reservation.id == reservation_id
    ).first()

    if reservation is None:
        raise HTTPException(
            status_code=404,
            detail="Reservation not found"
        )

    if reservation.status == "cancelled":
        raise HTTPException(
            status_code=400,
            detail="Reservation is already cancelled"
        )

    reservation.status = "cancelled"

    try:
        db.commit()
        db.refresh(reservation)

    except Exception:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail="Could not cancel reservation"
        )

    return reservation
