import importlib
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from ogami_oanda.strategy.shared import contracts
from ogami_oanda.strategy.shared.loader import load_strategy


def test_original_is_a_loadable_api_v1_strategy():
    directory = Path(__file__).parents[1] / 'src/ogami_oanda/strategy/original'
    assert (directory / 'strategy.py').is_file()
    loaded = load_strategy(directory / 'strategy.py', directory / 'parameters.yaml')
    assert isinstance(loaded.strategy, contracts.TradingStrategy)
    assert loaded.strategy.dump_state() == {}
    loaded.strategy.load_state({})
    assert contracts.strategy_data_requirements(loaded.strategy) == {
        'M5': 250, 'H1': 250, 'M30': 250, 'S5': 250,
    }


def test_optional_requirements_preserve_existing_plugin_input():
    helper = getattr(contracts, 'strategy_data_requirements', None)
    assert callable(helper)
    assert helper(SimpleNamespace()) == {'M1': 1000}
    for requirements in ({'M2': 3}, {'M1': 0}, {'M1': True}, {'M1': 1.5}, []):
        with pytest.raises(ValueError, match='data_requirements'):
            helper(SimpleNamespace(data_requirements=requirements))
    quote = contracts.StrategyQuote('USD_JPY', 150, 150, 150)
    old_input = contracts.StrategyInput(quote, candles='legacy')
    assert old_input.candles == 'legacy'
    assert old_input.candle_frames == {}


@pytest.mark.parametrize('pair', ['USD_JPY', 'EUR_USD', 'AUD_USD'])
def test_original_api_matches_characterized_candidates_and_candle_protection(pair, analysis_frame_store):
    from ogami_oanda.adapters.legacy.order_dict import order_plan_to_legacy_dict
    from ogami_oanda.application.services.order_planner import OrderPlanner
    from tests.test_characterization_analysis_oracle import _snapshot_value

    spec = importlib.util.find_spec('ogami_oanda.strategy.original.strategy')
    assert spec is not None, 'original must implement the shared strategy API'
    module = importlib.import_module('ogami_oanda.strategy.original.strategy')
    snapshot = json.loads((Path(__file__).parent / 'fixtures' / f'analysis_oracle_{pair.lower()}.json').read_text())
    frames = analysis_frame_store[pair]
    quote = contracts.StrategyQuote(pair, snapshot['current_price'], snapshot['current_price'], snapshot['current_price'])
    strategy = module.OriginalStrategy(pair=pair)
    decision = strategy.decide(contracts.StrategyInput(
        quote, candle_frames=frames,
        evaluation_time=datetime.fromisoformat(snapshot['decision_time'].replace('/', '-')),
    ))
    expected = snapshot['selected_immediate_candidates'] + snapshot['selected_future_resist_candidates'] + snapshot['selected_future_break_candidates']
    assert len(decision.intents) == len(expected)
    for intent, candidate in zip(decision.intents, expected):
        assert intent.direction.value == candidate['direction']
        assert intent.metadata['line_strategy'] == candidate['line_strategy']
        assert intent.metadata['recommended_reasons'] == candidate['recommended_reasons']
    assert decision.order_context.decision_time == frames['M5'].iloc[0]['time_jp']
    assert decision.candle_protection.previous_candle['time_jp'] == frames['M5'].iloc[1]['time_jp']
    assert strategy.dump_state() == {}
    actual_plans = [order_plan_to_legacy_dict(OrderPlanner().plan(intent, decision.order_context))
                    for intent in decision.intents]
    expected_plans = [order['plan'] | {'for_api_json': {'order': order['payload']}}
                      for order in snapshot['legacy_orders']]
    assert _snapshot_value(actual_plans) == _snapshot_value(expected_plans)


def test_plugin_runner_fetches_declared_frames_and_preserves_order_context():
    from ogami_oanda.application.ports.market_data import MarketQuote
    from ogami_oanda.application.services.order_planner import OrderPlanner
    from ogami_oanda.domain.orders.models import OrderContext
    from ogami_oanda.entrypoints.live import StrategyLiveApplication
    from tests.fakes import FixedClock
    from tests.test_contract_strategy_live_entrypoint import NOW, _Market, _Portfolio, _Strategy, _intent

    context = OrderContext(150, '2026/01/02 03:00:00', 0.123)
    assert 'order_context' in contracts.StrategyDecision.__dataclass_fields__
    strategy = _Strategy(contracts.StrategyDecision(intents=(_intent(),), order_context=context))
    strategy.data_requirements = {'M5': 250, 'S5': 250}
    market = _Market(MarketQuote('USD_JPY', 150, 150, 150, source_time=NOW))
    app = StrategyLiveApplication('USD_JPY', strategy, 'test', market, OrderPlanner(), _Portfolio(), FixedClock(NOW))
    result = app.run_once(dry_run=True)
    assert market.candle_calls == [('USD_JPY', 'M5', 250), ('USD_JPY', 'S5', 250)]
    assert set(strategy.inputs[0].candle_frames) == {'M5', 'S5'}
    assert strategy.inputs[0].candles is None
    assert result.plans[0].context == context


@pytest.mark.parametrize("dry_run", [False, True])
def test_original_explicit_plugin_keeps_first_tick_and_later_sync_order(analysis_frame_store, dry_run):
    from ogami_oanda.application.ports.market_data import MarketQuote
    from ogami_oanda.application.services.order_planner import OrderPlanner
    from ogami_oanda.entrypoints.live import StrategyLiveApplication
    from ogami_oanda.strategy.original.strategy import OriginalStrategy
    from tests.fakes import FixedClock
    from tests.test_contract_strategy_live_entrypoint import _Market, _Portfolio

    trace = []
    strategy = OriginalStrategy(candidate_builder=lambda *_: trace.append('decide') or [])
    class Market(_Market):
        def candles(self, pair, granularity, count):
            return analysis_frame_store[pair][granularity]
    class Portfolio(_Portfolio):
        def sync_all(self, *, candle_stop_loss=None, **kwargs):
            return super().sync_all(**kwargs)
    market = Market(MarketQuote('USD_JPY', 150, 150, 150), trace=trace)
    portfolio = Portfolio(trace, strategy_state={})
    app = StrategyLiveApplication('USD_JPY', strategy, 'original-test', market, OrderPlanner(), portfolio, FixedClock(datetime(2026, 1, 3, 5, 0, 6)))
    first = app.run_once(dry_run=dry_run)
    assert first.analysis is not None
    assert 'sync' not in trace
    assert portfolio.set_calls == ([] if dry_run else [({}, True)])
    assert app.strategy_id == 'original-test'
    trace.clear()
    later = app.run_once(now=datetime(2026, 1, 5, 10, 5, 6), dry_run=dry_run)
    assert later.analysis is not None
    expected = ['quote', 'sync', 'decide', 'sync'] if dry_run else ['quote', 'sync', 'decide', 'register', 'sync']
    assert [item for item in trace if item in {'quote', 'sync', 'decide', 'register'}] == expected


def test_compatibility_facade_preserves_explicit_decision_time(analysis_frame_store):
    from ogami_oanda.application.services.market_analysis_service import MarketAnalysisService
    from tests.fakes import FakeMarketData

    frames = analysis_frame_store['USD_JPY']
    market = FakeMarketData({('USD_JPY', key): value for key, value in frames.items()}, {'USD_JPY': 150})
    contexts = []
    service = MarketAnalysisService(market, lambda context, _: contexts.append(context) or [])
    service.analyze('USD_JPY', '2026/01/02 12:00:00')
    assert contexts[0]['decision_time'] == '2026/01/02 12:00:00'


def test_compatibility_facade_accepts_different_pairs_and_unpadded_dates(analysis_frame_store):
    from ogami_oanda.application.services.market_analysis_service import MarketAnalysisService
    from tests.fakes import FakeMarketData

    market = FakeMarketData({(pair, key): frame for pair, frames in analysis_frame_store.items()
                             for key, frame in frames.items()}, {'USD_JPY': 150, 'EUR_USD': 1.08})
    contexts = []
    service = MarketAnalysisService(market, lambda context, _: contexts.append(context) or [])
    service.analyze('USD_JPY', '2026/01/02 12:00:00')
    service.analyze('EUR_USD', '2026/1/2 12:00:00')
    assert contexts[-1]['decision_time'] == '2026/1/2 12:00:00'


def test_original_plugin_dry_run_never_registers_real_portfolio_positions(analysis_frame_store):
    from ogami_oanda.application.ports.market_data import MarketQuote
    from ogami_oanda.application.services.market_analysis_service import MarketAnalysisResult
    from ogami_oanda.application.services.order_planner import OrderPlanner
    from ogami_oanda.application.services.position_portfolio_service import PositionPortfolioService
    from ogami_oanda.application.services.position_service import PositionService
    from ogami_oanda.entrypoints.live import StrategyLiveApplication
    from ogami_oanda.strategy.original.strategy import OriginalStrategy
    from tests.fakes import FakeBroker, FakeNotifier, FixedClock, InMemoryTradeHistoryRepository
    from tests.test_contract_strategy_live_entrypoint import NOW, _Market, _intent

    class Original(OriginalStrategy):
        def decide(self, input):
            self.last_analysis = MarketAnalysisResult((_intent(),), input.candle_frames, {})
            return contracts.StrategyDecision(intents=(_intent(),))

    class Market(_Market):
        def candles(self, pair, granularity, count):
            return analysis_frame_store[pair][granularity]

    clock = FixedClock(NOW)
    broker = FakeBroker()
    service = PositionService(broker, broker, FakeNotifier(), InMemoryTradeHistoryRepository(), clock)
    portfolio = PositionPortfolioService('USD_JPY', service, broker, broker)
    market = Market(MarketQuote('USD_JPY', 150, 150, 150, source_time=NOW))
    app = StrategyLiveApplication('USD_JPY', Original(), 'original-test', market, OrderPlanner(), portfolio, clock)
    result = app.run_once(dry_run=True)
    assert result.plans
    assert all(slot is None for slot in portfolio.slots)
    assert broker.requests == []
