"""Thin wrapper around Alpaca's live market data stream for equities."""

from __future__ import annotations

import threading
from typing import Any, Dict, Iterable, Optional

from alpaca.data.live import StockDataStream
from loguru import logger

from trading_ai.settings import Settings


class AlpacaStream:
    """Manages a background StockDataStream and exposes latest bars."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        feed = (settings.alpaca_data_feed or "IEX").lower()
        self._stream = StockDataStream(
            api_key=settings.alpaca_api_key_id,
            secret_key=settings.alpaca_api_secret_key,
            feed=feed,
        )
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._latest_bars: Dict[str, Dict[str, Any]] = {}
        self._running = False

    # ------------------------------------------------------------------ lifecycle

    def start(self, tickers: Iterable[str]) -> None:
        """Subscribe to live bars for the given tickers and start the stream."""

        symbols = [str(t).upper() for t in tickers]
        if not symbols:
            logger.debug("No tickers provided for live stream; skipping start")
            return
        if self._running:
            return

        async def _on_bar(bar: Any) -> None:
            data = self._normalize_payload(bar)
            symbol = data.get("symbol")
            if not symbol:
                return
            with self._lock:
                self._latest_bars[symbol] = data

        # Register subscriptions before running the stream.
        try:
            self._stream.subscribe_bars(_on_bar, *symbols)
        except Exception as exc:  # pragma: no cover - dependency failure path
            logger.warning("Failed to subscribe to Alpaca bars", error=str(exc))
            return

        def _run() -> None:
            try:
                self._stream.run()
            except Exception as exc:  # pragma: no cover - dependency failure path
                logger.warning("Alpaca live stream stopped unexpectedly", error=str(exc))

        self._thread = threading.Thread(target=_run, name="AlpacaStream", daemon=True)
        self._thread.start()
        self._running = True
        logger.info("Alpaca live stream started", tickers=symbols, feed=self._settings.alpaca_data_feed)

    def stop(self) -> None:
        """Stop the stream if it is running."""

        if not self._running:
            return
        try:
            self._stream.stop()
        except Exception:  # pragma: no cover - defensive
            pass
        if self._thread:
            self._thread.join(timeout=2)
        self._running = False
        logger.info("Alpaca live stream stopped")

    # ------------------------------------------------------------------- accessors

    def latest_bars(self) -> Dict[str, Dict[str, Any]]:
        """Return a shallow copy of the latest bar per ticker."""

        with self._lock:
            return dict(self._latest_bars)

    # ------------------------------------------------------------------- helpers

    def _normalize_payload(self, bar: Any) -> Dict[str, Any]:
        if hasattr(bar, "model_dump"):
            payload = bar.model_dump()
        elif hasattr(bar, "__dict__"):
            payload = dict(bar.__dict__)
        elif isinstance(bar, dict):
            payload = dict(bar)
        else:
            payload = {"raw": bar}
        symbol = payload.get("symbol") or payload.get("S")
        if symbol:
            payload["symbol"] = str(symbol)
        ts = payload.get("timestamp") or payload.get("t")
        if hasattr(ts, "isoformat"):
            ts = ts.isoformat()
        if ts:
            payload["timestamp"] = ts
        return payload

