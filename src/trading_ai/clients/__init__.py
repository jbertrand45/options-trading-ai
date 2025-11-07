"""Client adapters for external data providers."""

from trading_ai.clients.alpaca_client import AlpacaClient
from trading_ai.clients.alpha_vantage_client import AlphaVantageNewsClient
from trading_ai.clients.marketaux_client import MarketauxClient
from trading_ai.clients.news_aggregator import NewsAggregator
from trading_ai.clients.news_client import NewsClient
from trading_ai.clients.polygon_client import PolygonClient
from trading_ai.clients.yahoo_client import YahooNewsClient

__all__ = [
    "AlpacaClient",
    "NewsClient",
    "PolygonClient",
    "YahooNewsClient",
    "AlphaVantageNewsClient",
    "MarketauxClient",
    "NewsAggregator",
]
