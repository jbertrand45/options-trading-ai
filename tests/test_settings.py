"""Settings tests."""

import os

import pytest

from trading_ai.settings import Settings


def test_settings_parses_comma_separated_tickers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_API_KEY_ID", "key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")
    monkeypatch.delenv("NEWS_API_KEY", raising=False)
    monkeypatch.setenv("POLYGON_API_KEY", "polygon")
    monkeypatch.setenv("TARGET_TICKERS", '["spy","qqq","tsla"]')

    settings = Settings()

    assert settings.target_tickers == ["SPY", "QQQ", "TSLA"]


def test_settings_alpaca_data_feed_defaults_to_iex(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_API_KEY_ID", "key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")
    monkeypatch.setenv("POLYGON_API_KEY", "polygon")
    monkeypatch.delenv("ALPACA_DATA_FEED", raising=False)

    settings = Settings()

    assert settings.alpaca_data_feed == "IEX"


def test_settings_loads_option_agg_thresholds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_API_KEY_ID", "key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")
    monkeypatch.setenv("POLYGON_API_KEY", "polygon")
    monkeypatch.setenv("MIN_OPTION_AGG_BARS", "25")
    monkeypatch.setenv("MIN_OPTION_AGG_VOLUME", "123.5")
    monkeypatch.setenv("MIN_OPTION_AGG_VWAP", "0.04")

    settings = Settings()

    assert settings.min_option_agg_bars == 25
    assert settings.min_option_agg_volume == pytest.approx(123.5)
    assert settings.min_option_agg_vwap == pytest.approx(0.04)
