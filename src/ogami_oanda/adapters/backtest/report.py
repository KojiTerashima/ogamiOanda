"""Streaming simulation artifacts and drawdown statistics."""

from __future__ import annotations

import csv
from pathlib import Path

from ogami_oanda.adapters.repositories.historical_store import atomic_json
from ogami_oanda.domain.market.history import utc_time

EVENT_COLUMNS = ("event_id", "time", "event", "pair", "name", "order_id", "trade_id",
                 "client_reference", "direction", "units", "price", "realized_pl", "reason")


class BacktestReport:
    def __init__(self, directory: str | Path, metadata: dict, initial_balance: float) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.metadata = {**metadata, "status": "running"}
        atomic_json(self.directory / "run.json", self.metadata)
        self.streams = []
        self.orders = self._writer("orders.csv", EVENT_COLUMNS)
        self.trades = self._writer("trades.csv", EVENT_COLUMNS)
        self.equity = self._writer("equity.csv", ("time", "balance", "unrealized_pl", "equity"))
        self.gaps = self._writer("gaps.csv", ("from", "to", "seconds"))
        self.peak = initial_balance
        self.max_drawdown = 0.0
        self.max_drawdown_pct = 0.0

    def _writer(self, name: str, fields: tuple) -> csv.DictWriter:
        stream = (self.directory / name).open("w", encoding="utf-8", newline="")
        self.streams.append(stream)
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        return writer

    def event(self, event: dict) -> None:
        event = {**event, "time": utc_time(event["time"]).isoformat()}
        self.orders.writerow(event)
        if event["event"] in {"FILL", "REDUCE", "CLOSE"}:
            self.trades.writerow(event)

    def gap(self, start, end) -> None:
        self.gaps.writerow({"from": start.isoformat(), "to": end.isoformat(),
                            "seconds": (end - start).total_seconds()})

    def mark(self, at, balance: float, unrealized: float) -> None:
        equity = balance + unrealized
        self.peak = max(self.peak, equity)
        self.max_drawdown = max(self.max_drawdown, self.peak - equity)
        self.max_drawdown_pct = max(self.max_drawdown_pct, (self.peak - equity) / self.peak * 100)
        self.equity.writerow({"time": utc_time(at).isoformat(), "balance": balance, "unrealized_pl": unrealized, "equity": equity})

    def finish(self, summary: dict, *, metadata: dict | None = None) -> None:
        self.close()
        atomic_json(self.directory / "summary.json", summary)
        atomic_json(self.directory / "run.json", {**self.metadata, **(metadata or {}), "status": "complete"})

    def fail(self, error: BaseException) -> None:
        self.close()
        atomic_json(self.directory / "run.json", {**self.metadata, "status": "failed", "error_type": type(error).__name__})

    def close(self) -> None:
        for stream in self.streams:
            stream.close()
