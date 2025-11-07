#!/usr/bin/env python3
import json
from pathlib import Path

import orjson

from trading_ai.data.duckdb_store import SnapshotStore


def main(path: str) -> None:
    store = SnapshotStore()
    path_obj = Path(path)
    snapshot = orjson.loads(path_obj.read_bytes())
    store.ingest_snapshot(snapshot)
    store.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Ingest snapshot JSON into DuckDB store.")
    parser.add_argument("snapshot", help="Path to snapshot JSON file")
    args = parser.parse_args()
    main(args.snapshot)
