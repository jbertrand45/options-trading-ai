"""TradingAI package root exports with lazy imports to avoid heavy deps at import time."""

from __future__ import annotations

from typing import Any

__all__ = ["SignalPipeline", "Settings", "get_settings"]


def __getattr__(name: str) -> Any:
    if name == "SignalPipeline":
        from trading_ai.core.pipeline import SignalPipeline

        return SignalPipeline
    if name == "Settings":
        from trading_ai.settings import Settings

        return Settings
    if name == "get_settings":
        from trading_ai.settings import get_settings

        return get_settings
    raise AttributeError(f"module 'trading_ai' has no attribute '{name}'")
