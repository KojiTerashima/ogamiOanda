"""Research harness checks, separate from production behavior contracts."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

from ogami_oanda.adapters.legacy.main_analysis.backend import MainSourceAnalysis
from ogami_oanda.application.services.historical_market import HistoricalMarket
from ogami_oanda.domain.market.history import HistoricalCandle, OHLC
from scripts.backtest_comparison.common import compare_candidates, differences, digest
from scripts.backtest_comparison.data import Dataset, fixed_spread
from scripts.backtest_comparison.execution import classify_execution, normalize_main, replay_order
from scripts.backtest_comparison.native import (
    NativeAnalysis, NativeInspection, comparable_candidate, inspection_sources,
)
from scripts.backtest_comparison.runner import evaluation_facts, normalized_hashes
from tests.fakes.main_analysis import request_for


START = datetime(2024, 9, 2, tzinfo=timezone.utc)


def bar(seconds, o=150, h=150.02, low=149.98, close=150):
    mid = OHLC(o, h, low, close)
    return fixed_spread(HistoricalCandle(START+timedelta(seconds=seconds), mid, mid, mid, volume=1), "USD_JPY")


def candidate(direction=1, **updates):
    return {"pair":"USD_JPY", "direction":direction, "order_type":"STOP", "target_price":150+direction*.1,
            "take_profit_price":150+direction*.2, "stop_loss_price":150-direction*.1,
            "units":100, "order_timeout_min":60, "trade_timeout_min":60, "metadata":{}, **updates}


@pytest.fixture(scope="module")
def sources(main_source_directory):
    if not (Path(main_source_directory)/"classInspection.py").exists():
        pytest.skip("external main Inspection source unavailable")
    return inspection_sources(main_source_directory)


def compare_execution(sources, candles, order=None, amendments=()):
    order = order or candidate()
    dataset = Dataset("USD_JPY", candles)
    end = candles[-1].end
    native = NativeInspection(sources, "USD_JPY")
    try:
        main = normalize_main(native.evaluate(START, order, dataset.inspection_frame(START,end)), order)
    finally:
        native.close()
    ogami, events = replay_order("USD_JPY", START, order, dataset.candles(START,end,True), amendments=amendments)
    delta, causes = classify_execution(main, ogami, order, events, dataset)
    return main, ogami, events, delta, causes


def test_price_change_is_not_lost_by_order_matching_and_duplicate_occurrences():
    result = compare_candidates([candidate(),candidate()], [candidate(target_price=150.11)], "USD_JPY")
    assert any(d.get("field")=="target_price" for d in result)
    assert any(d["kind"]=="main_only" for d in result)


def test_tolerances_do_not_hide_units_or_currency_pnl_differences():
    assert not differences({"target_price":150.10000001}, {"target_price":150.1}, "USD_JPY")
    assert differences({"units":100}, {"units":101}, "USD_JPY")
    assert differences({"pnl_quote":1e8}, {"pnl_quote":1e8+.001}, "USD_JPY")
    assert differences({"x":None}, {"x":0}, "USD_JPY")
    assert differences({"x":False}, {"x":0}, "USD_JPY")


def test_independent_aggregation_across_boundaries_and_gap():
    candles = [bar(s,close=150+(s%20)*.001) for s in range(0,3700,5) if not 200<=s<245]
    dataset = Dataset("USD_JPY", candles)
    market = HistoricalMarket("USD_JPY",dict.fromkeys(("S5","M5","M30","H1"),250))
    for candle in candles:
        market.advance(candle)
        if candle.end.second==0 or candle.time.second==5:
            expected,_,_=dataset.frames(candle.end)
            for foot,frame in expected.items():
                columns=["time","open","high","low","close","volume","complete"]
                assert not differences(frame[columns],market.candles("USD_JPY",foot,250)[columns],"USD_JPY")


def test_future_prices_never_enter_aggregation():
    before = [bar(s) for s in range(0,600,5)]
    after = before[:60] + [bar(s,o=160,h=161,low=159,close=160) for s in range(300,600,5)]
    a,b=Dataset("USD_JPY",before),Dataset("USD_JPY",after)
    at=START+timedelta(seconds=300)
    assert digest(a.frames(at))==digest(b.frames(at))
    assert a.observed_index(START)==-1
    assert a.observed_index(START+timedelta(seconds=5))==0


@pytest.mark.parametrize("pair",("USD_JPY","EUR_USD","AUD_USD"))
def test_independent_native_preparation_and_order_conversion(sources,pair):
    request=request_for(pair)
    native=NativeAnalysis(sources).evaluate(request)
    evaluation=MainSourceAnalysis(source_directory=sources.directory,analysis_name="resistance_breakout").evaluate(request)
    assert native["candidates"], "fixture must exercise positive order creation"
    assert not compare_candidates([comparable_candidate(c) for c in native["candidates"]],
                                  [comparable_candidate(c) for c in evaluation.candidates],pair)
    assert not differences(native["frames"],evaluation.frames,pair)
    assert not differences(native["facts"],evaluation_facts(evaluation),pair)
    assert not differences(native["signals"],evaluation.diagnostics["analysis"],pair)


@pytest.mark.parametrize("direction",(1,-1))
def test_both_hits_choose_sl_exactly_at_stop_price(sources,direction):
    if direction==1:
        candles=[bar(0,h=150.15,close=150.1),bar(5,o=150.1,h=150.25,low=149.85,close=150)]
    else:
        candles=[bar(0,low=149.85,close=149.9),bar(5,o=149.9,h=150.15,low=149.75,close=150)]
    a,b,_,delta,causes=compare_execution(sources,candles,candidate(direction))
    assert a["reason"]==b["reason"]=="sl"
    assert a["exit_price"]==pytest.approx(b["exit_price"])
    assert not delta and not causes


def test_intrabar_entry_tp_matches_main_in_fill_bar(sources):
    candles=[bar(0,h=150.25,close=150.15),bar(5,o=150.15,h=150.17,low=150.1,close=150.15)]
    a,b,_,delta,causes=compare_execution(sources,candles)
    assert a["reason"]==b["reason"]=="tp"
    assert a["close_bar"]==b["close_bar"]==a["fill_bar"]
    assert not delta and not causes


def test_stop_gap_fills_at_target_plus_slippage(sources):
    candles=[bar(0,o=150.15,h=150.18,low=150.12,close=150.16),bar(5,o=150.16,h=150.25,low=150.14,close=150.22)]
    a,b,_,delta,causes=compare_execution(sources,candles)
    assert a["entry_price"]==pytest.approx(150.105)
    assert b["entry_price"]==pytest.approx(150.105)
    assert not delta and not causes


def test_unfilled_deadline(sources):
    a,b,events,_,_=compare_execution(sources,[bar(s) for s in range(0,3700,5)])
    assert not a["filled"] and not b["filled"]
    assert any(e["event"]=="CANCEL" and e["reason"]=="ORDER_TIMEOUT" for e in events)


def test_fill_timeout_and_next_available_open(sources):
    candles=[bar(0,h=150.15,close=150.11)]
    candles += [bar(s,o=150.11,h=150.13,low=150.09,close=150.11) for s in range(5,3620,5)]
    a,b,events,delta,causes=compare_execution(sources,candles)
    assert a["reason"]==b["reason"]=="timeout"
    assert a["close_bar"]==b["close_bar"]
    assert a["exit_price"]==pytest.approx(b["exit_price"])
    assert not delta and not causes


def test_pending_deadline_boundary_inclusion(sources):
    quiet=[bar(s) for s in range(0,3600,5)]
    fill_bar=bar(3600,h=150.15,close=150.1)
    after=[bar(s,o=150.1,h=150.25,low=150.05,close=150.2) for s in range(3605,3900,5)]
    a,b,_,delta,causes=compare_execution(sources,quiet+[fill_bar]+after)
    # main includes the bar starting exactly at the deadline in the fill search.
    assert a["filled"] and b["filled"]
    assert a["fill_bar"]==b["fill_bar"]
    assert not delta and not causes


def test_pending_deadline_boundary_exclusion(sources):
    quiet=[bar(s) for s in range(0,3600,5)]
    late=bar(3605,h=150.15,close=150.1)
    a,b,events,delta,causes=compare_execution(sources,quiet+[late])
    assert not a["filled"] and not b["filled"]
    assert any(e["event"]=="CANCEL" and e["reason"]=="ORDER_TIMEOUT" for e in events)
    assert not delta and not causes


def test_timeout_without_coverage_stays_open_on_both_sides(sources):
    candles=[bar(0,h=150.15,close=150.11)]
    candles += [bar(s,o=150.11,h=150.13,low=150.09,close=150.11) for s in range(5,900,5)]
    candles += [bar(s,o=150.11,h=150.13,low=150.09,close=150.11) for s in range(3600,3700,5)]
    a,b,_,delta,causes=compare_execution(sources,candles)
    # coverage 25% <= 50%: main's verifier reports not_closed; the replay mirrors it.
    assert a["reason"]==b["reason"]=="open"
    assert not delta and not causes


def test_uncovered_timeout_ignores_post_deadline_protection_hits(sources):
    candles=[bar(0,h=150.15,close=150.11)]
    candles += [bar(s,o=150.11,h=150.13,low=150.09,close=150.11) for s in range(5,900,5)]
    candles += [bar(s,o=149.7,h=149.75,low=149.65,close=149.7) for s in range(3600,3700,5)]
    a,b,_,delta,causes=compare_execution(sources,candles)
    # main never inspects bars past the holding deadline, so the SL there is invisible.
    assert a["reason"]==b["reason"]=="open"
    assert not delta and not causes


def test_timeout_with_window_end_short_of_deadline_stays_open(sources):
    candles=[bar(0,h=150.15,close=150.11)]
    candles += [bar(s,o=150.11,h=150.13,low=150.09,close=150.11) for s in range(5,3595,5)]
    candles += [bar(s,o=150.11,h=150.13,low=150.09,close=150.11) for s in range(3600,3700,5)]
    a,b,_,delta,causes=compare_execution(sources,candles)
    # one missing five-second bar keeps the window short of the deadline on both sides.
    assert a["reason"]==b["reason"]=="open"
    assert not delta and not causes


def test_sl_amendment_and_horizon_open_parity(sources):
    candles=[bar(0,h=150.15,close=150.11),bar(5,o=150.11,h=150.13,low=150.06,close=150.1)]
    a,b,events,_,_=compare_execution(sources,candles,amendments=((0,150.08),))
    assert any(e["event"]=="AMEND" for e in events)
    # main's verifier has no amendment concept, so only the replay closes here.
    assert b["reason"]=="sl" and a["reason"]=="open"
    a,b,_,delta,causes=compare_execution(sources,candles)
    assert a["reason"]==b["reason"]=="open"
    assert b["pnl_quote"] is None
    assert not delta and not causes


def test_offline_boundary_in_dedicated_worker():
    code = """
import socket
from scripts.backtest_comparison.runner import deny_network
deny_network()
for action in (lambda: socket.socket().connect(('127.0.0.1', 9)), lambda: open('/tmp/tokens.py')):
    try:
        action()
    except RuntimeError:
        pass
    else:
        raise AssertionError('offline boundary did not reject operation')
"""
    subprocess.run([sys.executable,"-c",code],check=True,cwd=Path(__file__).resolve().parents[1])


def test_repeat_hashes_detect_changes_but_ignore_progress(tmp_path):
    (tmp_path/"analysis.jsonl").write_text('{"at":"example"}\n')
    (tmp_path/"progress.json").write_text(json.dumps({"elapsed":1}))
    first=normalized_hashes(tmp_path)
    (tmp_path/"progress.json").write_text(json.dumps({"elapsed":2}))
    assert normalized_hashes(tmp_path)==first
    (tmp_path/"analysis.jsonl").write_text('{"at":"changed"}\n')
    assert normalized_hashes(tmp_path)!=first


def test_expected_closure_is_not_an_evaluation_failure(sources, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from scripts.backtest_comparison.runner import Artifacts, run_analysis
    message = 'OANDA market is closed at the decision time'
    calls = {'native':0,'adapter':0}

    def native_closed(self, request):
        calls['native'] += 1
        raise ValueError(message)

    def adapter_closed(self, request):
        calls['adapter'] += 1
        return SimpleNamespace(status='not_ready',diagnostics={'reason':message})

    monkeypatch.setattr(NativeAnalysis,'evaluate',native_closed)
    monkeypatch.setattr(MainSourceAnalysis,'evaluate',adapter_closed)
    start = datetime(2024,9,1,tzinfo=timezone.utc)
    request = request_for()
    dataset = SimpleNamespace(pair='USD_JPY',frames=lambda at, counts:(request.candle_frames,150,pd.Timestamp(at)))
    artifacts = Artifacts(tmp_path/'closure','USD_JPY')
    try:
        _,result=run_analysis(dataset,sources,start,start+timedelta(hours=2),artifacts,lambda *args:None)
        assert result['market_closed']==result['scheduled']==24
        assert result.get('errors_or_not_ready',0)==0
        assert not artifacts.categories
        assert calls=={'native':1,'adapter':1}
    finally:
        artifacts.close()


def test_same_output_controller_lock_rejects_second_writer(tmp_path):
    from scripts.backtest_comparison.controller import controller_lock
    with controller_lock(tmp_path):
        with pytest.raises(ValueError,match='already running'):
            with controller_lock(tmp_path):
                pass


def test_native_reported_money_mixes_ideal_and_rounded_lc_width():
    from scripts.backtest_comparison.audit import monetary_difference
    record={'at':'2024-09-01T21:35:00+00:00','ordinal':0,
            'candidate':{'pair':'EUR_USD','direction':-1,'units':3000,
                         'metadata':{'usd_jpy_rate':160.0,'lc_pips':2.54166666666759,'actual_risk_yen':122.0}},
            'main':{'reported_yen':-146.4,'pnl_quote':-.9,'entry_price':1.10454,'exit_price':1.10484},
            'main_raw':{'lc_pips':2.5}}
    result=monetary_difference(record)
    assert result['price_quantity_yen']==pytest.approx(-144)
    assert result['difference_yen']==pytest.approx(-2.4)
    record['main']['reported_yen']=-144
    assert monetary_difference(record) is None
    record['main']['pnl_quote']=None
    assert monetary_difference(record) is None


@pytest.mark.parametrize('second,reason,price', [
    (bar(5,o=149.8,h=149.85,low=149.75,close=149.8),'sl',149.9),
    (bar(5,o=150.3,h=150.4,low=150.25,close=150.3),'tp',150.2),
])
def test_exit_gaps_close_exactly_at_protection_prices(sources,second,reason,price):
    a,b,_,delta,causes=compare_execution(sources,[bar(0,h=150.15,close=150.1),second])
    assert a["reason"]==b["reason"]==reason
    assert a["exit_price"]==pytest.approx(price)
    assert b["exit_price"]==pytest.approx(price)
    assert not delta and not causes
