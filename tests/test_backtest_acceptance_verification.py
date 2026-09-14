"""The acceptance auditor detects corrupt outputs independently of the broker."""

import csv
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import runpy

import pytest

from ogami_oanda.adapters.repositories.historical_store import HistoricalStore
from ogami_oanda.entrypoints.backtest_run import run_backtest
from ogami_oanda.strategy.shared.contracts import StrategyDecision
from tests.test_backtest_run import ExampleStrategy, START, candles

AUDIT = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/verify_backtest_acceptance.py"))


@pytest.fixture
def result(tmp_path):
    output = tmp_path / "result"
    run_backtest(ExampleStrategy(), "test", "USD_JPY", candles(), START, START + timedelta(minutes=1),
                 initial_balance=10000, output_dir=output)
    return output


def test_audit_reconciles_partial_closes_and_detects_repeat_difference(result, tmp_path):
    verified = AUDIT["verify_result"](result)
    assert verified["trade_count"] == 1
    repeat = tmp_path / "repeat"
    run_backtest(ExampleStrategy(), "test", "USD_JPY", candles(), START, START + timedelta(minutes=1),
                 initial_balance=10000, output_dir=repeat)
    assert AUDIT["compare_results"](result, repeat)["run_metadata_identical"]
    with (repeat / "gaps.csv").open("a") as stream:
        stream.write("\n")
    with pytest.raises(ValueError, match="repeat differs: gaps.csv"):
        AUDIT["compare_results"](result, repeat)


@pytest.mark.parametrize("artifact,field", [("trades.csv", "realized_pl"), ("equity.csv", "equity")])
def test_audit_rejects_corrupt_ledger_and_equity(result, artifact, field):
    path = result / artifact
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        values = list(reader)
    values[-1][field] = str(float(values[-1][field]) + 0.01)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(values)
    with pytest.raises(ValueError, match="fill profit|equity identity"):
        AUDIT["verify_result"](result)


def test_audit_rejects_incomplete_result(result):
    path = result / "run.json"
    metadata = json.loads(path.read_text())
    metadata["status"] = "failed"
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="incomplete"):
        AUDIT["verify_result"](result)


def test_audit_accepts_zero_trades(tmp_path):
    class EmptyStrategy(ExampleStrategy):
        def decide(self, input):
            return StrategyDecision()

    output = tmp_path / "empty"
    run_backtest(EmptyStrategy(), "empty", "USD_JPY", candles(), START, START + timedelta(minutes=1),
                 initial_balance=10000, output_dir=output)
    assert AUDIT["verify_result"](output)["trade_count"] == 0


def test_audit_validates_saved_data_and_warmup(tmp_path):
    store = HistoricalStore(tmp_path / "history", "USD_JPY")
    start, end = START - timedelta(minutes=2), START + timedelta(minutes=1)
    store.write_interval(start, START, [candle for candle in candles() if candle.time < START])
    store.write_interval(START, end, [candle for candle in candles() if candle.time >= START])
    encoded = json.dumps(store.manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    output = tmp_path / "result"
    run_backtest(ExampleStrategy(), "test", "USD_JPY", store.read(start, end), START, end,
                 initial_balance=10000, output_dir=output,
                 metadata={"data_manifest": store.manifest, "data_sha256": hashlib.sha256(encoded).hexdigest()})
    assert AUDIT["verify_result"](output, store.root)["status"] == "passed"
    daily_file = next(iter(store.manifest["files"].values()))["path"]
    (store.root / daily_file).write_bytes(b"corrupt daily file")
    with pytest.raises(ValueError, match="hash mismatch"):
        AUDIT["verify_result"](output, store.root)
