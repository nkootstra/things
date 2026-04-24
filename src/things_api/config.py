from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    api_key: str = ""
    things_email: str = ""
    things_password: str = ""
    sync_interval_seconds: int = 0  # 0 = disabled
    database_url: str = "sqlite+aiosqlite:///./data/things.db"

    model_config = {"env_prefix": "", "case_sensitive": False}

    def validate_api_key(self) -> None:
        if self.api_key and len(self.api_key) < 32:
            raise ValueError("API_KEY must be at least 32 characters")


settings = Settings()
