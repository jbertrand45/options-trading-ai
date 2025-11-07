"""Tests for LocalDataCache."""

from pathlib import Path

import pandas as pd
import pytest

from trading_ai.data.cache import LocalDataCache


def test_local_data_cache_json_roundtrip(tmp_path: Path) -> None:
    cache = LocalDataCache(root=tmp_path / "cache")
    payload = {"ticker": "AAPL", "value": 42}

    cache.write_json(payload, "alpaca", "test")
    assert cache.exists("alpaca", "test", suffix=".json")

    loaded = cache.read_json("alpaca", "test")
    assert loaded == payload


def test_local_data_cache_dataframe_roundtrip(tmp_path: Path) -> None:
    cache = LocalDataCache(root=tmp_path / "cache")
    frame = pd.DataFrame({"ticker": ["AAPL", "MSFT"], "close": [150.0, 320.5]})

    cache.write_dataframe(frame, "alpaca", "bars", "AAPL")
    reloaded = cache.read_dataframe("alpaca", "bars", "AAPL")

    pd.testing.assert_frame_equal(reloaded, frame)


def test_local_data_cache_remove(tmp_path: Path) -> None:
    cache = LocalDataCache(root=tmp_path / "cache")
    cache.write_json({"foo": "bar"}, "alpaca", "delete-me")

    cache.remove("alpaca", "delete-me")
    assert not cache.exists("alpaca", "delete-me")


def test_write_dataframe_raises_on_empty_frame(tmp_path: Path) -> None:
    cache = LocalDataCache(root=tmp_path / "cache")
    with pytest.raises(ValueError):
        cache.write_dataframe(pd.DataFrame(), "alpaca", "empty")
