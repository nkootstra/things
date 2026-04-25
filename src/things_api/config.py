from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    api_key: str = ""
    api_key_next: str = ""
    things_email: str = ""
    things_password: str = ""
    sync_interval_seconds: int = 0  # 0 = disabled
    enable_scheduler: bool = True
    scheduler_lock_seconds: float = 30.0
    scheduler_heartbeat_seconds: float = 10.0
    manual_sync_lock_seconds: float = 120.0
    sync_retry_attempts: int = 3
    sync_retry_base_seconds: float = 0.25
    sync_circuit_breaker_failures: int = 3
    sync_circuit_breaker_cooldown_seconds: float = 60.0
    readiness_max_sync_errors: int = 5
    log_format: str = "text"       # "text" or "json" — set to "json" for structured logging
    enable_metrics: bool = False    # set to true to expose GET /metrics endpoint
    database_url: str = "sqlite+aiosqlite:///./data/things.db"

    model_config = {"env_prefix": "", "case_sensitive": False, "env_file": ".env"}

    def validate_api_key(self) -> None:
        if self.api_key and len(self.api_key) < 32:
            raise ValueError("API_KEY must be at least 32 characters")
        if self.api_key_next and len(self.api_key_next) < 32:
            raise ValueError("API_KEY_NEXT must be at least 32 characters")


settings = Settings()
