from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET_KEY = "dev_jwt_secret_change_in_production_must_be_32_chars"
DEV_ENCRYPTION_KEY = "YLM_ViHfrMWM0hUF3XoAMLLSaL4dVTy-JnHamAaIWTo="


class AppConfig(BaseSettings):
    """Application settings using Pydantic Settings and .env. Pattern from VisionArk."""

    # Runtime Environment
    app_env: str = "development"

    # Auth Settings
    jwt_secret_key: str = DEV_JWT_SECRET_KEY
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24  # 24 hours

    # Database Settings
    database_url: str = "sqlite:///./finance.db"

    # Encryption Settings (for API Keys)
    encryption_key: str = DEV_ENCRYPTION_KEY

    # CORS Settings
    allowed_origins: str = "http://localhost:5173,http://localhost:15173,http://127.0.0.1:5173,http://127.0.0.1:15173"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def normalized_app_env(self) -> str:
        return (self.app_env or "development").strip().lower()

    @property
    def is_production(self) -> bool:
        return self.normalized_app_env == "production"

    @property
    def is_development(self) -> bool:
        return not self.is_production

    @property
    def cors_allowed_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in (self.allowed_origins or "").split(",")
            if origin.strip()
        ]

    def validate_production_settings(self) -> None:
        if not self.is_production:
            return

        errors: list[str] = []
        if self.jwt_secret_key == DEV_JWT_SECRET_KEY:
            errors.append("JWT_SECRET_KEY must be changed in production")
        if self.encryption_key == DEV_ENCRYPTION_KEY:
            errors.append("ENCRYPTION_KEY must be changed in production")
        if "*" in self.cors_allowed_origins:
            errors.append("ALLOWED_ORIGINS must not contain '*' in production")
        if not self.cors_allowed_origins:
            errors.append("ALLOWED_ORIGINS must include at least one trusted origin in production")

        if errors:
            raise RuntimeError("Invalid production configuration: " + "; ".join(errors))


@lru_cache()
def get_settings():
    return AppConfig()

settings = get_settings()
