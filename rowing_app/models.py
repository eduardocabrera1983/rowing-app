"""Pydantic models for Concept2 Logbook API responses."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────
# Token
# ──────────────────────────────────────────────
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    refresh_token: str


# ──────────────────────────────────────────────
# User
# ──────────────────────────────────────────────
class User(BaseModel):
    id: int
    username: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    gender: Optional[str] = None
    dob: Optional[str] = None
    email: Optional[str] = None
    country: Optional[str] = None
    profile_image: Optional[str] = None
    age_restricted: Optional[bool] = None
    max_heart_rate: Optional[int] = None
    logbook_privacy: Optional[str] = None


class UserResponse(BaseModel):
    data: User


# ──────────────────────────────────────────────
# Heart Rate
# ──────────────────────────────────────────────
class HeartRate(BaseModel):
    average: Optional[int] = None
    min: Optional[int] = None
    max: Optional[int] = None
    ending: Optional[int] = None
    recovery: Optional[int] = None
    rest: Optional[int] = None


# ──────────────────────────────────────────────
# Workout Result
# ──────────────────────────────────────────────
class WorkoutResult(BaseModel):
    id: int
    user_id: int
    date: str
    timezone: Optional[str] = None
    date_utc: Optional[str] = None
    distance: int
    type: str  # rower, skierg, bike, dynamic, etc.
    time: int  # tenths of a second
    time_formatted: Optional[str] = None
    workout_type: Optional[str] = None
    source: Optional[str] = None
    weight_class: Optional[str] = None
    verified: Optional[bool] = None
    ranked: Optional[bool] = None
    comments: Optional[str] = None
    privacy: Optional[str] = None
    stroke_rate: Optional[int] = None
    stroke_count: Optional[int] = None
    calories_total: Optional[int] = None
    drag_factor: Optional[int] = None
    heart_rate: Optional[HeartRate] = None
    rest_time: Optional[int] = None
    rest_distance: Optional[int] = None

    @property
    def time_seconds(self) -> float:
        """Convert time from tenths of a second to seconds."""
        return self.time / 10.0

    @property
    def pace_per_500m(self) -> Optional[float]:
        """Calculate pace per 500m in seconds."""
        if self.distance and self.distance > 0:
            return (self.time_seconds / self.distance) * 500
        return None

    @property
    def date_parsed(self) -> datetime:
        """Parse date string to datetime."""
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(self.date, fmt)
            except ValueError:
                continue
        return datetime.strptime(self.date[:10], "%Y-%m-%d")


# ──────────────────────────────────────────────
# Pagination
# ──────────────────────────────────────────────
class PaginationLinks(BaseModel):
    next: Optional[str] = None
    prev: Optional[str] = None


class Pagination(BaseModel):
    total: int
    count: int
    per_page: int
    current_page: int
    total_pages: int
    links: Optional[PaginationLinks | list] = None


class PaginationMeta(BaseModel):
    pagination: Pagination


class ResultsResponse(BaseModel):
    data: list[WorkoutResult]
    meta: Optional[PaginationMeta] = None


class SingleResultResponse(BaseModel):
    data: WorkoutResult


# ──────────────────────────────────────────────
# Stroke Data
# ──────────────────────────────────────────────
class StrokeDataPoint(BaseModel):
    t: Optional[int] = None  # time
    d: Optional[int] = None  # distance
    p: Optional[int] = None  # pace
    spm: Optional[int] = None  # strokes per minute
    hr: Optional[int] = None  # heart rate


class StrokeDataResponse(BaseModel):
    data: list[StrokeDataPoint]
