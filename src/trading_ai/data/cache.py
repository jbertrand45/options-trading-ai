"""Local filesystem caching helpers to persist market data pulls."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import orjson
import pandas as pd


class LocalDataCache:
    """Lightweight cache that writes JSON blobs under a root folder."""

    def __init__(self, root: str | Path = Path("data/cache")) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _sanitize(self, part: str) -> str:
        return part.replace("/", "_").replace(":", "-")

    def _build_path(self, *parts: str, suffix: str) -> Path:
        safe_parts = [self._sanitize(part) for part in parts if part]
        path = self.root.joinpath(*safe_parts)
        return path.with_suffix(suffix)

    def exists(self, *parts: str, suffix: str = ".json") -> bool:
        """Return True if a cached artifact exists."""

        return self._build_path(*parts, suffix=suffix).exists()

    def remove(self, *parts: str, suffix: str = ".json") -> None:
        """Remove a cached artifact if it exists."""

        path = self._build_path(*parts, suffix=suffix)
        if path.exists():
            path.unlink()

    # JSON helpers -----------------------------------------------------------------

    def read_json(self, *parts: str) -> Any:
        path = self._build_path(*parts, suffix=".json")
        with path.open("rb") as f:
            return orjson.loads(f.read())

    def write_json(self, data: Any, *parts: str) -> Path:
        path = self._build_path(*parts, suffix=".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = orjson.dumps(data, option=orjson.OPT_INDENT_2, default=str)
        with path.open("wb") as f:
            f.write(payload)
        return path

    # Parquet helpers --------------------------------------------------------------

    def read_dataframe(self, *parts: str) -> pd.DataFrame:
        payload = self.read_json(*parts)
        return pd.DataFrame(payload)

    def write_dataframe(self, frame: pd.DataFrame, *parts: str) -> Path:
        if frame.empty:
            raise ValueError("Cannot cache empty DataFrame")
        records = frame.to_dict(orient="records")
        return self.write_json(records, *parts)

    # Utility ----------------------------------------------------------------------

    def list_cached(self) -> Iterable[Path]:
        """Yield all cached file paths."""

        for path in self.root.glob("**/*"):
            if path.is_file():
                yield path
