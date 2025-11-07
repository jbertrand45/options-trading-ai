"""Application-wide configuration management using Pydantic settings."""

from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed configuration for the trading AI project."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    alpaca_api_key_id: str = Field(..., alias="ALPACA_API_KEY_ID")
    alpaca_api_secret_key: str = Field(..., alias="ALPACA_API_SECRET_KEY")
    alpaca_paper_base_url: str = Field("https://paper-api.alpaca.markets", alias="ALPACA_PAPER_BASE_URL")

    polygon_api_key: str = Field(..., alias="POLYGON_API_KEY")
    news_api_key: str | None = Field(None, alias="NEWS_API_KEY")
    news_secret_key: str | None = Field(None, alias="NEWS_SECRET_KEY")
    alpha_vantage_api_key: str | None = Field(None, alias="ALPHA_VANTAGE_API_KEY")
    marketaux_api_key: str | None = Field(None, alias="MARKETAUX_API_KEY")

    target_tickers: List[str] = Field(
        default_factory=lambda: [
            "AAPL",
            "MSFT",
            "AMZN",
            "GOOG",
            "NVDA",
            "META",
            "TSLA",
            "PLTR",
            "OPEN",
            "AMD",
            "HOOD",
        ],
        alias="TARGET_TICKERS",
    )
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    enable_news: bool = Field(True, alias="ENABLE_NEWS")
    use_polygon_bars: bool = Field(False, alias="USE_POLYGON_BARS")

    @field_validator("target_tickers", mode="before")
    @classmethod
    def _split_tickers(cls, value: List[str] | str) -> List[str]:
        """Support comma-separated ticker strings in environment variables."""

        if isinstance(value, list):
            return [str(ticker).strip().upper() for ticker in value if str(ticker).strip()]
        return [ticker.strip().upper() for ticker in value.split(",") if ticker.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings instance loaded from environment variables."""

    return Settings()
