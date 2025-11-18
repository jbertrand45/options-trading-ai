"""Background snapshot refresh service for near-real-time automation."""

from __future__ import annotations

import copy
import threading
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable, Dict, Iterable, Optional, Sequence

from loguru import logger

from trading_ai.core.pipeline import SignalPipeline

Snapshot = Dict[str, Any]
SnapshotCallback = Callable[[Snapshot], None]


@dataclass
class SnapshotStreamConfig:
    """Configuration knobs for the streaming snapshot buffer."""

    lookback_minutes: int = 120
    news_hours: int = 3
    timeframe: str = "1Min"
    include_news: bool = True
    use_cache: bool = False
    interval_seconds: float = 60.0
    tickers: Optional[Iterable[str]] = None


class SnapshotStream:
    """Keeps a rolling snapshot updated on a timer for downstream consumers."""

    def __init__(
        self,
        pipeline: SignalPipeline,
        *,
        config: Optional[SnapshotStreamConfig] = None,
    ) -> None:
        self.pipeline = pipeline
        self.config = config or SnapshotStreamConfig()
        self._tickers: Optional[Sequence[str]] = (
            tuple(self.config.tickers) if self.config.tickers is not None else None
        )
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._callbacks: list[SnapshotCallback] = []
        self._latest_snapshot: Optional[Snapshot] = None
        self._last_updated: Optional[float] = None

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        """Start the background refresh loop."""

        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="SnapshotStream", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the background refresh loop."""

        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None

    def __enter__(self) -> "SnapshotStream":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()

    # ------------------------------------------------------------------- callbacks

    def subscribe(self, callback: SnapshotCallback) -> None:
        """Register a callback invoked after each refresh (best-effort)."""

        with self._lock:
            self._callbacks.append(callback)

    # -------------------------------------------------------------------- snapshots

    def latest_snapshot(self) -> Snapshot:
        """Return the most recent snapshot (empty dict if none captured yet)."""

        with self._lock:
            snapshot = copy.deepcopy(self._latest_snapshot) if self._latest_snapshot is not None else None
        return snapshot or {}

    def refresh_now(self) -> Snapshot:
        """Synchronously capture a new snapshot."""

        snapshot = self.pipeline.collect_market_snapshot(
            tickers=self._tickers,
            lookback=timedelta(minutes=self.config.lookback_minutes),
            news_lookback=timedelta(hours=self.config.news_hours),
            timeframe=self.config.timeframe,
            use_cache=self.config.use_cache,
            include_news=self.config.include_news,
        )
        callbacks: list[SnapshotCallback]
        with self._lock:
            self._latest_snapshot = snapshot
            self._last_updated = time.time()
            callbacks = list(self._callbacks)
        for callback in callbacks:
            try:
                callback(copy.deepcopy(snapshot))
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.debug("SnapshotStream callback failed", error=str(exc))
        return snapshot

    def last_updated(self) -> Optional[float]:
        """Return the last refresh timestamp (epoch seconds)."""

        with self._lock:
            return self._last_updated

    # ------------------------------------------------------------------- internals

    def _run_loop(self) -> None:
        interval = max(0.1, float(self.config.interval_seconds))
        while not self._stop_event.is_set():
            try:
                self.refresh_now()
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning("SnapshotStream refresh failed", error=str(exc))
            if self._stop_event.wait(interval):
                break
