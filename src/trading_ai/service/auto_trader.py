"""Lightweight service to collect snapshots, score signals, and submit orders."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import orjson
import pandas as pd
from loguru import logger

from trading_ai.backtest.data_loader import contexts_from_snapshot
from trading_ai.clients import AlpacaClient
from trading_ai.clients.alpaca_stream import AlpacaStream
from trading_ai.core.pipeline import SignalPipeline
from trading_ai.risk.manager import PositionSizingInput, RiskManager
from trading_ai.settings import Settings
from trading_ai.strategies.base import StrategyContext, TradingSignal
from trading_ai.strategies.momentum_iv import MomentumIVStrategy
from trading_ai.service.snapshot_stream import SnapshotStream, SnapshotStreamConfig


@dataclass
class AutoTraderConfig:
    """Configuration knobs for AutoTrader."""

    lookback_minutes: int = 120
    news_hours: int = 3
    timeframe: str = "1Min"
    min_confidence: float = 0.55
    trade_risk_fraction: float = 0.02
    max_positions: int = 1
    account_equity: float = 150.0
    dry_run: bool = True
    include_news: bool = False
    use_cache: bool = False
    sleep_seconds: int = 60
    log_path: Path = Path("data/logs/auto_trader.log")
    min_option_agg_bars: int = 0
    min_option_agg_volume: float = 0.0
    min_option_agg_vwap: float = 0.0
    max_option_spread_pct: float = 0.25
    min_option_liquidity: float = 50.0
    use_snapshot_stream: bool = False
    stream_interval_seconds: float = 60.0
    stream_force_refresh: bool = False
    stop_loss_fraction: float = 0.03
    take_profit_reward: float = 2.5
    refresh_account_equity: bool = True
    option_order_mode: str = "auto"  # long | cash_secured | auto
    enable_exit_monitor: bool = True
    exit_log_scan_lines: int = 500
    enable_option_aggregates: bool = False
    use_live_stream: bool = False


@dataclass
class TradeIntent:
    """Represents a pending order derived from a signal."""

    ticker: str
    option_symbol: Optional[str]
    direction: str
    quantity: int
    entry_price: float
    confidence: float
    stop_price: Optional[float]
    take_profit_price: Optional[float]
    metadata: Dict[str, float]


class AutoTrader:
    """Coordinates snapshot collection, signal scoring, and order placement."""

    def __init__(
        self,
        settings: Settings,
        *,
        pipeline: Optional[SignalPipeline] = None,
        strategy: Optional[MomentumIVStrategy] = None,
        risk_manager: Optional[RiskManager] = None,
        alpaca_client: Optional[AlpacaClient] = None,
        config: Optional[AutoTraderConfig] = None,
        snapshot_stream: Optional[SnapshotStream] = None,
        live_stream: Optional[AlpacaStream] = None,
    ) -> None:
        self.settings = settings
        self.config = config or AutoTraderConfig()
        self.pipeline = pipeline or SignalPipeline(settings)
        self.strategy = strategy or MomentumIVStrategy()
        self.risk_manager = risk_manager or RiskManager(
            min_confidence=self.config.min_confidence,
            max_spread_pct=self.config.max_option_spread_pct,
            min_liquidity=self.config.min_option_liquidity,
            max_daily_loss_pct=self.config.trade_risk_fraction,
        )
        self.alpaca = alpaca_client or AlpacaClient(settings)
        self.log_path = Path(self.config.log_path).expanduser()
        self.live_stream = live_stream
        self.snapshot_stream = snapshot_stream
        self._owns_stream = False
        self._owns_live_stream = False
        self.account_equity = self.config.account_equity
        if self.live_stream is None and self.config.use_live_stream:
            try:
                self.live_stream = AlpacaStream(settings)
                self.live_stream.start(self.settings.target_tickers)
                self._owns_live_stream = True
            except Exception as exc:
                logger.warning("Failed to start Alpaca live stream; continuing without", error=str(exc))
                self.live_stream = None
                self.config.use_live_stream = False
        if self.snapshot_stream is None and self.config.use_snapshot_stream:
            stream_config = SnapshotStreamConfig(
                lookback_minutes=self.config.lookback_minutes,
                news_hours=self.config.news_hours,
                timeframe=self.config.timeframe,
                include_news=self.config.include_news,
                use_cache=self.config.use_cache,
                interval_seconds=self.config.stream_interval_seconds,
            )
            self.snapshot_stream = SnapshotStream(
                self.pipeline,
                config=stream_config,
                live_stream=self.live_stream if self.config.use_live_stream else None,
            )
            self.snapshot_stream.start()
            self._owns_stream = True

    def run_once(self) -> List[TradeIntent]:
        """Collect the latest snapshot, score signals, and optionally place orders."""

        logger.info(
            "AutoTrader cycle starting",
            lookback=self.config.lookback_minutes,
            news=self.config.news_hours,
            timeframe=self.config.timeframe,
        )
        if self.config.refresh_account_equity:
            self._update_account_equity()
        if self.config.enable_exit_monitor:
            self._maybe_close_positions()
        snapshot = self._fetch_snapshot()
        contexts = contexts_from_snapshot(snapshot)
        intents: List[TradeIntent] = []
        for context in contexts:
            intent = self._build_intent(context)
            if intent:
                intents.append(intent)
                result = self._execute_intent(intent, context)
                self._record_intent(intent, result)
        logger.info("AutoTrader cycle completed", intents=len(intents))
        return intents

    def run_loop(self) -> None:
        """Continuously run until interrupted."""

        while True:
            self.run_once()
            time.sleep(max(1, self.config.sleep_seconds))

    def close(self) -> None:
        if self._owns_stream and self.snapshot_stream:
            self.snapshot_stream.stop()
        if self._owns_live_stream and self.live_stream:
            try:
                self.live_stream.stop()
            except Exception:  # pragma: no cover - defensive cleanup
                pass

    def __del__(self) -> None:  # pragma: no cover - best effort cleanup
        try:
            self.close()
        except Exception:
            pass

    def _build_intent(self, context: StrategyContext) -> Optional[TradeIntent]:
        signal = self.strategy.generate_signal(context)
        if signal.direction == "NONE" or signal.confidence < self.config.min_confidence:
            return None
        entry_price = self._infer_entry_price(signal, context)
        if entry_price is None or entry_price <= 0:
            logger.debug("Skipping signal without price", ticker=context.ticker)
            return None
        option_symbol = self._option_symbol(context, signal.direction)
        order_mode = (self.config.option_order_mode or "auto").lower()
        spread_override: Optional[float] = None
        if order_mode == "cash_secured" and signal.direction == "PUT":
            entry_price, option_symbol, spread_override = self._maybe_select_affordable_put(
                context, entry_price, option_symbol
            )
        # DISABLED: option_is_tradable() check causes 10+ minute hangs
        # if option_symbol and not self.alpaca.option_is_tradable(option_symbol):
        #     fallback = self._first_tradable_option(context, signal.direction)
        #     if fallback:
        #         option_symbol, entry_price, spread_override = fallback
        #     else:
        #         logger.debug("Skipping non-tradable option", ticker=context.ticker, option=option_symbol)
        #         return None
        if not option_symbol:
            logger.debug("Skipping signal without option symbol", ticker=context.ticker, direction=signal.direction)
            return None

        # Always compute aggregate metadata for diagnostics, but only enforce aggregate
        # thresholds when explicitly enabled.
        agg_stats = self._aggregate_health(context, signal.direction)
        agg_vwap = self._aggregate_vwap_trend(context, signal.direction)
        if self.config.enable_option_aggregates and (
            agg_stats["bars"] < self.config.min_option_agg_bars
            or agg_stats["volume"] < self.config.min_option_agg_volume
            or abs(agg_vwap) < self.config.min_option_agg_vwap
        ):
            logger.debug(
                "Skipping signal due to insufficient option aggregate data",
                ticker=context.ticker,
                bars=agg_stats["bars"],
                volume=agg_stats["volume"],
                vwap=agg_vwap,
            )
            return None
        # DISABLED: option_is_tradable() check causes hangs
        # if option_symbol and not self.alpaca.option_is_tradable(option_symbol):
        #     logger.debug("Skipping non-tradable option", ticker=context.ticker, option=option_symbol)
        #     return None
        spread = spread_override if spread_override is not None else self._quote_spread(context, signal.direction)

        # Get liquidity - use fallback if aggregates disabled
        if self.config.enable_option_aggregates:
            available_volume = agg_stats["volume"]
        else:
            available_volume = 0  # Will trigger fallback_liquidity
        if available_volume <= 0:
            available_volume = self._fallback_liquidity(context, signal.direction, option_symbol)
        size = self.risk_manager.size_position(
            PositionSizingInput(
                account_equity=self.account_equity,
                trade_risk_fraction=self.config.trade_risk_fraction,
                contract_price=entry_price,
                confidence=signal.confidence,
                max_positions=self.config.max_positions,
                spread=spread,
                available_volume=available_volume,
            )
        )
        contract_strike = self._strike_from_symbol(option_symbol)
        if order_mode == "cash_secured":
            # For cash_secured mode, never switch to long - skip trade instead
            coverage = self._coverage_limit(context.ticker, signal.direction, contract_strike)
            if coverage <= 0:
                logger.debug(
                    "Insufficient coverage for cash-secured option; skipping trade",
                    ticker=context.ticker,
                    direction=signal.direction,
                    strike=contract_strike,
                    shares=self._get_underlying_shares(context.ticker),
                    equity=self.account_equity,
                )
                return None
            else:
                size = min(size, coverage)
        elif order_mode == "auto":
            # Auto mode can fall back to long if no coverage
            coverage = self._coverage_limit(context.ticker, signal.direction, contract_strike)
            if coverage <= 0:
                logger.debug(
                    "Insufficient coverage for short option; switching to long mode for this signal",
                    ticker=context.ticker,
                    direction=signal.direction,
                    strike=contract_strike,
                    shares=self._get_underlying_shares(context.ticker),
                    equity=self.account_equity,
                )
                order_mode = "long"
            else:
                size = min(size, coverage)
        if size <= 0:
            spread_pct = (spread / entry_price) if entry_price else None
            msg = (
                "No position sized "
                f"ticker={context.ticker} dir={signal.direction} conf={signal.confidence:.3f} "
                f"price={entry_price} spread={spread} spread_pct={spread_pct} "
                f"avail_vol={available_volume} min_liq={self.risk_manager.min_liquidity} "
                f"max_spread_pct={self.risk_manager.max_spread_pct} "
                f"risk_cap={self.account_equity * min(self.config.trade_risk_fraction, self.risk_manager.max_daily_loss_pct):.2f}"
            )
            logger.debug(msg)
            return None
        stop_price = self.risk_manager.stop_loss_price(entry_price, self.config.stop_loss_fraction)
        take_profit_price = signal.target_price
        if take_profit_price is None:
            take_profit_price = self.risk_manager.take_profit_price(
                entry_price,
                reward_multiplier=self.config.take_profit_reward,
                risk_fraction=self.config.stop_loss_fraction,
            )
        intent = TradeIntent(
            ticker=context.ticker,
            option_symbol=option_symbol,
            direction=signal.direction,
            quantity=size,
            entry_price=entry_price,
            confidence=signal.confidence,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
            metadata={
                **(signal.metadata or {}),
                "option_agg_bars": agg_stats["bars"],
                "option_agg_volume": agg_stats["volume"],
                "option_agg_vwap": agg_vwap,
                "option_spread": spread,
                "signal_target_price": signal.target_price,
                "stop_price": stop_price,
                "take_profit_price": take_profit_price,
                "account_equity": self.account_equity,
                "order_mode": order_mode,
            },
        )
        return intent

    def _execute_intent(self, intent: TradeIntent, context: Optional[StrategyContext] = None) -> Dict[str, Optional[str]]:
        if self.config.dry_run:
            logger.info(
                "DRY RUN order",
                ticker=intent.ticker,
                option=intent.option_symbol,
                direction=intent.direction,
                qty=intent.quantity,
                price=intent.entry_price,
                confidence=intent.confidence,
                take_profit=intent.take_profit_price,
                stop_loss=intent.stop_price,
            )
            return {"status": "DRY_RUN", "order_id": None}
        if not intent.option_symbol:
            logger.warning("Cannot place option order without symbol", ticker=intent.ticker)
            return {"status": "MISSING_SYMBOL", "order_id": None}

        # Validate account has options trading approval
        check_options_enabled = getattr(self.alpaca, "check_options_trading_enabled", None)
        if callable(check_options_enabled) and not check_options_enabled():
            error_msg = "Account not approved for options trading - check Alpaca account settings"
            logger.error(error_msg, ticker=intent.ticker)
            return {"status": "ERROR", "error": error_msg}

        mode = (intent.metadata or {}).get("order_mode") or (self.config.option_order_mode or "auto").lower()
        side = _direction_to_side(intent.direction, mode)
        position_intent = _direction_to_position_intent(intent.direction, mode)
        try:
            order_id = self.alpaca.submit_option_order(
                symbol=intent.option_symbol,
                quantity=intent.quantity,
                side=side,
                position_intent=position_intent,
                take_profit_price=intent.take_profit_price,
                stop_loss_price=intent.stop_price,
                limit_price=intent.entry_price,
            )
            logger.info("Submitted option order", order_id=order_id, symbol=intent.option_symbol)
            return {"status": "SUBMITTED", "order_id": order_id}
        except Exception as exc:
            logger.error("Failed to submit option order", symbol=intent.option_symbol, error=str(exc))
            return {"status": "ERROR", "error": str(exc)}

    def _infer_entry_price(self, signal: TradingSignal, context: StrategyContext) -> Optional[float]:
        if signal.entry_price:
            return signal.entry_price
        quote = context.option_quote
        if isinstance(quote, dict) and ("CALL" in quote or "PUT" in quote):
            quote = quote.get(signal.direction) or quote.get("CALL") or quote.get("PUT")
        if not isinstance(quote, dict):
            return None
        # Use .get() with default None to avoid issues with zero values being skipped
        bid = quote.get("bid")
        if bid is None:
            bid = quote.get("bid_price")
        ask = quote.get("ask")
        if ask is None:
            ask = quote.get("ask_price")
        try:
            bid_f = float(bid) if bid is not None else None
            ask_f = float(ask) if ask is not None else None
        except (TypeError, ValueError):
            return None
        if bid_f is None and ask_f is None:
            return None
        if bid_f is None:
            return ask_f
        if ask_f is None:
            return bid_f
        return (bid_f + ask_f) / 2

    def _quote_spread(self, context: StrategyContext, direction: str) -> float:
        quote = context.option_quote
        if isinstance(quote, dict):
            leg = quote.get(direction) or quote.get(direction.capitalize())
            if isinstance(leg, dict):
                bid = leg.get("bid") or leg.get("bid_price")
                ask = leg.get("ask") or leg.get("ask_price")
                try:
                    bid_f = float(bid) if bid is not None else None
                    ask_f = float(ask) if ask is not None else None
                except (TypeError, ValueError):
                    return 0.0
                if bid_f is None or ask_f is None:
                    return 0.0
                return max(0.0, ask_f - bid_f)
        return 0.0

    def _option_symbol(self, context: StrategyContext, direction: str) -> Optional[str]:
        quote = context.option_quote
        if not isinstance(quote, dict):
            return None
        leg = quote.get(direction) or quote.get(direction.capitalize())
        if isinstance(leg, dict):
            return leg.get("symbol")
        return None

    def _record_intent(self, intent: TradeIntent, result: Dict[str, Optional[str]]) -> None:
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "ticker": intent.ticker,
            "option_symbol": intent.option_symbol,
            "direction": intent.direction,
            "quantity": intent.quantity,
            "entry_price": intent.entry_price,
            "confidence": intent.confidence,
            "stop_price": intent.stop_price,
            "take_profit_price": intent.take_profit_price,
            "status": result.get("status"),
            "order_id": result.get("order_id"),
            "error": result.get("error"),  # Log error details for debugging
            "metadata": intent.metadata,
        }
        payload = orjson.dumps(entry, option=orjson.OPT_SERIALIZE_NUMPY)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("ab") as log_file:
            log_file.write(payload + b"\n")
        logger.debug("Intent recorded", status=entry["status"], option=intent.option_symbol)

    def _aggregate_health(self, context: StrategyContext, direction: str) -> Dict[str, float]:
        aggregates = context.option_aggregates or {}
        series = aggregates.get(direction) or []
        if not isinstance(series, list):
            return {"bars": 0, "volume": 0.0}
        bars = len(series)
        volume = 0.0
        window_size = self.config.min_option_agg_bars
        window = series[-window_size:] if window_size else series
        for bar in window:
            if isinstance(bar, dict):
                try:
                    volume += float(bar.get("volume") or 0.0)
                except (TypeError, ValueError):
                    continue
        return {"bars": bars, "volume": volume}

    def _aggregate_vwap_trend(self, context: StrategyContext, direction: str) -> float:
        aggregates = context.option_aggregates or {}
        series = aggregates.get(direction) or []
        if not isinstance(series, list) or len(series) < 2:
            return 0.0
        vwaps = [bar.get("vwap") for bar in series if isinstance(bar, dict) and bar.get("vwap") is not None]
        if len(vwaps) < 2:
            return 0.0
        try:
            start = float(vwaps[0])
            end = float(vwaps[-1])
        except (TypeError, ValueError):
            return 0.0
        if abs(start) < 1e-9:  # Protect against near-zero or zero division
            return 0.0
        return (end - start) / start

    def _fallback_liquidity(self, context: StrategyContext, direction: str, option_symbol: Optional[str]) -> float:
        """Estimate available volume when option aggregates are disabled or empty."""

        metrics = context.option_metrics or {}
        target_symbol = option_symbol or ""
        if isinstance(target_symbol, str) and target_symbol in metrics and isinstance(metrics[target_symbol], dict):
            direct = self._extract_liquidity(metrics[target_symbol])
            if direct is not None:
                return direct
        aggregated = 0.0
        for payload in metrics.values():
            if not isinstance(payload, dict):
                continue
            contract_type = str(payload.get("contract_type") or "").upper()
            if contract_type != direction.upper():
                continue
            liq = self._extract_liquidity(payload)
            if liq is not None:
                aggregated += liq
        if aggregated > 0:
            return aggregated
        quote = context.option_quote
        if isinstance(quote, dict):
            leg = quote.get(direction) or quote.get(direction.capitalize())
            liq = self._extract_liquidity(leg)
            if liq is not None:
                return liq
        return 0.0

    def _extract_liquidity(self, payload: Optional[Dict[str, Any]]) -> Optional[float]:
        if not isinstance(payload, dict):
            return None
        for key in ("open_interest", "bid_size", "ask_size", "volume", "size"):
            val = self._coerce_float(payload.get(key))
            if val is not None and val > 0:
                return val
        quote = payload.get("last_quote") if isinstance(payload, dict) else None
        if isinstance(quote, dict):
            for key in ("bid_size", "ask_size", "volume", "size"):
                val = self._coerce_float(quote.get(key))
                if val is not None and val > 0:
                    return val
        trade = payload.get("latest_trade") if isinstance(payload, dict) else None
        if isinstance(trade, dict):
            val = self._coerce_float(trade.get("size"))
            if val is not None and val > 0:
                return val
        return None

    def _strike_from_symbol(self, symbol: Optional[str]) -> Optional[float]:
        if not symbol or len(symbol) < 15:
            return None
        try:
            strike_part = symbol[-8:]
            return int(strike_part) / 1000.0
        except (ValueError, TypeError):
            return None

    def _infer_contract_type(self, symbol: Optional[str]) -> Optional[str]:
        if not symbol or len(symbol) < 15:
            return None
        flag = symbol[-9:-8].upper()
        if flag == "C":
            return "CALL"
        if flag == "P":
            return "PUT"
        return None

    def _get_underlying_shares(self, ticker: str) -> int:
        try:
            return max(0, int(self.alpaca.get_position_qty(ticker)))
        except Exception:
            return 0

    def _coverage_limit(self, ticker: str, direction: str, strike: Optional[float]) -> int:
        direction = direction.upper()
        if direction == "CALL":
            shares = self._get_underlying_shares(ticker)
            return shares // 100
        if direction == "PUT":
            if strike is None or strike <= 0:
                return 0
            collateral_per_contract = strike * 100.0
            if collateral_per_contract <= 0:
                return 0
            return int(self.account_equity // collateral_per_contract)
        return 0

    def _coerce_float(self, value: Any) -> Optional[float]:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _affordable_put_candidates(self, context: StrategyContext) -> list[Dict[str, Any]]:
        """Return sorted affordable put candidates, preferring Alpaca tradable contracts."""

        max_strike = self.account_equity / 100.0 if self.account_equity > 0 else 0.0
        candidates: list[Dict[str, Any]] = []

        def _add(symbol: str, strike: float, mid: float, spread: float, exp: Optional[datetime], source: str) -> None:
            if strike <= 0 or strike > max_strike:
                return
            candidates.append(
                {
                    "symbol": symbol,
                    "strike": strike,
                    "price": mid,
                    "spread": spread,
                    "exp": exp or datetime.max,
                    "source": source,
                }
            )

        option_chain = context.option_chain
        chain_items = []
        if isinstance(option_chain, dict):
            chain_items = list(option_chain.values())
        elif isinstance(option_chain, list):
            chain_items = option_chain
        fallback_contract: Optional[Dict[str, Any]] = None
        for contract in chain_items:
            if not isinstance(contract, dict):
                continue
            symbol = str(contract.get("symbol") or "")
            if not symbol:
                continue
            if self._infer_contract_type(symbol) != "PUT":
                continue
            exp = self._parse_expiration(contract.get("expiration_date"))
            strike_val = contract.get("strike") or contract.get("strike_price")
            try:
                strike_f = float(strike_val)
            except (TypeError, ValueError):
                strike_f = self._strike_from_symbol(symbol)
            if strike_f is None or strike_f <= 0:
                continue
            if strike_f > max_strike:
                if fallback_contract is None or strike_f < fallback_contract["strike"]:
                    fallback_contract = {"exp": exp, "strike": strike_f, "symbol": symbol, "contract": contract}
                continue
            quote = contract.get("latest_quote") or contract.get("quote") or {}
            bid = self._coerce_float(quote.get("bid_price") or quote.get("bid"))
            ask = self._coerce_float(quote.get("ask_price") or quote.get("ask"))
            if ask is None or ask <= 0:
                continue
            mid = (bid + ask) / 2 if bid is not None else ask
            spread = (ask - bid) if (bid is not None and bid >= 0) else 0.0
            if self.alpaca.option_is_tradable(symbol):
                _add(symbol, strike_f, mid, spread, exp, "chain")

        metrics = context.option_metrics or {}
        for symbol, payload in metrics.items():
            if not isinstance(payload, dict):
                continue
            if str(payload.get("contract_type") or "").upper() != "PUT":
                continue
            strike_f = self._coerce_float(payload.get("strike_price") or payload.get("strike")) or self._strike_from_symbol(symbol)
            if strike_f is None or strike_f <= 0 or strike_f > max_strike:
                continue
            exp = self._parse_expiration(payload.get("expiration_date"))
            occ_symbol = self._occ_symbol(context.ticker, payload.get("expiration_date"), "P", strike_f)
            sym_out = occ_symbol or (symbol.lstrip("O:") if isinstance(symbol, str) else symbol)
            quote = payload.get("last_quote") or {}
            bid = self._coerce_float(quote.get("bid_price") or quote.get("bid"))
            ask = self._coerce_float(quote.get("ask_price") or quote.get("ask"))
            if ask is None or ask <= 0:
                continue
            mid = (bid + ask) / 2 if bid is not None else ask
            spread = (ask - bid) if (bid is not None and bid >= 0) else 0.0
            if self.alpaca.option_is_tradable(sym_out):
                _add(sym_out, strike_f, mid, spread, exp, "metrics")

        candidates.sort(key=lambda c: (c["exp"], -c["strike"], c["spread"]))
        if not candidates and fallback_contract is not None:
            contract = fallback_contract["contract"]
            quote = contract.get("latest_quote") or contract.get("quote") or {}
            bid = self._coerce_float(quote.get("bid_price") or quote.get("bid"))
            ask = self._coerce_float(quote.get("ask_price") or quote.get("ask"))
            if ask is not None and ask > 0:
                mid = (bid + ask) / 2 if bid is not None else ask
                spread = (ask - bid) if (bid is not None and bid >= 0) else 0.0
                sym = fallback_contract["symbol"]
                if self.alpaca.option_is_tradable(sym):
                    _add(sym, fallback_contract["strike"], mid, spread, fallback_contract["exp"], "chain_fallback")
        return candidates

    def _maybe_select_affordable_put(
        self,
        context: StrategyContext,
        current_price: Optional[float],
        current_symbol: Optional[str],
    ) -> tuple[Optional[float], Optional[str], Optional[float]]:
        """If the selected put is unaffordable, pick the highest strike within collateral."""

        candidates = self._affordable_put_candidates(context)
        if not candidates:
            return current_price, current_symbol, None
        top = candidates[0]
        return top["price"], top["symbol"], top["spread"]

    def _maybe_close_positions(self) -> None:
        """Attempt to close open option positions when stop/target are hit."""

        try:
            positions = self.alpaca.get_open_positions()
        except Exception as exc:  # pragma: no cover - dependency failure path
            logger.warning("Failed to fetch open positions", error=str(exc))
            return

        levels_cache: dict[str, tuple[Optional[float], Optional[float]]] = {}
        for pos in positions:
            try:
                if getattr(pos, "asset_class", "").lower() != "option":
                    continue
                symbol = getattr(pos, "symbol", None)
                if not symbol:
                    continue
                qty_raw = getattr(pos, "qty", getattr(pos, "quantity", None))
                side_raw = getattr(pos, "side", "").lower()
                try:
                    qty = abs(int(float(qty_raw)))
                except Exception:
                    continue
                if qty <= 0:
                    continue
                if symbol not in levels_cache:
                    levels_cache[symbol] = self._lookup_exit_levels(symbol)
                stop_price, tp_price = levels_cache[symbol]
                if stop_price is None and tp_price is None:
                    continue
                mid = self._latest_option_mid(symbol)
                if mid is None:
                    continue
                should_close = False
                if side_raw == "short":
                    if tp_price is not None and mid <= tp_price:
                        should_close = True
                    if stop_price is not None and mid >= stop_price:
                        should_close = True
                else:  # treat others as long
                    if tp_price is not None and mid >= tp_price:
                        should_close = True
                    if stop_price is not None and mid <= stop_price:
                        should_close = True
                if not should_close:
                    continue
                side, intent = _closing_order_params(side_raw)
                try:
                    order_id = self.alpaca.submit_option_order(
                        symbol=symbol,
                        quantity=qty,
                        side=side,
                        position_intent=intent,
                    )
                    logger.info("Submitted exit order", symbol=symbol, qty=qty, side=side, intent=intent, order_id=order_id)
                except Exception as exc:  # pragma: no cover - broker failure
                    logger.error("Failed to submit exit order", symbol=symbol, error=str(exc))
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Exit monitor issue", error=str(exc))

    def _latest_option_mid(self, symbol: str) -> Optional[float]:
        try:
            quote = self.alpaca.fetch_option_latest_quote(symbol)
        except Exception:
            return None
        if hasattr(quote, "latest_quote"):
            quote = getattr(quote, "latest_quote")
        if hasattr(quote, "dict"):
            quote = quote.dict()
        if isinstance(quote, dict):
            bid = self._coerce_float(quote.get("bid_price") or quote.get("bid"))
            ask = self._coerce_float(quote.get("ask_price") or quote.get("ask"))
            if bid is None and ask is None:
                return None
            if bid is None:
                return ask
            if ask is None:
                return bid
            return (bid + ask) / 2
        return None

    def _first_tradable_option(
        self, context: StrategyContext, direction: str
    ) -> Optional[tuple[str, Optional[float], Optional[float]]]:
        """Find the first tradable option for the given direction from Alpaca chain."""

        chain = context.option_chain
        contracts = []
        if isinstance(chain, dict):
            contracts = list(chain.values())
        elif isinstance(chain, list):
            contracts = chain
        for contract in contracts:
            if not isinstance(contract, dict):
                continue
            symbol = contract.get("symbol")
            if not symbol or self._infer_contract_type(symbol) != direction.upper():
                continue
            if not self.alpaca.option_is_tradable(symbol):
                continue
            quote = contract.get("latest_quote") or contract.get("quote") or {}
            bid = self._coerce_float(quote.get("bid_price") or quote.get("bid"))
            ask = self._coerce_float(quote.get("ask_price") or quote.get("ask"))
            if bid is None and ask is None:
                continue
            if bid is None:
                price = ask
            elif ask is None:
                price = bid
            else:
                price = (bid + ask) / 2
            spread = (ask - bid) if (bid is not None and ask is not None) else None
            return symbol, price, spread
        return None

    def _lookup_exit_levels(self, symbol: str) -> tuple[Optional[float], Optional[float]]:
        """Parse recent log entries to recover stop/take-profit for a symbol."""

        stop = None
        take_profit = None
        log_path = Path(self.log_path)
        if not log_path.exists():
            return stop, take_profit
        try:
            lines = deque(log_path.open("rb"), maxlen=max(self.config.exit_log_scan_lines, 10))
        except Exception:
            return stop, take_profit
        for raw in reversed(lines):
            try:
                entry = orjson.loads(raw)
            except Exception:
                continue
            if entry.get("option_symbol") != symbol:
                continue
            stop_val = entry.get("stop_price")
            tp_val = entry.get("take_profit_price")
            try:
                if stop_val is not None:
                    stop = float(stop_val)
                if tp_val is not None:
                    take_profit = float(tp_val)
            except (TypeError, ValueError):
                pass
            if stop is not None or take_profit is not None:
                break
        return stop, take_profit

    def _occ_symbol(
        self,
        ticker: str,
        expiration: Any,
        contract_type: str,
        strike: float,
    ) -> Optional[str]:
        try:
            if isinstance(expiration, str):
                exp_dt = datetime.fromisoformat(expiration.replace("Z", "+00:00"))
            elif isinstance(expiration, datetime):
                exp_dt = expiration
            else:
                return None
            yy = exp_dt.strftime("%y")
            mm = exp_dt.strftime("%m")
            dd = exp_dt.strftime("%d")
            flag = "C" if contract_type.upper().startswith("C") else "P"
            strike_int = int(round(float(strike) * 1000))
            strike_part = f"{strike_int:08d}"
            return f"{ticker.upper()}{yy}{mm}{dd}{flag}{strike_part}"
        except Exception:
            return None

    def _parse_expiration(self, value: Any) -> Optional[datetime]:
        try:
            if value is None:
                return None
            if isinstance(value, datetime):
                return value
            if isinstance(value, str):
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None
        return None

    def _fetch_snapshot(self) -> Dict[str, Any]:
        if self.snapshot_stream:
            if self.config.stream_force_refresh:
                try:
                    return self._merge_live_bars(self.snapshot_stream.refresh_now())
                except Exception as exc:  # pragma: no cover - network failure path
                    logger.warning("Snapshot stream refresh failed", error=str(exc))
            snapshot = self.snapshot_stream.latest_snapshot()
            if snapshot:
                return self._merge_live_bars(snapshot)
            try:
                return self._merge_live_bars(self.snapshot_stream.refresh_now())
            except Exception as exc:  # pragma: no cover - network failure path
                logger.warning("Snapshot stream refresh failed", error=str(exc))
        snapshot = self.pipeline.collect_market_snapshot(
            lookback=timedelta(minutes=self.config.lookback_minutes),
            news_lookback=timedelta(hours=self.config.news_hours),
            timeframe=self.config.timeframe,
            use_cache=self.config.use_cache,
            include_news=self.config.include_news,
        )
        return self._merge_live_bars(snapshot)

    def _update_account_equity(self) -> None:
        try:
            equity = float(self.alpaca.get_options_buying_power())
        except Exception as exc:  # pragma: no cover - dependency failure path
            logger.warning("Failed to refresh account equity; using last known value", error=str(exc))
            return
        if equity > 0:
            self.account_equity = equity
            logger.debug("Account equity refreshed", equity=equity)

    # ------------------------------------------------------------------- live bars

    def _merge_live_bars(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        if not self.live_stream:
            return snapshot
        latest = self.live_stream.latest_bars()
        if not latest:
            return snapshot
        for ticker, bar in latest.items():
            if ticker not in snapshot:
                continue
            bar_row = self._normalize_live_bar(bar)
            if not bar_row:
                continue
            existing = snapshot[ticker].get("underlying_bars")
            if isinstance(existing, pd.DataFrame):
                if not existing.empty and "timestamp" in existing.columns:
                    if str(bar_row["timestamp"]) in set(existing["timestamp"].astype(str)):
                        continue
                new_df = pd.DataFrame([bar_row])
                snapshot[ticker]["underlying_bars"] = pd.concat([existing, new_df], ignore_index=True)
            elif isinstance(existing, list):
                if any(str(item.get("timestamp")) == str(bar_row["timestamp"]) for item in existing):
                    continue
                snapshot[ticker]["underlying_bars"] = existing + [bar_row]
            else:
                snapshot[ticker]["underlying_bars"] = [bar_row]
        return snapshot

    def _normalize_live_bar(self, bar: Any) -> Optional[Dict[str, Any]]:
        if bar is None:
            return None
        if hasattr(bar, "model_dump"):
            payload = bar.model_dump()
        elif isinstance(bar, dict):
            payload = dict(bar)
        elif hasattr(bar, "__dict__"):
            payload = dict(bar.__dict__)
        else:
            return None
        ts = payload.get("timestamp") or payload.get("t")
        if hasattr(ts, "isoformat"):
            ts = ts.isoformat()
        if ts is None:
            return None
        try:
            open_p = float(payload.get("open") or payload.get("o"))
            high = float(payload.get("high") or payload.get("h"))
            low = float(payload.get("low") or payload.get("l"))
            close = float(payload.get("close") or payload.get("c"))
            volume = float(payload.get("volume") or payload.get("v") or 0.0)
        except (TypeError, ValueError):
            return None
        return {
            "timestamp": ts,
            "open": open_p,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }


def _direction_to_side(direction: str, order_mode: str):
    from alpaca.trading.enums import OrderSide

    if order_mode == "long":
        return OrderSide.BUY
    return OrderSide.SELL


def _direction_to_position_intent(direction: str, order_mode: str):
    from alpaca.trading.enums import PositionIntent

    if order_mode == "long":
        return PositionIntent.BUY_TO_OPEN
    return PositionIntent.SELL_TO_OPEN


def _closing_order_params(position_side: str):
    from alpaca.trading.enums import OrderSide, PositionIntent

    if position_side.lower() == "short":
        return OrderSide.BUY, PositionIntent.BUY_TO_CLOSE
    return OrderSide.SELL, PositionIntent.SELL_TO_CLOSE
