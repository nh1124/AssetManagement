from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
import os

class Settings(BaseSettings):
    """Application settings using Pydantic Settings and .env. Pattern from VisionArk."""
    
    # Auth Settings
    jwt_secret_key: str = "dev_jwt_secret_change_in_production_must_be_32_chars"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24  # 24 hours
    
    # Database Settings
    database_url: str = "sqlite:///./finance.db"
    
    # Encryption Settings (for API Keys)
    encryption_key: str = "YLM_ViHfrMWM0hUF3XoAMLLSaL4dVTy-JnHamAaIWTo="

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

@lru_cache()
def get_settings():
    return Settings()

settings = get_settings()
