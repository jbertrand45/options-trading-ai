"""Command-line interface for TradingAI utilities."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict

import orjson
import pandas as pd

from trading_ai.core.pipeline import SignalPipeline
from trading_ai.settings import get_settings


def command_check_config(args: argparse.Namespace) -> None:
    """Print active configuration."""

    settings = get_settings()
    print("TradingAI configuration")
    print(f"Tracked tickers: {settings.target_tickers}")
    print(f"Log level: {settings.log_level}")


def command_collect_snapshots(args: argparse.Namespace) -> None:
    """Collect and persist market snapshots for later analysis."""

    settings = get_settings()
    pipeline = SignalPipeline(settings)
    lookback = timedelta(minutes=args.lookback_minutes)
    news_lookback = timedelta(hours=args.news_hours)
    print(
        f"Collecting snapshots for {len(settings.target_tickers)} tickers "
        f"(lookback={args.lookback_minutes}m, news={args.news_hours}h, timeframe={args.timeframe})..."
    )
    snapshot = pipeline.collect_market_snapshot(
        lookback=lookback,
        news_lookback=news_lookback,
        timeframe=args.timeframe,
        use_cache=not args.no_cache,
        include_news=not args.skip_news,
    )

    output_dir: Path = args.output
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"snapshots_{timestamp}.json"
    payload = orjson.dumps(_to_serializable(snapshot), option=orjson.OPT_INDENT_2)
    path.write_bytes(payload)
    print(f"Snapshot saved to {path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TradingAI command-line tools.")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check-config", help="Print active configuration.")
    check.set_defaults(func=command_check_config)

    collect = sub.add_parser("collect-snapshots", help="Collect and persist market snapshots.")
    collect.add_argument("--output", type=Path, default=Path("data/snapshots"), help="Output directory for JSON snapshots.")
    collect.add_argument("--lookback-minutes", type=int, default=390, help="Underlying bar lookback window in minutes.")
    collect.add_argument("--news-hours", type=int, default=12, help="News lookback window in hours.")
    collect.add_argument("--timeframe", type=str, default="1Min", help="Underlying bar timeframe (Alpaca syntax).")
    collect.add_argument("--no-cache", action="store_true", help="Bypass local cache when collecting data.")
    collect.add_argument("--skip-news", action="store_true", help="Skip news ingestion when collecting snapshots.")
    collect.set_defaults(func=command_collect_snapshots)

    return parser


def run(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


def _to_serializable(snapshot: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    serializable: Dict[str, Dict[str, Any]] = {}
    for ticker, data in snapshot.items():
        entry: Dict[str, Any] = {}
        for key, value in data.items():
            if key == "underlying_bars" and isinstance(value, pd.DataFrame):
                entry[key] = value.to_dict(orient="records")
            elif key == "option_chain" and isinstance(value, pd.DataFrame):
                entry[key] = value.to_dict(orient="records")
            else:
                entry[key] = value
        serializable[ticker] = entry
    return serializable


if __name__ == "__main__":
    run()
