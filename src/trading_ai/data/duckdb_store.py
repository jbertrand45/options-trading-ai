"""Utilities for persisting snapshots into DuckDB."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable

import duckdb
import pandas as pd


class SnapshotStore:
    """Append snapshots into a DuckDB database for backtesting."""

    def __init__(self, db_path: str | Path = "data/snapshots.duckdb") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(str(self.db_path))
        self._ensure_tables()

    def close(self) -> None:
        self.conn.close()

    def _ensure_tables(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS underlying_bars (
                snapshot_ts TIMESTAMP,
                ticker TEXT,
                timestamp TIMESTAMP,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume DOUBLE
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS option_chain (
                snapshot_ts TIMESTAMP,
                ticker TEXT,
                payload JSON
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS news_items (
                snapshot_ts TIMESTAMP,
                ticker TEXT,
                payload JSON
            )
            """
        )

    def ingest_snapshot(self, snapshot: Dict[str, Dict[str, Any]]) -> None:
        for ticker, data in snapshot.items():
            snapshot_ts = data["collected_at"]
            bars = data.get("underlying_bars")
            if isinstance(bars, list):
                bars = pd.DataFrame(bars)
            if isinstance(bars, pd.DataFrame) and not bars.empty:
                bars = bars.copy()
                if "timestamp" in bars.columns:
                    bars["timestamp"] = pd.to_datetime(bars["timestamp"])
                bars["snapshot_ts"] = snapshot_ts
                bars["ticker"] = ticker
                cols = ["snapshot_ts", "ticker", "timestamp", "open", "high", "low", "close", "volume"]
                bars = bars[cols]
                self.conn.register("bars_df", bars)
                self.conn.execute("INSERT INTO underlying_bars SELECT * FROM bars_df")

            chain = data.get("option_chain")
            if chain:
                self.conn.execute(
                    "INSERT INTO option_chain VALUES (?, ?, ?::JSON)",
                    (snapshot_ts, ticker, chain),
                )

            news = data.get("news") or []
            if news:
                for story in news:
                    self.conn.execute(
                        "INSERT INTO news_items VALUES (?, ?, ?::JSON)",
                        (snapshot_ts, ticker, story),
                    )

    def list_snapshots(self) -> pd.DataFrame:
        return self.conn.execute(
            "SELECT DISTINCT snapshot_ts, ticker FROM underlying_bars ORDER BY snapshot_ts DESC"
        ).fetchdf()
