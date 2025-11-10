"""Lightweight service to collect snapshots, score signals, and submit orders."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import orjson
from loguru import logger

from trading_ai.backtest.data_loader import contexts_from_snapshot
from trading_ai.clients import AlpacaClient
from trading_ai.core.pipeline import SignalPipeline
from trading_ai.risk.manager import PositionSizingInput, RiskManager
from trading_ai.settings import Settings
from trading_ai.strategies.base import StrategyContext, TradingSignal
from trading_ai.strategies.momentum_iv import MomentumIVStrategy


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


@dataclass
class TradeIntent:
    """Represents a pending order derived from a signal."""

    ticker: str
    option_symbol: Optional[str]
    direction: str
    quantity: int
    entry_price: float
    confidence: float
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
    ) -> None:
        self.settings = settings
        self.pipeline = pipeline or SignalPipeline(settings)
        self.strategy = strategy or MomentumIVStrategy()
        self.risk_manager = risk_manager or RiskManager()
        self.alpaca = alpaca_client or AlpacaClient(settings)
        self.config = config or AutoTraderConfig()
        self.log_path = Path(self.config.log_path).expanduser()

    def run_once(self) -> List[TradeIntent]:
        """Collect the latest snapshot, score signals, and optionally place orders."""

        logger.info(
            "AutoTrader cycle starting",
            lookback=self.config.lookback_minutes,
            news=self.config.news_hours,
            timeframe=self.config.timeframe,
        )
        snapshot = self.pipeline.collect_market_snapshot(
            lookback=timedelta(minutes=self.config.lookback_minutes),
            news_lookback=timedelta(hours=self.config.news_hours),
            timeframe=self.config.timeframe,
            use_cache=self.config.use_cache,
            include_news=self.config.include_news,
        )
        contexts = contexts_from_snapshot(snapshot)
        intents: List[TradeIntent] = []
        for context in contexts:
            intent = self._build_intent(context)
            if intent:
                intents.append(intent)
                result = self._execute_intent(intent)
                self._record_intent(intent, result)
        logger.info("AutoTrader cycle completed", intents=len(intents))
        return intents

    def run_loop(self) -> None:
        """Continuously run until interrupted."""

        while True:
            self.run_once()
            time.sleep(max(1, self.config.sleep_seconds))

    def _build_intent(self, context: StrategyContext) -> Optional[TradeIntent]:
        signal = self.strategy.generate_signal(context)
        if signal.direction == "NONE" or signal.confidence < self.config.min_confidence:
            return None
        entry_price = self._infer_entry_price(signal, context)
        if entry_price is None or entry_price <= 0:
            logger.debug("Skipping signal without price", ticker=context.ticker)
            return None
        size = self.risk_manager.size_position(
            PositionSizingInput(
                account_equity=self.config.account_equity,
                trade_risk_fraction=self.config.trade_risk_fraction,
                contract_price=entry_price,
                confidence=signal.confidence,
                max_positions=self.config.max_positions,
            )
        )
        if size <= 0:
            return None
        option_symbol = self._option_symbol(context, signal.direction)
        agg_stats = self._aggregate_health(context, signal.direction)
        agg_vwap = self._aggregate_vwap_trend(context, signal.direction)
        if (
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
        intent = TradeIntent(
            ticker=context.ticker,
            option_symbol=option_symbol,
            direction=signal.direction,
            quantity=size,
            entry_price=entry_price,
            confidence=signal.confidence,
            metadata={
                **(signal.metadata or {}),
                "option_agg_bars": agg_stats["bars"],
                "option_agg_volume": agg_stats["volume"],
                "option_agg_vwap": agg_vwap,
            },
        )
        return intent

    def _execute_intent(self, intent: TradeIntent) -> Dict[str, Optional[str]]:
        if self.config.dry_run:
            logger.info(
                "DRY RUN order",
                ticker=intent.ticker,
                option=intent.option_symbol,
                direction=intent.direction,
                qty=intent.quantity,
                price=intent.entry_price,
                confidence=intent.confidence,
            )
            return {"status": "DRY_RUN", "order_id": None}
        if not intent.option_symbol:
            logger.warning("Cannot place option order without symbol", ticker=intent.ticker)
            return {"status": "MISSING_SYMBOL", "order_id": None}
        side = _direction_to_side(intent.direction)
        position_intent = _direction_to_position_intent(intent.direction)
        order_id = self.alpaca.submit_option_order(
            symbol=intent.option_symbol,
            quantity=intent.quantity,
            side=side,
            position_intent=position_intent,
        )
        logger.info("Submitted option order", order_id=order_id, symbol=intent.option_symbol)
        return {"status": "SUBMITTED", "order_id": order_id}

    def _infer_entry_price(self, signal: TradingSignal, context: StrategyContext) -> Optional[float]:
        if signal.entry_price:
            return signal.entry_price
        quote = context.option_quote
        if isinstance(quote, dict) and ("CALL" in quote or "PUT" in quote):
            quote = quote.get(signal.direction) or quote.get("CALL") or quote.get("PUT")
        if not isinstance(quote, dict):
            return None
        bid = quote.get("bid") or quote.get("bid_price")
        ask = quote.get("ask") or quote.get("ask_price")
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
            "status": result.get("status"),
            "order_id": result.get("order_id"),
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
        for bar in series[-self.config.min_option_agg_bars or len(series) :]:
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
        if start == 0:
            return 0.0
        return (end - start) / start


def _direction_to_side(direction: str):
    from alpaca.trading.enums import OrderSide

    return OrderSide.BUY if direction.upper() in {"CALL", "PUT"} else OrderSide.BUY


def _direction_to_position_intent(direction: str):
    from alpaca.trading.enums import PositionIntent

    return PositionIntent.BUY_TO_OPEN
