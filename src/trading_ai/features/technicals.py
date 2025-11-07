"""Intraday feature engineering helpers."""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd


def compute_intraday_features(bars: pd.DataFrame) -> Dict[str, float]:
    """Return simple momentum/volatility features for a bar dataframe."""

    if bars.empty:
        return {"momentum_15": 0.0, "momentum_60": 0.0, "volatility": 0.0}

    close = bars["close"].astype(float)
    momentum_15 = _pct_change(close, 15)
    momentum_60 = _pct_change(close, 60)
    volatility = close.pct_change().tail(60).std(ddof=0) * np.sqrt(390) if len(close) > 1 else 0.0
    return {
        "momentum_15": float(momentum_15),
        "momentum_60": float(momentum_60),
        "volatility": float(volatility),
    }


def _pct_change(series: pd.Series, window: int) -> float:
    if len(series) < window + 1:
        window = len(series) - 1
    if window <= 0:
        return 0.0
    start = series.iloc[-window - 1]
    end = series.iloc[-1]
    return (end - start) / start if start else 0.0
