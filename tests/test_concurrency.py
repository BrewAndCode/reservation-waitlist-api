
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from dotenv import load_dotenv
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models import Reservation

load_dotenv()

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

if not TEST_DATABASE_URL:
    raise ValueError("TEST_DATABASE_URL is not configured")

test_engine = create_engine(
    TEST_DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=10,
)

TestSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=test_engine,
)


def override_test_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_concurrent_bookings_do_not_exceed_capacity():
    # Create tables in the dedicated test database.
    Base.metadata.create_all(bind=test_engine)

    future_time = (
        datetime.now(timezone.utc) + timedelta(days=10)
    ).replace(microsecond=0)

    def book_customer(name):
        with TestClient(app) as client:
            response = client.post(
                "/reservations",
                json={
                    "customer_name": name,
                    "email": f"{name.lower()}@example.com",
                    "party_size": 2,
                    "reservation_time": future_time.isoformat(),
                },
                headers={"Idempotency-Key": str(uuid4())},
            )

        assert response.status_code == 201, response.text
        return response.json()

    original_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_test_db

    try:
        # Send five simultaneous requests.
        with ThreadPoolExecutor(max_workers=5) as executor:
            results = list(
                executor.map(
                    book_customer,
                    ["Aman", "Rahul", "Mehul", "Rohan", "Karan"],
                )
            )

        confirmed_people = sum(
            item["party_size"]
            for item in results
            if item["status"] == "confirmed"
        )

        waitlisted_count = sum(
            1 for item in results
            if item["status"] == "waitlisted"
        )

        # Two-seat groups cannot be split.
        assert confirmed_people == 4
        assert waitlisted_count == 3

        # Verify the actual PostgreSQL data.
        with TestSessionLocal() as db:
            database_confirmed_people = (
                db.query(
                    func.coalesce(func.sum(Reservation.party_size), 0)
                )
                .filter(
                    Reservation.reservation_time == future_time,
                    Reservation.status == "confirmed",
                )
                .scalar()
            )

        assert database_confirmed_people == 4

    finally:
        if original_override is not None:
            app.dependency_overrides[get_db] = original_override
        else:
            app.dependency_overrides.pop(get_db, None)

def test_concurrent_cancellation_happens_only_once():
    Base.metadata.create_all(bind=test_engine)

    future_time = (
        datetime.now(timezone.utc) + timedelta(days=15)
    ).replace(microsecond=0)

    original_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_test_db

    try:
        # First create a confirmed reservation.
        with TestClient(app) as client:
            booking_response = client.post(
                "/reservations",
                json={
                    "customer_name": "Cancellation Test",
                    "email": "cancel.test@example.com",
                    "party_size": 1,
                    "reservation_time": future_time.isoformat(),
                },
                headers={"Idempotency-Key": str(uuid4())},
            )

        assert booking_response.status_code == 201, booking_response.text

        reservation_id = booking_response.json()["id"]

        # Two requests attempt to cancel the same reservation.
        def cancel_booking():
            with TestClient(app) as client:
                return client.patch(
                    f"/reservations/{reservation_id}/cancel"
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(
                executor.map(
                    lambda _: cancel_booking(),
                    range(2),
                )
            )

        status_codes = sorted(
            response.status_code for response in responses
        )

        # One cancellation succeeds; the other is rejected.
        assert status_codes == [200, 400]

        # Verify the final database state.
        with TestSessionLocal() as db:
            reservation = (
                db.query(Reservation)
                .filter(Reservation.id == reservation_id)
                .first()
            )

            assert reservation.status == "cancelled"

    finally:
        if original_override is not None:
            app.dependency_overrides[get_db] = original_override
        else:
            app.dependency_overrides.pop(get_db, None)

