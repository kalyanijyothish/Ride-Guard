from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    name: str = Field(min_length=1, max_length=120)
    role: Literal["passenger", "driver"] = "passenger"


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class GoogleIn(BaseModel):
    id_token: str
    role: Literal["passenger", "driver"] = "passenger"


class UserOut(ORM):
    id: int
    email: str
    name: str
    role: str
    is_active: bool
    risk_score: float
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class RideCreate(BaseModel):
    pickup_lat: float = Field(ge=-90, le=90)
    pickup_lng: float = Field(ge=-180, le=180)
    drop_lat: float = Field(ge=-90, le=90)
    drop_lng: float = Field(ge=-180, le=180)


class RideOut(ORM):
    id: int
    passenger_id: int
    driver_id: int | None
    status: str
    pickup_lat: float
    pickup_lng: float
    drop_lat: float
    drop_lng: float
    est_distance_km: float
    est_duration_min: float
    est_fare: float
    route_source: str
    actual_distance_km: float | None
    actual_duration_min: float | None
    fare: float | None
    requested_at: datetime
    accepted_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    cancelled_by_id: int | None
    fraud_score: float
    flagged: bool


class LocationIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    speed_kmh: float | None = Field(default=None, ge=0, le=400)
    accuracy_m: float | None = Field(default=None, ge=0)
    timestamp: datetime | None = None


class CancelIn(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class GpsPointOut(ORM):
    id: int
    lat: float
    lng: float
    speed_kmh: float | None
    accuracy_m: float | None
    ts: datetime


class AlertOut(ORM):
    id: int
    type: str
    severity: str
    title: str
    message: str
    ride_id: int | None
    user_id: int | None
    details: dict | None
    status: str
    created_at: datetime
    resolved_at: datetime | None
