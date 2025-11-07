"""Shared infrastructure for API clients."""

from __future__ import annotations

from typing import Any, Mapping

from loguru import logger


class APIClientError(Exception):
    """Raised when a client-level error occurs."""


class BaseClient:
    """Base functionality for API client implementations."""

    def __init__(self, name: str, extra_context: Mapping[str, Any] | None = None) -> None:
        self.name = name
        self._context = dict(extra_context or {})

    def _log(self, message: str, **kwargs: Any) -> None:
        """Convenience logger hook."""

        logger.bind(client=self.name, **self._context, **kwargs).debug(message)

