"""Application-wide configuration management using Pydantic settings."""

from functools import lru_cache
from typing import List, Optional, Union

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed configuration for the trading AI project."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    alpaca_api_key_id: str = Field(..., alias="ALPACA_API_KEY_ID")
    alpaca_api_secret_key: str = Field(..., alias="ALPACA_API_SECRET_KEY")
    alpaca_paper_base_url: str = Field("https://paper-api.alpaca.markets", alias="ALPACA_PAPER_BASE_URL")
    alpaca_data_feed: str = Field("IEX", alias="ALPACA_DATA_FEED")
    alpaca_data_override_ip: Optional[str] = Field(None, alias="ALPACA_DATA_OVERRIDE_IP")
    alpaca_ca_bundle: Optional[str] = Field(None, alias="ALPACA_CA_BUNDLE")
    alpaca_verify_tls: bool = Field(True, alias="ALPACA_VERIFY_TLS")
    alpaca_paper_account: bool = Field(True, alias="ALPACA_PAPER_ACCOUNT")  # SAFE DEFAULT: paper trading
    alpaca_oauth_token: Optional[str] = Field(None, alias="ALPACA_OAUTH_TOKEN")

    news_api_key: Optional[str] = Field(None, alias="NEWS_API_KEY")
    news_secret_key: Optional[str] = Field(None, alias="NEWS_SECRET_KEY")
    alpha_vantage_api_key: Optional[str] = Field(None, alias="ALPHA_VANTAGE_API_KEY")
    marketaux_api_key: Optional[str] = Field(None, alias="MARKETAUX_API_KEY")

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
    option_metrics_limit: int = Field(300, alias="OPTION_METRICS_LIMIT")
    enable_underlying_bars: bool = Field(True, alias="ENABLE_UNDERLYING_BARS")
    use_alpaca_option_chain: bool = Field(True, alias="USE_ALPACA_OPTION_CHAIN")
    auto_min_confidence: float = Field(0.55, alias="AUTO_MIN_CONFIDENCE")
    auto_risk_fraction: float = Field(0.02, alias="AUTO_RISK_FRACTION")
    auto_max_positions: int = Field(1, alias="AUTO_MAX_POSITIONS")
    auto_account_equity: float = Field(150.0, alias="AUTO_ACCOUNT_EQUITY")
    auto_interval_seconds: int = Field(60, alias="AUTO_INTERVAL_SECONDS")
    auto_include_news: bool = Field(False, alias="AUTO_INCLUDE_NEWS")
    auto_use_cache: bool = Field(False, alias="AUTO_USE_CACHE")
    auto_use_snapshot_stream: bool = Field(False, alias="AUTO_USE_SNAPSHOT_STREAM")
    auto_stream_interval_seconds: float = Field(60.0, alias="AUTO_STREAM_INTERVAL_SECONDS")
    auto_stream_force_refresh: bool = Field(False, alias="AUTO_STREAM_FORCE_REFRESH")
    auto_use_live_stream: bool = Field(False, alias="AUTO_USE_LIVE_STREAM")
    auto_stop_loss_fraction: float = Field(0.03, alias="AUTO_STOP_LOSS_FRACTION")
    auto_take_profit_reward: float = Field(2.5, alias="AUTO_TAKE_PROFIT_REWARD")
    auto_order_mode: str = Field("auto", alias="AUTO_ORDER_MODE")
    enable_option_aggregates: bool = Field(False, alias="ENABLE_OPTION_AGGREGATES")
    max_option_spread_pct: float = Field(0.25, alias="MAX_OPTION_SPREAD_PCT")
    min_option_liquidity: float = Field(50.0, alias="MIN_OPTION_LIQUIDITY")
    min_option_agg_bars: int = Field(0, alias="MIN_OPTION_AGG_BARS")
    min_option_agg_volume: float = Field(0.0, alias="MIN_OPTION_AGG_VOLUME")
    min_option_agg_vwap: float = Field(0.0, alias="MIN_OPTION_AGG_VWAP")

    @field_validator("target_tickers", mode="before")
    @classmethod
    def _split_tickers(cls, value: Union[List[str], str]) -> List[str]:
        """Support comma-separated ticker strings in environment variables."""

        if isinstance(value, list):
            return [str(ticker).strip().upper() for ticker in value if str(ticker).strip()]
        return [ticker.strip().upper() for ticker in value.split(",") if ticker.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings instance loaded from environment variables."""

    return Settings()
