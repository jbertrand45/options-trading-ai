"""Feature engineering tests."""

import pandas as pd

from trading_ai.features import compute_intraday_features


def test_compute_intraday_features_handles_empty() -> None:
    features = compute_intraday_features(pd.DataFrame())
    assert features["momentum_15"] == 0.0


def test_compute_intraday_features_basic() -> None:
    data = pd.DataFrame({"close": [100, 101, 102, 103, 104, 105]})
    features = compute_intraday_features(data)
    assert "momentum_15" in features
    assert isinstance(features["volatility"], float)
