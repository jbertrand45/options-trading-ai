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
