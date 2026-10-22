from functools import lru_cache
from urllib.parse import urlparse
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET_KEY = "dev_jwt_secret_change_in_production_must_be_32_chars"
DEV_ENCRYPTION_KEY = "YLM_ViHfrMWM0hUF3XoAMLLSaL4dVTy-JnHamAaIWTo="
DEV_TOTP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
DEV_MCP_JWT_SECRET = "change-me-to-a-secret-key-at-least-32-chars"


class AppConfig(BaseSettings):
    """Application settings using Pydantic Settings and .env. Pattern from VisionArk."""

    # Runtime Environment
    app_env: str = "development"

    # Auth Settings
    jwt_secret_key: str = DEV_JWT_SECRET_KEY
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24  # 24 hours
    mcp_jwt_secret: str = DEV_MCP_JWT_SECRET
    mcp_token_audience: str = "asset-management-backend"
    mcp_allowed_issuers: str = "http://localhost:13000"
    mcp_base_url: str = ""

    admin_allowed_hosts: str = "admin.localhost"
    admin_allowed_origins: str = "http://admin.localhost:18300"
    admin_cookie_secure: bool = False
    admin_session_idle_minutes: int = 30
    admin_session_max_hours: int = 8
    admin_ui_dir: str = ""

    # Database Settings
    database_url: str = "sqlite:///./finance.db"

    # Encryption Settings (for API Keys)
    encryption_key: str = DEV_ENCRYPTION_KEY
    # Comma-separated keys that may still decrypt stored values but are no
    # longer used to encrypt. Only set while a key rotation is in progress.
    encryption_key_previous: str = ""

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
    def encryption_keys(self) -> list[str]:
        """Current key first, then the previous ones."""
        previous = [key.strip() for key in (self.encryption_key_previous or "").split(",") if key.strip()]
        return [self.encryption_key, *(key for key in previous if key != self.encryption_key)]

    @property
    def cors_allowed_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in (self.allowed_origins or "").split(",")
            if origin.strip()
        ]

    @property
    def allowed_mcp_token_issuers(self) -> list[str]:
        issuers = [
            issuer.strip().rstrip("/")
            for issuer in (self.mcp_allowed_issuers or "").split(",")
            if issuer.strip()
        ]
        base_url = (self.mcp_base_url or "").strip().rstrip("/")
        if base_url and base_url not in issuers:
            issuers.append(base_url)
        if self.is_development:
            for issuer in list(issuers):
                parsed = urlparse(issuer)
                if parsed.scheme in {"http", "https"} and parsed.hostname in {"localhost", "127.0.0.1"}:
                    alternate_scheme = "https" if parsed.scheme == "http" else "http"
                    alternate = parsed._replace(scheme=alternate_scheme).geturl().rstrip("/")
                    if alternate not in issuers:
                        issuers.append(alternate)
        return issuers

    def _admin_production_errors(self) -> list[str]:
        errors: list[str] = []
        if not self.encryption_key.strip() or self.encryption_key == DEV_ENCRYPTION_KEY:
            errors.append("ENCRYPTION_KEY must be changed in production")
        for key in ("admin_allowed_hosts", "admin_allowed_origins"):
            value = getattr(self, key)
            if "*" in value:
                errors.append(f"{key.upper()} must not contain '*' in production")
            if not any(part.strip() for part in value.split(",")):
                errors.append(f"{key.upper()} must include at least one trusted value in production")
        return errors

    def validate_admin_production_settings(self) -> None:
        """The admin process decrypts MFA secrets; it never signs user/MCP JWTs."""
        if not self.is_production:
            return
        errors = self._admin_production_errors()
        if errors:
            raise RuntimeError("Invalid production configuration: " + "; ".join(errors))

    def validate_production_settings(self) -> None:
        if not self.is_production:
            return

        errors = self._admin_production_errors()
        if self.jwt_secret_key == DEV_JWT_SECRET_KEY:
            errors.append("JWT_SECRET_KEY must be changed in production")
        if self.mcp_jwt_secret == DEV_MCP_JWT_SECRET:
            errors.append("MCP_JWT_SECRET must be changed in production")
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
