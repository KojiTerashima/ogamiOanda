import csv
from datetime import datetime, timedelta, timezone
import json

import pytest

from ogami_oanda.domain.market.history import HistoricalCandle, OHLC
from ogami_oanda.domain.orders.models import Direction, OrderIntent, OrderType
from ogami_oanda.strategy.shared.contracts import StrategyDecision, StrategyCommand, StrategyCommandAction

START = datetime(2024, 1, 2, tzinfo=timezone.utc)


class ExampleStrategy:
    data_requirements = {"M1": 2}

    def __init__(self):
        self.count = 0

    def dump_state(self):
        return {"count": self.count}

    def load_state(self, state):
        self.count = state.get("count", 0)

    def decide(self, input):
        self.count += 1
        if self.count == 1:
            return StrategyDecision(intents=(OrderIntent(
                "USD_JPY", Direction.BUY, OrderType.MARKET, 0, False,
                10, False, 10, False, 100, "example", 1, 10,
                metadata={"source": "example", "candle_lc_enabled": False},
            ),))
        if self.count == 2:
            assert len(input.positions) == 1
            return StrategyDecision(commands=(StrategyCommand(StrategyCommandAction.REDUCE_EXPOSURE, "example", "reduce", 40),))
        return StrategyDecision()


def candles():
    for i in range(-24, 12):
        value = 150 + max(i, 0) * .001
        mid = OHLC(value, value, value, value)
        bid = OHLC(*(value - .005 for _ in range(4)))
        ask = OHLC(*(value + .005 for _ in range(4)))
        yield HistoricalCandle(START + timedelta(seconds=5 * i), mid, bid, ask)


def test_replay_tracks_partial_close_and_reproducible_outputs(tmp_path):
    from ogami_oanda.entrypoints.backtest_run import run_backtest

    summaries = []
    for name in ("first", "second"):
        output = tmp_path / name
        summary = run_backtest(ExampleStrategy(), "test-id", "USD_JPY", candles(),
                               START, START + timedelta(minutes=1), initial_balance=10000,
                               output_dir=output, metadata={"data_sha256": "test"})
        summaries.append(summary)
        assert summary["trade_count"] == 1
        assert summary["ending_balance"] == pytest.approx(10000 + summary["realized_pl"])
        assert summary["ending_unrealized_pl"] == 0
        rows = list(csv.DictReader((output / "trades.csv").open()))
        assert [r["event"] for r in rows] == ["FILL", "REDUCE", "CLOSE"]
        assert [int(r["units"]) for r in rows] == [100, 40, 60]
        assert sum(float(r["realized_pl"]) for r in rows) == pytest.approx(summary["realized_pl"])
        equity = list(csv.DictReader((output / "equity.csv").open()))
        assert all(float(r["equity"]) == pytest.approx(float(r["balance"]) + float(r["unrealized_pl"])) for r in equity)
        assert json.loads((output / "run.json").read_text())["status"] == "complete"
    assert summaries[0] == summaries[1]
    for name in ("orders.csv", "trades.csv", "equity.csv"):
        assert (tmp_path / "first" / name).read_bytes() == (tmp_path / "second" / name).read_bytes()


def test_replay_rejects_existing_output_and_short_warmup(tmp_path):
    from ogami_oanda.entrypoints.backtest_run import run_backtest

    with pytest.raises(FileExistsError):
        run_backtest(ExampleStrategy(), "test", "USD_JPY", candles(), START, START + timedelta(minutes=1),
                     initial_balance=10000, output_dir=tmp_path)
    output = tmp_path / "short"
    with pytest.raises(ValueError, match="warmup"):
        run_backtest(ExampleStrategy(), "test", "USD_JPY", (b for b in candles() if b.time >= START), START,
                     START + timedelta(minutes=1), initial_balance=10000, output_dir=output)
    assert json.loads((output / "run.json").read_text())["status"] == "failed"


def test_cli_run_is_offline_and_writes_zero_trade_statistics(tmp_path, monkeypatch):
    from ogami_oanda.entrypoints import backtest

    class QuietStrategy(ExampleStrategy):
        def decide(self, input):
            return StrategyDecision()

    monkeypatch.setattr(backtest, "select_strategy", lambda args: (QuietStrategy(), "quiet", {}))
    path = tmp_path / "mid.csv"
    with path.open("w") as stream:
        writer = csv.writer(stream)
        writer.writerow(["time", "open", "high", "low", "close"])
        for bar in candles():
            writer.writerow([bar.time.isoformat(), 150, 150, 150, 150])
    out = tmp_path / "result"
    assert backtest.main(["run", "--strategy", "matcha", "--pair", "USD_JPY", "--from", START.isoformat(),
                          "--to", (START + timedelta(minutes=1)).isoformat(), "--mid-csv", str(path),
                          "--fixed-spread-pips", "1", "--initial-balance", "10000", "--output-dir", str(out)]) == 0
    summary = json.loads((out / "summary.json").read_text())
    assert summary["trade_count"] == 0
    assert summary["win_rate"] is None
    assert summary["profit_factor"] is None
    assert summary["max_drawdown"] == 0
    assert json.loads((out / "run.json").read_text())["price_mode"] == "MID_FIXED_SPREAD"


@pytest.mark.parametrize("name,pair", [("original", "USD_JPY"), ("original", "EUR_USD"),
                                       ("original", "AUD_USD"), ("matcha", "USD_JPY")])
def test_packaged_strategies_complete_a_short_offline_replay(tmp_path, name, pair, request):
    from argparse import Namespace
    from ogami_oanda.entrypoints.backtest import select_strategy
    from ogami_oanda.entrypoints.backtest_run import run_backtest

    main_dir = request.getfixturevalue("main_source_directory") if name == "original" else tmp_path / "missing-main"
    strategy, identity, metadata = select_strategy(Namespace(command="run", main_analysis_dir=main_dir, strategy=name, strategy_py=None, strategy_yaml=None,
                                                             pair=pair, risk_yen=500, line_units=1))
    interval = 300 if name == "original" else 60
    amount = 3600 if name == "original" else 1100
    base = 150 if pair == "USD_JPY" else 1.05 if pair == "EUR_USD" else .7

    def history():
        for i in range(-amount, 0):
            value = base + base * .0001 * (i % 11)
            p = OHLC(value, value * 1.00001, value * .99999, value)
            yield HistoricalCandle(START + timedelta(seconds=i * interval), p, p, p)
        for i in range(12):
            p = OHLC(base, base, base, base)
            yield HistoricalCandle(START + timedelta(seconds=i * 5), p, p, p)

    result = run_backtest(strategy, identity, pair, history(), START, START + timedelta(minutes=1),
                          initial_balance=10000, output_dir=tmp_path / "output", metadata=metadata)
    assert result["evaluated_candles"] == 12
    assert result["ending_unrealized_pl"] == 0
    assert result["currency"] == pair.split("_")[1]


def test_quote_only_replay_records_gap_intervals_without_warmup(tmp_path):
    from ogami_oanda.entrypoints.backtest_run import run_backtest

    class QuoteOnly(ExampleStrategy):
        data_requirements = {}

        def decide(self, input):
            assert input.candles is None
            assert input.candle_frames == {}
            return StrategyDecision()

    price = OHLC(150, 150, 150, 150)
    values = (HistoricalCandle(START + timedelta(seconds=offset), price, price, price)
              for offset in (5, 10, 25))
    output = tmp_path / "gaps"
    summary = run_backtest(QuoteOnly(), "quote-only", "USD_JPY", values, START,
                           START + timedelta(minutes=1), initial_balance=10000, output_dir=output)
    assert summary["warmup_candles"] == 0
    assert summary["evaluated_candles"] == 3
    assert summary["gap_count"] == 3
    assert summary["gap_seconds"] == 45
    with (output / "gaps.csv").open() as stream:
        gaps = list(csv.DictReader(stream))
    assert [(row["from"], row["to"], float(row["seconds"])) for row in gaps] == [
        ((START + timedelta(seconds=left)).isoformat(), (START + timedelta(seconds=right)).isoformat(), right - left)
        for left, right in ((0, 5), (15, 25), (30, 60))
    ]


def test_future_input_changes_cannot_change_earlier_decisions_or_executions(tmp_path):
    from ogami_oanda.entrypoints.backtest_run import run_backtest

    class ObservingStrategy(ExampleStrategy):
        def __init__(self):
            super().__init__()
            self.observed = []

        def decide(self, input):
            decision = super().decide(input)
            self.observed.append((input.evaluation_time, input.quote, input.positions,
                                  input.candles.to_json(date_format="iso"), decision))
            return decision

    cutoff = START + timedelta(seconds=30)
    strategies = []
    trades = []
    for changed in (False, True):
        strategy = ObservingStrategy()
        strategies.append(strategy)

        def history():
            for candle in candles():
                if changed and candle.time >= cutoff:
                    price = OHLC(155, 156, 154, 155)
                    yield HistoricalCandle(candle.time, price, price, price)
                else:
                    yield candle

        output = tmp_path / str(changed)
        run_backtest(strategy, "observing", "USD_JPY", history(), START, START + timedelta(minutes=1),
                     initial_balance=10000, output_dir=output)
        with (output / "trades.csv").open() as stream:
            trades.append([row for row in csv.DictReader(stream) if datetime.fromisoformat(row["time"]) <= cutoff])
    assert [row for row in strategies[0].observed if row[0] <= cutoff] == [
        row for row in strategies[1].observed if row[0] <= cutoff]
    assert trades[0] == trades[1]
    assert strategies[0].observed[-1] != strategies[1].observed[-1]


def test_mid_replay_failure_retains_incomplete_artifacts(tmp_path):
    from ogami_oanda.entrypoints.backtest_run import run_backtest

    def broken_history():
        for candle in candles():
            if candle.time >= START + timedelta(seconds=30):
                raise RuntimeError("synthetic source failure")
            yield candle

    output = tmp_path / "failed"
    with pytest.raises(RuntimeError, match="synthetic source failure"):
        run_backtest(ExampleStrategy(), "failure", "USD_JPY", broken_history(), START,
                     START + timedelta(minutes=1), initial_balance=10000, output_dir=output)
    assert json.loads((output / "run.json").read_text())["status"] == "failed"
    assert not (output / "summary.json").exists()
    with (output / "trades.csv").open() as stream:
        assert [row["event"] for row in csv.DictReader(stream)] == ["FILL", "REDUCE"]
    with (output / "orders.csv").open() as stream:
        assert all(row["time"].endswith("+00:00") for row in csv.DictReader(stream))


@pytest.mark.parametrize("name,pair", [("original", "USD_JPY"), ("original", "EUR_USD"),
                                       ("original", "AUD_USD"), ("matcha", "USD_JPY")])
def test_cli_runs_real_packaged_strategies_without_live_composition(tmp_path, monkeypatch, name, pair, request):
    from ogami_oanda.entrypoints import backtest, live
    from ogami_oanda.infrastructure.config import loader

    main_dir = request.getfixturevalue("main_source_directory") if name == "original" else tmp_path / "absent-main"

    def forbidden(*args, **kwargs):
        raise AssertionError("offline replay used live composition or credentials")

    monkeypatch.setattr(loader, "load_settings", forbidden)
    monkeypatch.setattr(live, "build_live_application", forbidden)
    monkeypatch.setattr(live, "build_strategy_live_application", forbidden)
    price = 150 if pair == "USD_JPY" else 1.1 if pair == "EUR_USD" else .7
    interval = 300 if name == "original" else 60
    amount = 3600 if name == "original" else 1100
    source = tmp_path / "mid.csv"
    with source.open("w") as stream:
        writer = csv.writer(stream)
        writer.writerow(["time", "open", "high", "low", "close"])
        for index in range(-amount, 12):
            at = START + timedelta(seconds=index * (interval if index < 0 else 5))
            value = price * (1 + .0001 * (index % 11))
            writer.writerow([at.isoformat(), value, value * 1.00001, value * .99999, value])
    output = tmp_path / "result"
    assert backtest.main(["run", "--strategy", name, "--main-analysis-dir", str(main_dir), "--pair", pair, "--from", START.isoformat(),
                          "--to", (START + timedelta(minutes=1)).isoformat(), "--mid-csv", str(source),
                          "--fixed-spread-pips", "0", "--initial-balance", "10000", "--output-dir", str(output)]) == 0
    metadata = json.loads((output / "run.json").read_text())
    assert metadata["status"] == "complete"
    assert len(metadata["data_sha256"]) == len(metadata["source_sha256"]) == 64


def test_end_cleanup_cancels_local_watching_without_submitting_and_drains_events(tmp_path, monkeypatch):
    from ogami_oanda.entrypoints import backtest_run

    brokers = []
    base = backtest_run.SimulatedBroker
    class RecordingBroker(base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            brokers.append(self)
    monkeypatch.setattr(backtest_run, 'SimulatedBroker', RecordingBroker)
    class Watching(ExampleStrategy):
        data_requirements = {}
        def decide(self, input):
            self.count += 1
            if self.count != 1:
                return StrategyDecision()
            return StrategyDecision(intents=(OrderIntent(
                'USD_JPY', Direction.BUY, OrderType.STOP, 150.05, True,
                10, False, 10, False, 100, 'watch', 1, 10,
                metadata={'source': 'watch', 'order_permission': False, 'candle_lc_enabled': False},
            ),))
    values = []
    for index, value in enumerate((150, 150, 151)):
        price = OHLC(value, value, value, value)
        values.append(HistoricalCandle(START + timedelta(seconds=index * 5), price, price, price))
    output = tmp_path / 'result'
    result = backtest_run.run_backtest(Watching(), 'watch', 'USD_JPY', values, START,
                                     START + timedelta(seconds=15), initial_balance=10000, output_dir=output)
    assert result['trade_count'] == 0
    assert not brokers[0].pending_orders()
    assert not brokers[0].open_positions()
    events = list(csv.DictReader((output / 'orders.csv').open()))
    assert not any(row['event'] == 'SUBMIT' for row in events)
    assert any(row['event'] == 'order_cancelled' and row['reason'] == 'END_OF_TEST' for row in events)
    assert json.loads((output / 'run.json').read_text())['status'] == 'complete'


def test_cli_pins_manifest_content_when_writer_commits_during_preflight(tmp_path, monkeypatch):
    import hashlib
    from argparse import Namespace
    from ogami_oanda.adapters.repositories.historical_store import HistoricalStore
    from ogami_oanda.entrypoints import backtest

    writer = HistoricalStore(tmp_path / 'data', 'USD_JPY')
    price = OHLC(150, 150, 150, 150)
    writer.write_interval(START, START + timedelta(hours=6), [HistoricalCandle(START, price, price, price)])
    pinned = json.loads(json.dumps(writer.manifest))
    original_validate = HistoricalStore.validate
    def validate_then_append(self, start, end):
        original_validate(self, start, end)
        writer.write_interval(START + timedelta(hours=6), START + timedelta(hours=12), [])
    monkeypatch.setattr(HistoricalStore, 'validate', validate_then_append)
    class Quiet(ExampleStrategy):
        data_requirements = {}
        def decide(self, input):
            return StrategyDecision()
    output = tmp_path / 'result'
    args = Namespace(output_dir=output, mid_csv=None, fixed_spread_pips=None, data_dir=writer.root,
                     pair='USD_JPY', start=START, end=START + timedelta(seconds=5), initial_balance=10000, slippage_pips=0,
                     main_analysis_dir=tmp_path / 'absent-main')
    backtest._run(args, Quiet(), 'quiet', {})
    metadata = json.loads((output / 'run.json').read_text())
    assert metadata['data_manifest'] == pinned
    assert metadata['data_manifest_encoding'] == 'utf-8;json:sort_keys=true,separators=comma:colon,ensure_ascii=false'
    expected = json.dumps(pinned, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()
    assert metadata['data_sha256'] == hashlib.sha256(expected).hexdigest()


def test_run_never_reports_complete_with_unclosed_terminal_exposure(tmp_path, monkeypatch):
    from ogami_oanda.entrypoints import backtest_run

    def interrupted_liquidation(self):
        self.finalized = True
    monkeypatch.setattr(backtest_run.SimulatedBroker, 'finalize', interrupted_liquidation)
    output = tmp_path / 'incomplete-liquidation'
    with pytest.raises(RuntimeError, match='terminal state'):
        backtest_run.run_backtest(ExampleStrategy(), 'test', 'USD_JPY', candles(), START,
                                  START + timedelta(minutes=1), initial_balance=10000, output_dir=output)
    assert json.loads((output / 'run.json').read_text())['status'] == 'failed'
    assert not (output / 'summary.json').exists()


@pytest.mark.parametrize('name', ['trade', 'trade-1', 'session:trade'])
def test_history_release_matches_complete_event_references_and_amendment_suffixes(name):
    from types import SimpleNamespace
    from ogami_oanda.adapters.backtest.broker import SimulatedBroker
    from ogami_oanda.adapters.backtest.history import SimulationHistory, SimulationNotifier
    from ogami_oanda.application.services.historical_market import ReplayClock
    from ogami_oanda.application.services.position_service import PositionService
    from ogami_oanda.domain.positions.managed_position import ManagedPosition
    from ogami_oanda.entrypoints.backtest_run import release_simulation_history

    clock = ReplayClock(START)
    history = SimulationHistory()
    broker = SimulatedBroker('USD_JPY', clock, initial_balance=10000)
    service = PositionService(broker, broker, SimulationNotifier(), history, clock)
    position = ManagedPosition.registered(name, 'USD_JPY')._replace(
        order_id='order-1', trade_id='trade-1', client_reference='ogm-current',
    )
    expected = {
        'order_submitted:order-1', 'trade_closed:trade-1', f'order_cancelled:{name}',
        'order_rejected:ogm-current', 'stop_loss_amended:trade-1:2:149.0',
        f'stop_loss_amended:{name}:3:149.5',
    }
    obsolete = {f'trade_closed:trade-{index}' for index in range(100, 100100)}
    obsolete |= {f'order_cancelled:{name}-obsolete', 'stop_loss_amended:trade-100:2:149.0',
                 'order_submitted:order-10', 'order_rejected:ogm-current-old'}
    service._emitted_event_ids = expected | obsolete
    history.seen = {'trade-1', 'trade-100'}
    service.closure_reporting._reported_event_ids = {'trade_closed:trade-1', 'trade_closed:trade-100'}
    application = SimpleNamespace(portfolio=SimpleNamespace(slots=[position], position_service=service))

    release_simulation_history(application, broker, history)

    assert service._emitted_event_ids == expected
    assert history.seen == {'trade-1'}
    assert service.closure_reporting._reported_event_ids == {'trade_closed:trade-1'}
