"""TradingAI package root exports."""

from trading_ai.core.pipeline import SignalPipeline
from trading_ai.settings import Settings, get_settings

__all__ = ["SignalPipeline", "Settings", "get_settings"]
