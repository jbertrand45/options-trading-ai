"""SnapshotStream service tests."""

from __future__ import annotations

import threading
import time

from trading_ai.service.snapshot_stream import SnapshotStream, SnapshotStreamConfig


class DummyPipeline:
    def __init__(self) -> None:
        self.calls = 0

    def collect_market_snapshot(self, **_: object):
        self.calls += 1
        return {"tick": self.calls}


def test_snapshot_stream_refresh_now_returns_snapshot() -> None:
    pipeline = DummyPipeline()
    stream = SnapshotStream(pipeline, config=SnapshotStreamConfig(interval_seconds=0.01))

    snapshot = stream.refresh_now()

    assert snapshot["tick"] == 1
    assert stream.latest_snapshot()["tick"] == 1


def test_snapshot_stream_background_loop_invokes_callbacks() -> None:
    pipeline = DummyPipeline()
    stream = SnapshotStream(pipeline, config=SnapshotStreamConfig(interval_seconds=0.05))
    event = threading.Event()

    def callback(snapshot):
        if snapshot.get("tick", 0) >= 1:
            event.set()

    stream.subscribe(callback)
    stream.start()
    try:
        assert event.wait(0.5)
        assert pipeline.calls >= 1
    finally:
        stream.stop()
