"""Momentum + Implied Volatility strategy scaffold."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from trading_ai.strategies.base import StrategyContext, TradingSignal, TradingStrategy


@dataclass
class MomentumIVConfig:
    lookback_minutes: int = 60
    momentum_threshold: float = 0.0015  # 0.15% to fire in quiet sessions
    feature_momentum_key: str = "momentum_15"
    alt_feature_momentum_key: str = "momentum_60"
    iv_squeeze_threshold: float = -0.05  # 5% drop vs. rolling IV mean
    max_confidence: float = 0.9
    baseline_confidence: float = 0.35
    option_flow_threshold: float = 0.2
    momentum_weight: float = 0.4
    iv_weight: float = 0.25
    news_weight: float = 0.2
    option_flow_weight: float = 0.15


class MomentumIVStrategy(TradingStrategy):
    """Blend of intraday momentum and IV crush detection."""

    name = "momentum_iv"

    def __init__(self, config: Optional[MomentumIVConfig] = None) -> None:
        self.config = config or MomentumIVConfig()

    def _compute_momentum(self, bars: pd.DataFrame) -> float:
        if bars.empty:
            return 0.0
        close = bars["close"].astype(float)
        window = close.tail(self.config.lookback_minutes)
        if len(window) < 2:
            return 0.0
        return (window.iloc[-1] - window.iloc[0]) / window.iloc[0]

    def _momentum_from_features(self, features: Optional[Dict[str, Any]]) -> float:
        if not features:
            return 0.0
        for key in (self.config.feature_momentum_key, self.config.alt_feature_momentum_key):
            value = features.get(key)
            if value is None:
                continue
            try:
                momentum = float(value)
            except (TypeError, ValueError):
                continue
            if momentum:
                return momentum
        return 0.0

    def _momentum_from_quotes(self, option_quote: Optional[Dict[str, Any]]) -> float:
        if not isinstance(option_quote, dict):
            return 0.0
        call = option_quote.get("CALL") or option_quote.get("call")
        put = option_quote.get("PUT") or option_quote.get("put")
        call_mid = self._quote_mid(call)
        put_mid = self._quote_mid(put)
        if call_mid is None or put_mid is None:
            return 0.0
        total = call_mid + put_mid
        if total <= 0:
            return 0.0
        return (call_mid - put_mid) / total

    def _quote_mid(self, quote: Optional[Dict[str, Any]]) -> Optional[float]:
        if not isinstance(quote, dict):
            return None
        bid = quote.get("bid") or quote.get("bid_price")
        ask = quote.get("ask") or quote.get("ask_price")
        try:
            bid = float(bid) if bid is not None else None
            ask = float(ask) if ask is not None else None
        except (TypeError, ValueError):
            return None
        if bid is None and ask is None:
            return None
        if bid is None:
            return ask
        if ask is None:
            return bid
        return (bid + ask) / 2

    def _extract_iv_metrics(self, option_chain: Dict, option_metrics: Dict[str, Any] | None = None) -> Dict[str, float]:
        if not option_chain:
            return {"avg_iv": np.nan, "iv_change": np.nan}
        ivs = []
        iv_changes = []
        for leg in option_chain if isinstance(option_chain, list) else option_chain.values():
            if isinstance(leg, dict):
                iv = leg.get("implied_volatility")
                if iv is not None:
                    ivs.append(float(iv))
                iv_change = leg.get("iv_change")
                if iv_change is not None:
                    iv_changes.append(float(iv_change))
        if option_metrics:
            for payload in option_metrics.values():
                iv = payload.get("implied_volatility")
                if iv is not None:
                    ivs.append(float(iv))
                greeks = payload.get("greeks") or {}
                iv_change = greeks.get("vega")  # proxy if explicit iv change missing
                if iv_change is not None:
                    iv_changes.append(float(iv_change))
        return {
            "avg_iv": float(np.nanmean(ivs)) if ivs else np.nan,
            "iv_change": float(np.nanmean(iv_changes)) if iv_changes else np.nan,
        }

    def _determine_direction(self, momentum: float, iv_change: float, flow_bias: float) -> str:
        effective_threshold = self.config.momentum_threshold
        if np.isnan(iv_change):
            effective_threshold *= 0.5  # relax requirement when IV data is sparse
        if momentum > effective_threshold and iv_change <= self.config.iv_squeeze_threshold:
            return "CALL"
        if momentum < -effective_threshold and iv_change >= -self.config.iv_squeeze_threshold:
            return "PUT"
        if momentum > effective_threshold:
            return "CALL"
        if momentum < -effective_threshold:
            return "PUT"
        if abs(flow_bias) >= self.config.option_flow_threshold:
            return "CALL" if flow_bias > 0 else "PUT"
        return "NONE"

    def _confidence_score(self, momentum: float, iv_change: float, news_bias: float, flow_bias: float) -> float:
        momentum_score = min(abs(momentum) / (self.config.momentum_threshold * 2), 1.0)
        iv_score = 0.0 if np.isnan(iv_change) else min(abs(iv_change) / 0.1, 1.0)
        flow_score = min(abs(flow_bias), 1.0)
        weights = (
            self.config.momentum_weight,
            self.config.iv_weight,
            self.config.news_weight,
            self.config.option_flow_weight,
        )
        total_weight = sum(weights) or 1.0
        raw = (
            weights[0] * momentum_score
            + weights[1] * iv_score
            + weights[2] * news_bias
            + weights[3] * flow_score
        ) / total_weight
        baseline = self.config.baseline_confidence / self.config.max_confidence
        raw = max(baseline, raw)
        return max(0.0, min(raw * self.config.max_confidence, self.config.max_confidence))

    def _news_bias(self, news_items: list[dict]) -> float:
        if not news_items:
            return 0.5
        positive = 0
        negative = 0
        for article in news_items:
            summary = str(article.get("description") or article.get("title") or "").lower()
            if any(keyword in summary for keyword in ("beats", "surge", "upgrade", "positive")):
                positive += 1
            if any(keyword in summary for keyword in ("misses", "downgrade", "negative", "lawsuit")):
                negative += 1
        total = positive + negative
        if total == 0:
            return 0.5
        return max(0.0, min(positive / total, 1.0))

    def _option_flow_metrics(
        self,
        option_metrics: Optional[Dict[str, Any]],
        option_chain: Optional[Dict[str, Any]],
    ) -> Dict[str, float]:
        call_oi = 0.0
        put_oi = 0.0
        call_delta = 0.0
        put_delta = 0.0

        def _ingest(source: Optional[Any]) -> None:
            nonlocal call_oi, put_oi, call_delta, put_delta
            if not source:
                return
            if isinstance(source, dict):
                iterable = source.values()
            elif isinstance(source, list):
                iterable = source
            else:
                return
            for payload in iterable:
                if not isinstance(payload, dict):
                    continue
                contract_type = str(payload.get("contract_type") or "").upper()
                if not contract_type:
                    contract_type = self._infer_contract_type(payload.get("symbol"))
                if contract_type not in {"CALL", "PUT"}:
                    continue
                open_interest = self._coerce_float(payload.get("open_interest"))
                if open_interest is None or open_interest < 0:
                    open_interest = self._estimate_liquidity(payload)
                greeks = payload.get("greeks") or {}
                delta = self._coerce_float(greeks.get("delta")) or 0.0
                weight = open_interest if open_interest and open_interest > 0 else abs(delta)
                if weight is None or weight <= 0:
                    continue
                if contract_type == "CALL":
                    call_oi += weight
                    call_delta += delta * weight
                else:
                    put_oi += weight
                    put_delta += delta * weight

        _ingest(option_metrics)
        if call_oi + put_oi == 0:
            _ingest(option_chain)

        total_weight = call_oi + put_oi
        if total_weight > 0:
            flow_ratio = (call_oi - put_oi) / total_weight
            aggregated_delta = (call_delta + put_delta) / total_weight
        else:
            flow_ratio = 0.0
            aggregated_delta = 0.0
        flow_ratio = max(-1.0, min(flow_ratio, 1.0))
        aggregated_delta = max(-1.0, min(aggregated_delta, 1.0))
        return {
            "call_open_interest": call_oi,
            "put_open_interest": put_oi,
            "flow_ratio": flow_ratio,
            "delta_bias": aggregated_delta,
        }

    def _coerce_float(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _estimate_liquidity(self, payload: Dict[str, Any]) -> Optional[float]:
        quote = payload.get("latest_quote") or {}
        bid_size = self._coerce_float(quote.get("bid_size"))
        ask_size = self._coerce_float(quote.get("ask_size"))
        volume = self._coerce_float((payload.get("latest_trade") or {}).get("size"))
        estimate = max(bid_size or 0.0, ask_size or 0.0, volume or 0.0)
        return estimate if estimate > 0 else None

    def _infer_contract_type(self, symbol: Any) -> Optional[str]:
        if not isinstance(symbol, str) or len(symbol) < 15:
            return None
        flag = symbol[-9:-8].upper()
        if flag == "C":
            return "CALL"
        if flag == "P":
            return "PUT"
        return None

    def generate_signal(self, context: StrategyContext) -> TradingSignal:
        bars = context.underlying_bars
        momentum = self._compute_momentum(bars)
        if abs(momentum) < self.config.momentum_threshold:
            fallback_momentum = self._momentum_from_features(context.features)
            if abs(fallback_momentum) > abs(momentum):
                momentum = fallback_momentum
        if abs(momentum) < self.config.momentum_threshold:
            quote_momentum = self._momentum_from_quotes(context.option_quote)
            if abs(quote_momentum) > abs(momentum):
                momentum = quote_momentum
        iv_metrics = self._extract_iv_metrics(context.option_chain, context.option_metrics)
        iv_change = iv_metrics["iv_change"]
        flow_metrics = self._option_flow_metrics(context.option_metrics, context.option_chain)
        flow_bias = flow_metrics["flow_ratio"]
        if abs(flow_metrics["delta_bias"]) > abs(flow_bias):
            flow_bias = flow_metrics["delta_bias"]
        direction = self._determine_direction(momentum, iv_change, flow_bias)
        news_bias = self._news_bias(context.news_items)
        confidence = self._confidence_score(momentum, iv_change, news_bias, flow_bias)

        signal = TradingSignal(
            ticker=context.ticker,
            direction=direction,
            confidence=confidence,
            metadata={
                "momentum": momentum,
                "avg_iv": iv_metrics["avg_iv"],
                "iv_change": iv_change,
                "news_bias": news_bias,
                "flow_ratio": flow_metrics["flow_ratio"],
                "delta_bias": flow_metrics["delta_bias"],
            },
        )
        return signal
