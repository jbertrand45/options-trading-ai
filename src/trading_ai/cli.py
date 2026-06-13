"""Command-line interface for TradingAI utilities."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict

import orjson
import pandas as pd

from trading_ai.core.pipeline import SignalPipeline
from trading_ai.risk.manager import RiskManager
from trading_ai.service.auto_trader import AutoTrader, AutoTraderConfig
from trading_ai.settings import get_settings
from trading_ai.strategies.momentum_iv import MomentumIVStrategy


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
    payload = orjson.dumps(
        _to_serializable(snapshot),
        option=orjson.OPT_INDENT_2,
        default=str,
    )
    path.write_bytes(payload)
    print(f"Snapshot saved to {path}")


def command_auto_trade(args: argparse.Namespace) -> None:
    """Execute AutoTrader once or in a loop."""

    settings = get_settings()
    min_conf = args.min_confidence if args.min_confidence is not None else settings.auto_min_confidence
    risk_fraction = args.risk_fraction if args.risk_fraction is not None else settings.auto_risk_fraction
    max_positions = args.max_positions if args.max_positions is not None else settings.auto_max_positions
    account_equity = args.account_equity if args.account_equity is not None else settings.auto_account_equity
    interval = args.interval if args.interval is not None else settings.auto_interval_seconds
    include_news = settings.auto_include_news if args.include_news is None else args.include_news
    use_cache = settings.auto_use_cache if args.use_cache is None else args.use_cache
    use_snapshot_stream = (
        settings.auto_use_snapshot_stream if args.use_snapshot_stream is None else args.use_snapshot_stream
    )
    use_live_stream_arg = getattr(args, "use_live_stream", None)
    use_live_stream = settings.auto_use_live_stream if use_live_stream_arg is None else use_live_stream_arg
    stream_interval = (
        args.stream_interval if args.stream_interval is not None else settings.auto_stream_interval_seconds
    )
    stream_force_refresh = (
        settings.auto_stream_force_refresh if args.stream_force_refresh is None else args.stream_force_refresh
    )
    min_option_agg_bars = (
        args.min_option_agg_bars if args.min_option_agg_bars is not None else settings.min_option_agg_bars
    )
    min_option_agg_volume = (
        args.min_option_agg_volume if args.min_option_agg_volume is not None else settings.min_option_agg_volume
    )
    min_option_agg_vwap = (
        args.min_option_agg_vwap if args.min_option_agg_vwap is not None else settings.min_option_agg_vwap
    )
    max_option_spread_pct = (
        args.max_option_spread_pct if args.max_option_spread_pct is not None else settings.max_option_spread_pct
    )
    stop_loss_fraction = (
        args.stop_loss_fraction if args.stop_loss_fraction is not None else settings.auto_stop_loss_fraction
    )
    take_profit_reward = (
        args.take_profit_reward if args.take_profit_reward is not None else settings.auto_take_profit_reward
    )
    order_mode = args.option_order_mode or settings.auto_order_mode
    config = AutoTraderConfig(
        lookback_minutes=args.lookback_minutes,
        news_hours=args.news_hours,
        timeframe=args.timeframe,
        min_confidence=min_conf,
        trade_risk_fraction=risk_fraction,
        max_positions=max_positions,
        account_equity=account_equity,
        dry_run=not args.live,
        include_news=include_news,
        use_cache=use_cache,
        sleep_seconds=interval,
        min_option_agg_bars=min_option_agg_bars,
        min_option_agg_volume=min_option_agg_volume,
        min_option_agg_vwap=min_option_agg_vwap,
        max_option_spread_pct=max_option_spread_pct,
        min_option_liquidity=args.min_option_liquidity,
        use_snapshot_stream=use_snapshot_stream,
        use_live_stream=use_live_stream,
        stream_interval_seconds=stream_interval,
        stream_force_refresh=stream_force_refresh,
        option_order_mode=order_mode,
        enable_option_aggregates=settings.enable_option_aggregates,
        stop_loss_fraction=stop_loss_fraction,
        take_profit_reward=take_profit_reward,
    )
    risk_manager = RiskManager(
        min_confidence=min_conf,
        max_spread_pct=config.max_option_spread_pct,
        min_liquidity=config.min_option_liquidity,
        max_daily_loss_pct=config.trade_risk_fraction,
    )
    trader = AutoTrader(
        settings,
        pipeline=SignalPipeline(settings),
        strategy=MomentumIVStrategy(),
        risk_manager=risk_manager,
        config=config,
    )
    try:
        if args.loop:
            trader.run_loop()
        else:
            intents = trader.run_once()
            if not intents:
                print("No trades met the criteria.")
            else:
                print("Generated trade intents:")
                for intent in intents:
                    print(intent)
    finally:
        trader.close()


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

    auto = sub.add_parser("auto-trade", help="Score live signals and (optionally) submit orders.")
    auto.add_argument("--lookback-minutes", type=int, default=120, help="Lookback window for underlying bars.")
    auto.add_argument("--news-hours", type=int, default=3, help="News lookback window.")
    auto.add_argument("--timeframe", type=str, default="1Min", help="Underlying bar timeframe.")
    auto.add_argument("--min-confidence", type=float, default=None, help="Minimum confidence required to trade.")
    auto.add_argument("--risk-fraction", type=float, default=None, help="Fraction of equity risked per trade.")
    auto.add_argument("--max-positions", type=int, default=None, help="Maximum contracts per trade.")
    auto.add_argument("--account-equity", type=float, default=None, help="Account equity for sizing calculations.")
    auto.add_argument(
        "--stop-loss-fraction",
        type=float,
        default=None,
        help="Fractional stop-loss per trade (e.g., 0.03 = 3%% below entry).",
    )
    auto.add_argument(
        "--take-profit-reward",
        type=float,
        default=None,
        help="Reward multiple of risk to set take-profit (e.g., 2.5 => 2.5R).",
    )
    auto.add_argument(
        "--min-option-agg-bars",
        type=int,
        default=None,
        help="Minimum number of Alpaca option bars required.",
    )
    auto.add_argument(
        "--min-option-agg-volume",
        type=float,
        default=None,
        help="Minimum summed volume across Alpaca option aggregates.",
    )
    auto.add_argument(
        "--min-option-agg-vwap",
        type=float,
        default=None,
        help="Minimum absolute VWAP trend required from Alpaca option aggregates.",
    )
    auto.add_argument(
        "--max-option-spread-pct",
        type=float,
        default=None,
        help="Maximum bid/ask spread (fraction of option price) allowed when sizing trades.",
    )
    auto.add_argument(
        "--min-option-liquidity",
        type=float,
        default=50.0,
        help="Minimum cumulative option volume required to allocate capital.",
    )
    auto.add_argument(
        "--include-news",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Include news ingestion before scoring signals.",
    )
    auto.add_argument(
        "--use-cache",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Allow cached data for collection.",
    )
    auto.add_argument(
        "--use-snapshot-stream",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Maintain a rolling snapshot between cycles instead of collecting every run.",
    )
    auto.add_argument(
        "--use-live-stream",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable Alpaca live bar stream to enrich snapshots between cycles.",
    )
    auto.add_argument(
        "--stream-interval",
        type=float,
        default=None,
        help="Interval (seconds) between background snapshot refreshes when streaming.",
    )
    auto.add_argument(
        "--stream-force-refresh",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Force a fresh snapshot each cycle even when the stream has cached data.",
    )
    auto.add_argument(
        "--option-order-mode",
        choices=["long", "cash_secured", "auto"],
        default=None,
        help="Order style: long buys, cash-secured/covered sells, or auto fallback.",
    )
    auto.add_argument("--loop", action="store_true", help="Continuously run until interrupted.")
    auto.add_argument("--interval", type=int, default=None, help="Sleep seconds between loops when --loop is set.")
    auto.add_argument("--live", action="store_true", help="Submit live orders (WARNING: real capital at risk, test with paper trading first).")
    auto.set_defaults(func=command_auto_trade)

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
