"""Concept2 Logbook API client with pagination, retries, and error handling."""

from __future__ import annotations

from typing import Optional

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import settings
from .models import (
    ResultsResponse,
    SingleResultResponse,
    StrokeDataResponse,
    UserResponse,
    WorkoutResult,
)


class Concept2Client:
    """Async client for the Concept2 Logbook API."""

    def __init__(self, access_token: str):
        self.access_token = access_token
        self.base_url = settings.c2_api_url
        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": f"application/vnd.c2logbook.{settings.c2_api_version}+json",
        }

    # ──────────────────────────────────────────
    # User
    # ──────────────────────────────────────────
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def get_user(self, user: str = "me") -> UserResponse:
        """Get user profile. Pass 'me' for authenticated user or an int id."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/users/{user}",
                headers=self._headers,
            )
            resp.raise_for_status()
            return UserResponse(**resp.json())

    # ──────────────────────────────────────────
    # Results (workouts)
    # ──────────────────────────────────────────
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def get_results(
        self,
        user: str = "me",
        page: int = 1,
        per_page: int = 50,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        workout_type: Optional[str] = None,
        updated_after: Optional[str] = None,
    ) -> ResultsResponse:
        """Fetch a page of workout results with optional filters.

        Args:
            user:           'me' or user ID
            page:           Page number (1-based)
            per_page:       Results per page (max 250)
            from_date:      YYYY-MM-DD filter (inclusive start)
            to_date:        YYYY-MM-DD filter (inclusive end)
            workout_type:   rower | skierg | bike | dynamic | etc.
            updated_after:  YYYY-MM-DD, only results updated on/after this
        """
        params: dict = {"page": page, "number": min(per_page, 250)}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        if workout_type:
            params["type"] = workout_type
        if updated_after:
            params["updated_after"] = updated_after

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/users/{user}/results",
                headers=self._headers,
                params=params,
            )
            resp.raise_for_status()
            return ResultsResponse(**resp.json())

    async def get_all_results(
        self,
        user: str = "me",
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        workout_type: Optional[str] = None,
    ) -> list[WorkoutResult]:
        """Fetch ALL workout results, automatically handling pagination."""
        all_results: list[WorkoutResult] = []
        page = 1

        while True:
            response = await self.get_results(
                user=user,
                page=page,
                per_page=250,
                from_date=from_date,
                to_date=to_date,
                workout_type=workout_type,
            )
            all_results.extend(response.data)
            logger.info(
                f"Fetched page {page}/{response.meta.pagination.total_pages if response.meta else '?'} "
                f"({len(all_results)} results so far)"
            )

            if response.meta and page < response.meta.pagination.total_pages:
                page += 1
            else:
                break

        logger.success(f"Total results fetched: {len(all_results)}")
        return all_results

    # ──────────────────────────────────────────
    # Single Result
    # ──────────────────────────────────────────
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def get_result(
        self, result_id: int, user: str = "me"
    ) -> SingleResultResponse:
        """Get a single workout result by ID."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/users/{user}/results/{result_id}",
                headers=self._headers,
            )
            resp.raise_for_status()
            return SingleResultResponse(**resp.json())

    # ──────────────────────────────────────────
    # Stroke Data
    # ──────────────────────────────────────────
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def get_stroke_data(
        self, result_id: int, user: str = "me"
    ) -> StrokeDataResponse:
        """Get stroke-level data for a workout."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/users/{user}/results/{result_id}/strokes",
                headers=self._headers,
            )
            resp.raise_for_status()
            return StrokeDataResponse(**resp.json())

    # ──────────────────────────────────────────
    # File export
    # ──────────────────────────────────────────
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def export_result(
        self,
        result_id: int,
        file_type: str = "csv",
        user: str = "me",
    ) -> bytes:
        """Download a workout export (csv, fit, or tcx)."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/users/{user}/results/{result_id}/export/{file_type}",
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.content
