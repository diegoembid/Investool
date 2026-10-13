"""Configuración de la aplicación.

Todo se lee de variables de entorno (fichero `.env` en local). Ninguna clave se escribe
en el código ni se sube al repositorio.
"""

from decimal import Decimal
from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- General ---
    environment: str = Field(default="local", description="local | production | test")
    database_url: str = "postgresql+psycopg://investool:investool@db:5432/investool"

    # Clave maestra para cifrar secretos guardados en la base de datos (p. ej. la semilla
    # del doble factor). Se genera con `python -m app.cli generate-secret`.
    app_secret_key: SecretStr

    # Nombres con los que se puede acceder a la aplicación (sin puerto), separados por comas.
    # Protege frente a ataques de "DNS rebinding" desde webs maliciosas.
    allowed_hosts: str = "localhost,127.0.0.1,backend"

    # --- Sesiones y acceso ---
    session_hours: int = 12
    cookie_secure: bool = True
    login_max_failures: int = 5
    login_lockout_minutes: int = 15

    # --- IA: claves ---
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None

    # --- IA: control de gasto (USD, mes natural en UTC) ---
    ai_enabled: bool = True
    ai_global_monthly_cap_usd: Decimal = Decimal("120")
    ai_global_daily_cap_usd: Decimal = Decimal("10")
    ai_anthropic_monthly_cap_usd: Decimal = Decimal("80")
    ai_openai_monthly_cap_usd: Decimal = Decimal("40")
    # Tipo de cambio solo para mostrar importes en euros; no afecta a los topes.
    usd_to_eur: Decimal = Decimal("0.86")

    # --- IA: modelos para la prueba de proveedores ---
    ai_anthropic_smoke_model: str = "claude-haiku-5-5"
    ai_openai_smoke_model: str = "gpt-6-luna"

    # --- IA: caché ---
    ai_cache_hours: int = 24

    @field_validator("app_secret_key")
    @classmethod
    def _secret_not_placeholder(cls, v: SecretStr) -> SecretStr:
        raw = v.get_secret_value()
        if not raw or raw.startswith("CAMBIAR"):
            raise ValueError(
                "APP_SECRET_KEY no está configurada. Genera una con "
                "`python -m app.cli generate-secret` y pégala en el fichero .env"
            )
        return v

    def allowed_host_set(self) -> set[str]:
        return {h.strip().lower() for h in self.allowed_hosts.split(",") if h.strip()}

    def provider_monthly_cap(self, provider: str) -> Decimal:
        caps = {
            "anthropic": self.ai_anthropic_monthly_cap_usd,
            "openai": self.ai_openai_monthly_cap_usd,
        }
        return caps.get(provider, Decimal("0"))


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
