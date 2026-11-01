from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class ReservationCreate(BaseModel):
    customer_name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=15)
    party_size: int = Field(ge=1, le=20)
    reservation_time: datetime


class ReservationResponse(BaseModel):
    id: int
    customer_name: str
    email: EmailStr
    phone: str | None = Field(default=None, max_length=15)
    party_size: int
    reservation_time: datetime
    status: Literal["confirmed", "waitlisted", "cancelled"]

    model_config = {"from_attributes": True}