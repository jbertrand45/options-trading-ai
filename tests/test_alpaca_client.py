"""Tests for Alpaca client TLS overrides."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from trading_ai.clients.alpaca_client import AlpacaClient
from trading_ai.settings import Settings


class DummySession:
    def __init__(self) -> None:
        self.verify = True


class DummyOptionClient:
    def __init__(self, *args, **kwargs) -> None:
        self._session = DummySession()
        self.oauth_token = kwargs.get("oauth_token")


class DummyEquityClient(DummyOptionClient):
    pass


class DummyTradingClient(DummyOptionClient):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.oauth_access_token = kwargs.get("oauth_access_token")


def build_settings(monkeypatch: pytest.MonkeyPatch, *, verify_tls: str = "1", ca_bundle: str | None = None) -> Settings:
    monkeypatch.setenv("ALPACA_API_KEY_ID", "key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")
    monkeypatch.setenv("ALPACA_DATA_FEED", "IEX")
    monkeypatch.setenv("ALPACA_VERIFY_TLS", verify_tls)
    if ca_bundle is not None:
        monkeypatch.setenv("ALPACA_CA_BUNDLE", ca_bundle)
    else:
        monkeypatch.delenv("ALPACA_CA_BUNDLE", raising=False)
    return Settings()


@pytest.fixture(autouse=True)
def patch_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("trading_ai.clients.alpaca_client.OptionHistoricalDataClient", DummyOptionClient)
    monkeypatch.setattr("trading_ai.clients.alpaca_client.StockHistoricalDataClient", DummyEquityClient)
    monkeypatch.setattr("trading_ai.clients.alpaca_client.TradingClient", DummyTradingClient)


def test_alpaca_client_disables_tls_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = build_settings(monkeypatch, verify_tls="0")

    client = AlpacaClient(settings)

    assert client._option_client._session.verify is False  # type: ignore[attr-defined]
    assert client._equity_client._session.verify is False  # type: ignore[attr-defined]


def test_alpaca_client_uses_custom_ca_bundle(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    cert_path = tmp_path / "corp.pem"
    cert_path.write_text("dummy")
    settings = build_settings(monkeypatch, ca_bundle=str(cert_path))

    client = AlpacaClient(settings)

    assert client._option_client._session.verify == str(cert_path)  # type: ignore[attr-defined]


def test_alpaca_client_uses_oauth_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_API_KEY_ID", "key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")
    monkeypatch.setenv("ALPACA_OAUTH_TOKEN", "oauth-token")
    monkeypatch.setenv("ALPACA_DATA_FEED", "IEX")
    settings = Settings()

    client = AlpacaClient(settings)

    assert client._trading_client.oauth_access_token == "oauth-token"  # type: ignore[attr-defined]
    assert client._option_client.oauth_token == "oauth-token"  # type: ignore[attr-defined]
