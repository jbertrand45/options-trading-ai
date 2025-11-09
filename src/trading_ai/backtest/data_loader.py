"""Helpers to load StrategyContext objects from snapshot artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List

import orjson
import pandas as pd

from trading_ai.strategies.base import StrategyContext


def load_snapshot_file(path: str | Path) -> Dict[str, Dict]:
    payload = orjson.loads(Path(path).read_bytes())
    return payload


def contexts_from_snapshot(snapshot: Dict[str, Dict]) -> List[StrategyContext]:
    contexts: List[StrategyContext] = []
    for ticker, data in snapshot.items():
        bars = data.get("underlying_bars") or []
        if isinstance(bars, list):
            bars_df = pd.DataFrame(bars)
        elif isinstance(bars, pd.DataFrame):
            bars_df = bars
        else:
            bars_df = pd.DataFrame()

        option_chain = data.get("option_chain")
        option_metrics = data.get("option_metrics") or {}
        option_quote = data.get("option_quote") or {}
        news = data.get("news") or []
        features = data.get("features") or {}

        context = StrategyContext(
            ticker=ticker,
            underlying_bars=bars_df,
            option_chain=option_chain,
            option_metrics=option_metrics,
            option_quote=option_quote,
            news_items=news,
            features=features,
        )
        contexts.append(context)
    return contexts
