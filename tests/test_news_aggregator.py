"""Tests for NewsAggregator normalization."""

from datetime import datetime, timedelta

from trading_ai.clients.news_aggregator import NewsAggregator


class DummyArticle:
    def __init__(self, title: str) -> None:
        self.title = title
        self.link = "http://example.com/article"

    def model_dump(self) -> dict:
        return {"title": self.title, "link": self.link}


def test_news_aggregator_normalizes_objects() -> None:
    aggregator = NewsAggregator()
    aggregator.providers.append(lambda ticker, since, limit: [DummyArticle("Hello World")])

    stories = aggregator.gather("AAPL", since=datetime.utcnow() - timedelta(hours=1))

    assert len(stories) == 1
    assert stories[0]["title"] == "Hello World"
