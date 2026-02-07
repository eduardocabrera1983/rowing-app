"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Settings loaded from .env file."""

    # Concept2 OAuth2
    c2_client_id: str = Field(default="", description="Concept2 OAuth2 Client ID")
    c2_client_secret: str = Field(default="", description="Concept2 OAuth2 Client Secret")
    c2_redirect_uri: str = Field(default="http://localhost:8000/auth/callback")
    c2_scope: str = Field(default="user:read,results:read")

    # Concept2 API
    c2_api_base_url: str = Field(default="https://log.concept2.com")
    c2_api_version: str = Field(default="v1")

    # App
    app_secret_key: str = Field(default="change-me-to-a-random-string")
    app_host: str = Field(default="0.0.0.0")
    app_port: int = Field(default=8000)
    app_debug: bool = Field(default=True)
    log_level: str = Field(default="INFO")

    @property
    def c2_authorize_url(self) -> str:
        return f"{self.c2_api_base_url}/oauth/authorize"

    @property
    def c2_token_url(self) -> str:
        return f"{self.c2_api_base_url}/oauth/access_token"

    @property
    def c2_api_url(self) -> str:
        return f"{self.c2_api_base_url}/api"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
