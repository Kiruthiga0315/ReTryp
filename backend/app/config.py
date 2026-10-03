"""Application settings.

Every external integration is optional. The application must be fully
functional with an empty environment: providers that are unconfigured are
reported as unavailable rather than invented.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR.parent / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "ReTryp API"
    environment: str = "development"

    # --- storage -------------------------------------------------------
    # SQLite by default; PostgreSQL via DATABASE_URL.
    database_url: str = f"sqlite:///{BACKEND_DIR / 'retryp.db'}"

    # --- web -----------------------------------------------------------
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    session_ttl_hours: int = 24 * 14
    cookie_secure: bool = False

    provider_cache_ttl_seconds: int = 900

    # --- flight schedule / status providers ----------------------------
    # aerodatabox | aviationstack | flightaware. Empty means "auto-detect from
    # whichever key is set". There is no demo provider.
    flight_provider: str = ""
    aerodatabox_api_key: str = ""
    aviationstack_api_key: str = ""
    flightaware_api_key: str = ""
    # How many hubs a connection search may spend calls on beyond the direct
    # pair. Each hub costs two calls on a metered plan, so this is a budget
    # control, not a suggestion: 3 hubs plus the direct call is 7 calls, which
    # keeps a journey build inside a small monthly allowance. Set to 0 to list
    # direct services only.
    connection_search_hubs: int = 3
    # How many timed itineraries to keep per hub in the connection list.
    connection_per_hub: int = 2

    # --- reference / positions ----------------------------------------
    opensky_client_id: str = ""
    opensky_client_secret: str = ""

    # --- ground transport ---------------------------------------------
    transitland_api_key: str = ""
    mobility_database_api_key: str = ""
    railradar_api_key: str = ""
    railradar_base_url: str = "https://api.railradar.in/v1"
    railradar_timeout_seconds: float = 10.0
    indianrailway: str = ""

    # --- hotels --------------------------------------------------------
    amadeus_base_url: str = "https://test.api.amadeus.com"
    amadeus_client_id: str = ""
    amadeus_client_secret: str = ""

    # --- currency (display conversion) ---------------------------------
    # Amounts are stored in the currency the provider quoted. Display uses the
    # viewer's preferred currency, converted with a live rate when one can be
    # fetched. No key is needed for the rate source.
    fx_enabled: bool = True
    fx_base_url: str = "https://api.frankfurter.app"
    # The base is the currency the rate source quotes against, not what the
    # viewer sees; that is ``fx_display_currency``.
    fx_base_currency: str = "EUR"
    # The currency a viewer sees when they have not chosen one. Indian Rupee
    # is the product default; a viewer's own Settings value always wins.
    fx_display_currency: str = "INR"
    fx_cache_ttl_seconds: int = 3600
    fx_timeout_seconds: float = 10.0
    # The currencies the UI can display. Used only to shape the rate request;
    # no rate value is stored here.
    fx_display_currencies: list[str] = [
        "USD",
        "GBP",
        "INR",
        "CHF",
        "SEK",
        "NOK",
        "DKK",
        "JPY",
    ]

    # --- maps ----------------------------------------------------------
    nominatim_user_agent: str = "ReTryp/1.0 (contact: ops@retryp.example)"
    osrm_base_url: str = "https://router.project-osrm.org"

    # --- LLM (optional; deterministic fallback when unset) -------------
    llm_provider: str = ""  # gemini | openai_compatible | ""
    llm_model: str = "gemini-2.5-flash-lite"  # single source of truth for the model id
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_fallback_provider: str = ""
    llm_fallback_model: str = ""
    llm_fallback_api_key: str = ""
    llm_fallback_base_url: str = ""
    llm_timeout_seconds: float = 20.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_provider and self.llm_api_key)

    @property
    def effective_railradar_api_key(self) -> str:
        return (self.railradar_api_key or self.indianrailway).strip()

    @property
    def railradar_enabled(self) -> bool:
        return bool(self.effective_railradar_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
