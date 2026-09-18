from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env.sodexo"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite:///./data/sodexo.db"
    mock_api_base_url: str = "http://127.0.0.1:8200"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    # Signs the login tokens. The default is a known development value, so
    # anything beyond a local run must set JWT_SECRET in .env.sodexo - with
    # this default, a token minted anywhere is accepted here. Changing it
    # invalidates every issued token, which is also how you force a re-login.
    jwt_secret: str = "sodexo-poc-dev-secret-change-me"
    jwt_expire_minutes: int = 480

    # Square POS connector. The sandbox and production tokens are different
    # credentials against different hosts, so the host is derived from which
    # one is set rather than configured separately and got wrong.
    square_sandbox_token: str | None = None
    square_api_version: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
