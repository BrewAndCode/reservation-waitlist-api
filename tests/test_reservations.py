from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db


# Create an isolated in-memory database for testing
TEST_DATABASE_URL = "sqlite://"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def override_get_db():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)




def test_create_reservation():
    future_time = (
        datetime.now() + timedelta(days=2)
    ).replace(microsecond=0)

    payload = {
        "customer_name": "Mehul",
        "email": "mehul.test@example.com",
        "party_size": 2,
        "reservation_time": future_time.isoformat(),
    }

    response = client.post(
    "/reservations",
    json=payload,
    headers={"Idempotency-Key": "test-create-1"}
)

    assert response.status_code == 201

    data = response.json()

    assert data["customer_name"] == "Mehul"
    assert data["party_size"] == 2
    assert data["status"] == "confirmed"

def create_test_reservation():
    """Helper function to create a reservation for tests."""

    future_time = (
        datetime.now(timezone.utc) + timedelta(days=2)
    ).replace(microsecond=0)

    payload = {
        "customer_name": "Mehul",
        "email": "mehul.test@example.com",
        "party_size": 2,
        "reservation_time": future_time.isoformat(),
    }

    response = client.post(
        "/reservations",
        json=payload,
        headers={"Idempotency-Key": "test-helper-1"}
    )

    assert response.status_code == 201, response.text

    return response.json()

    
def test_idempotency_same_key_same_payload():
    future_time = (
        datetime.now() + timedelta(days=2)
    ).replace(microsecond=0)

    payload = {
        "customer_name": "Mehul",
        "email": "mehul.test@example.com",
        "party_size": 2,
        "reservation_time": future_time.isoformat(),
    }

    headers = {"Idempotency-Key": "same-key-001"}

    first = client.post("/reservations", json=payload, headers=headers)
    second = client.post("/reservations", json=payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

def test_cancel_reservation():
    reservation = create_test_reservation()
    reservation_id = reservation["id"]

    response = client.patch(
        f"/reservations/{reservation_id}/cancel"
    )
   

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_cancel_already_cancelled_reservation():
    reservation = create_test_reservation()
    reservation_id = reservation["id"]

    first_response = client.patch(
        f"/reservations/{reservation_id}/cancel"
    )
    print("FIRST CANCEL:", first_response.status_code, first_response.json())

    assert first_response.status_code == 200

    second_response = client.patch(
        f"/reservations/{reservation_id}/cancel"
    )
    print("SECOND CANCEL:", second_response.status_code, second_response.json())

    assert second_response.status_code == 400


def test_cancel_nonexistent_reservation():
    response = client.patch("/reservations/99999/cancel")

    assert response.status_code == 404


def test_cancelled_status_persists_in_database():
    reservation = create_test_reservation()
    reservation_id = reservation["id"]

    cancel_response = client.patch(
        f"/reservations/{reservation_id}/cancel"
    )

    assert cancel_response.status_code == 200

    get_response = client.get(
        f"/reservations/{reservation_id}"
    )

    assert get_response.status_code == 200
    assert get_response.json()["status"] == "cancelled"
def test_booking_within_capacity_is_confirmed():
    future_time = (
        datetime.now(timezone.utc) + timedelta(days=2)
    ).replace(microsecond=0)

    payload = {
        "customer_name": "Mehul",
        "email": "mehul.test@example.com",
        "party_size": 5,
        "reservation_time": future_time.isoformat(),
    }

    response = client.post(
        "/reservations",
        json=payload,
        headers={"Idempotency-Key": "capacity-test-1"},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "confirmed"

def test_booking_when_capacity_full_goes_to_waitlist():
    future_time = (
        datetime.now(timezone.utc) + timedelta(days=2)
    ).replace(microsecond=0)

    def book(name, size, key):
        return client.post(
            "/reservations",
            json={
                "customer_name": name,
                "email": f"{name.lower()}@example.com",
                "party_size": size,
                "reservation_time": future_time.isoformat(),
            },
            headers={"Idempotency-Key": key},
        )

    first = book("Mehul", 3, "capacity-test-2a")
    second = book("Rahul", 2, "capacity-test-2b")
    third = book("Aman", 1, "capacity-test-2c")

    assert first.json()["status"] == "confirmed"
    assert second.json()["status"] == "confirmed"
    assert third.json()["status"] == "waitlisted"

def test_waitlist_promotion_after_cancellation():
    future_time = (
        datetime.now(timezone.utc) + timedelta(days=2)
    ).replace(microsecond=0)

    def book(name, size, key):
        return client.post(
            "/reservations",
            json={
                "customer_name": name,
                "email": f"{name.lower()}@example.com",
                "party_size": size,
                "reservation_time": future_time.isoformat(),
            },
            headers={"Idempotency-Key": key},
        ).json()

    first = book("Mehul", 3, "promotion-test-1")
    second = book("Rahul", 2, "promotion-test-2")
    third = book("Aman", 2, "promotion-test-3")

    assert third["status"] == "waitlisted"

    response = client.patch(
        f"/reservations/{second['id']}/cancel"
    )

    assert response.status_code == 200

    promoted = client.get(
        f"/reservations/{third['id']}"
    )

    assert promoted.json()["status"] == "confirmed"

def test_get_waitlist():
    future_time = (
        datetime.now(timezone.utc) + timedelta(days=2)
    ).replace(microsecond=0)

    def book(name, size, key):
        return client.post(
            "/reservations",
            json={
                "customer_name": name,
                "email": f"{name.lower()}@example.com",
                "party_size": size,
                "reservation_time": future_time.isoformat(),
            },
            headers={"Idempotency-Key": key},
        )

    book("Mehul", 5, "waitlist-api-1")
    waiting = book("Aman", 2, "waitlist-api-2")

    assert waiting.json()["status"] == "waitlisted"

    response = client.get("/waitlist")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["customer_name"] == "Aman"
