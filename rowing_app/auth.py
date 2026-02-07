"""OAuth2 authentication flow for Concept2 Logbook API."""

from urllib.parse import urlencode

import httpx
from loguru import logger

from .config import settings
from .models import TokenResponse


def get_authorization_url(state: str | None = None) -> str:
    """Build the Concept2 OAuth2 authorization URL.

    The user should be redirected to this URL to grant access.
    """
    params = {
        "client_id": settings.c2_client_id,
        "scope": settings.c2_scope,
        "response_type": "code",
        "redirect_uri": settings.c2_redirect_uri,
    }
    if state:
        params["state"] = state

    url = f"{settings.c2_authorize_url}?{urlencode(params)}"
    logger.debug(f"Authorization URL: {url}")
    return url


async def exchange_code_for_token(code: str) -> TokenResponse:
    """Exchange an authorization code for an access + refresh token."""
    payload = {
        "client_id": settings.c2_client_id,
        "client_secret": settings.c2_client_secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.c2_redirect_uri,
        "scope": settings.c2_scope,
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(
            settings.c2_token_url,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        data = response.json()
        logger.info("Successfully obtained access token.")
        return TokenResponse(**data)


async def refresh_access_token(refresh_token: str) -> TokenResponse:
    """Use a refresh token to get a new access token."""
    payload = {
        "client_id": settings.c2_client_id,
        "client_secret": settings.c2_client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": settings.c2_scope,
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(
            settings.c2_token_url,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        data = response.json()
        logger.info("Successfully refreshed access token.")
        return TokenResponse(**data)
