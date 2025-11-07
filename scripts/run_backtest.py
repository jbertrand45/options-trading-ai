#!/usr/bin/env python3
"""Run BacktestRunner on one or more snapshot JSON files."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

from trading_ai.backtest.data_loader import contexts_from_snapshot, load_snapshot_file
from trading_ai.backtest.engine import BacktestConfig, BacktestRunner
from trading_ai.risk.manager import RiskManager
from trading_ai.strategies import MomentumIVStrategy


def run_backtest(files: List[Path]) -> None:
    contexts = []
    for path in files:
        snapshot = load_snapshot_file(path)
        contexts.extend(contexts_from_snapshot(snapshot))

    if not contexts:
        print("No contexts loaded. Ensure snapshots contain underlying bars.")
        return

    strategy = MomentumIVStrategy()
    risk_manager = RiskManager()
    runner = BacktestRunner(strategy=strategy, risk_manager=risk_manager, config=BacktestConfig())
    result = runner.run(contexts)
    print("Backtest stats:", result.stats)
    print("Trades:")
    for trade in result.trades:
        print(trade)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run backtests on snapshot JSON files.")
    parser.add_argument("snapshots", nargs="+", help="Snapshot JSON files produced by collect-snapshots.")
    args = parser.parse_args()
    files = [Path(p) for p in args.snapshots]
    run_backtest(files)


if __name__ == "__main__":
    main()
