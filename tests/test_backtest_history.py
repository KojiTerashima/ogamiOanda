from datetime import datetime, timedelta, timezone

import pytest

from ogami_oanda.domain.market.history import HistoricalCandle, OHLC

START = datetime(2024, 1, 2, tzinfo=timezone.utc)


def candle(at=START):
    return HistoricalCandle(at, OHLC(150, 151, 149, 150),
                            OHLC(149.99, 150.99, 148.99, 149.99),
                            OHLC(150.01, 151.01, 149.01, 150.01))


def test_store_roundtrip_coverage_integrity_and_resumption(tmp_path):
    from ogami_oanda.adapters.repositories.historical_store import HistoricalStore

    store = HistoricalStore(tmp_path, "USD_JPY")
    end = START + timedelta(hours=6)
    store.write_interval(START, end, [candle()])
    assert store.covers(START, end)
    assert not store.covers(START, end + timedelta(seconds=5))
    assert list(store.read(START, end)) == [candle()]
    store.validate(START, end)
    reopened = HistoricalStore(tmp_path, "USD_JPY")
    assert reopened.covers(START, end)
    path = next(tmp_path.glob("*.csv.gz"))
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="hash"):
        reopened.validate(START, end)


def test_downloader_resume_empty_windows_and_no_count(tmp_path):
    from ogami_oanda.adapters.repositories.historical_store import HistoricalStore
    from ogami_oanda.application.services.history_download import download_history

    store = HistoricalStore(tmp_path, "USD_JPY")

    class Source:
        calls = []

        def fetch(self, pair, start, end):
            self.calls.append((pair, start, end))
            return [candle(start)] if start == START else []

    source = Source()
    end = START + timedelta(hours=13)
    download_history(source, store, START, end, sleep=lambda _: None)
    assert len(source.calls) == 3
    assert all((b - a) <= timedelta(hours=6) for _, a, b in source.calls)
    download_history(source, store, START, end, sleep=lambda _: None)
    assert len(source.calls) == 3
    assert store.covers(START, end)


def test_download_keeps_completed_progress_when_retry_exhausts(tmp_path):
    from ogami_oanda.adapters.repositories.historical_store import HistoricalStore
    from ogami_oanda.application.errors import TransientExternalServiceError
    from ogami_oanda.application.services.history_download import download_history

    store = HistoricalStore(tmp_path, "USD_JPY")
    pauses = []

    class Source:
        def fetch(self, pair, start, end):
            if start == START:
                return [candle()]
            raise TransientExternalServiceError("oanda", "temporary")

    with pytest.raises(TransientExternalServiceError):
        download_history(Source(), store, START, START + timedelta(hours=12), sleep=pauses.append)
    assert pauses == [1, 2, 4]
    assert store.covers(START, START + timedelta(hours=6))
    assert not store.covers(START, START + timedelta(hours=12))


def test_store_rejects_duplicate_and_reverse_candles(tmp_path):
    from ogami_oanda.adapters.repositories.historical_store import HistoricalStore

    store = HistoricalStore(tmp_path, "USD_JPY")
    with pytest.raises(ValueError, match="order"):
        store.write_interval(START, START + timedelta(hours=6), [candle(), candle()])
    with pytest.raises(ValueError, match="order"):
        store.write_interval(START, START + timedelta(hours=6), [candle(START + timedelta(seconds=5)), candle()])


def test_mid_csv_requires_explicit_spread_and_normalizes_legacy_time(tmp_path):
    from ogami_oanda.adapters.repositories.historical_store import read_mid_csv

    path = tmp_path / "legacy.csv"
    path.write_text("time_jp,open,high,low,close\n2024/01/02 09:00:00,150,151,149,150\n")
    with pytest.raises(ValueError, match="spread"):
        list(read_mid_csv(path, "USD_JPY", None))
    bars = list(read_mid_csv(path, "USD_JPY", 2))
    assert bars[0].time == START
    assert bars[0].ask.close - bars[0].bid.close == pytest.approx(.02)


def test_oanda_source_sends_only_historical_candle_request():
    from ogami_oanda.adapters.oanda.history import OandaHistorySource

    class Client:
        def request(self, endpoint):
            assert endpoint.params["granularity"] == "S5"
            assert endpoint.params["price"] == "MBA"
            assert "count" not in endpoint.params
            assert endpoint.params["from"] == START.isoformat()
            return {"candles": [{"time": START.isoformat(), "complete": True, "volume": 3,
                                  **{key: dict(o="150", h="151", l="149", c="150") for key in ("mid", "bid", "ask")}}]}

    bars = OandaHistorySource(Client()).fetch("USD_JPY", START, START + timedelta(hours=6))
    assert len(bars) == 1
    assert bars[0].volume == 3


def test_downloader_can_extend_a_partially_acquired_window(tmp_path):
    from ogami_oanda.adapters.repositories.historical_store import HistoricalStore
    from ogami_oanda.application.services.history_download import download_history

    store = HistoricalStore(tmp_path, "USD_JPY")

    class Source:
        def fetch(self, pair, start, end):
            return [candle(start)]

    download_history(Source(), store, START, START + timedelta(hours=1), sleep=lambda _: None)
    download_history(Source(), store, START, START + timedelta(hours=7), sleep=lambda _: None)
    assert store.covers(START, START + timedelta(hours=7))


def test_history_validation_checks_full_day_rows_before_replay(tmp_path):
    from ogami_oanda.adapters.repositories.historical_store import HistoricalStore

    store = HistoricalStore(tmp_path, "USD_JPY")
    store.write_interval(START, START + timedelta(hours=6), [candle()])
    store.write_interval(START + timedelta(hours=6), START + timedelta(hours=12), [])
    store.manifest["files"]["2024-01-02"]["rows"] = 999
    with pytest.raises(ValueError, match="count"):
        store.validate(START, START + timedelta(hours=12))


def test_downloader_only_fetches_gaps_and_normalizes_utc_days(tmp_path):
    from ogami_oanda.adapters.repositories.historical_store import HistoricalStore
    from ogami_oanda.application.services.history_download import download_history

    store = HistoricalStore(tmp_path, 'USD_JPY')
    store.write_interval(START + timedelta(hours=1), START + timedelta(hours=2), [])
    calls = []
    class Source:
        def fetch(self, pair, start, end):
            calls.append((start, end))
            return []
    offset = timezone(timedelta(hours=9))
    download_history(Source(), store, START.astimezone(offset), (START + timedelta(hours=3)).astimezone(offset), sleep=lambda _: None)
    assert calls == [(START, START + timedelta(hours=1)), (START + timedelta(hours=2), START + timedelta(hours=3))]
    assert all(left.tzinfo is timezone.utc for left, _ in calls)


def test_validation_checks_acquisition_counts_and_uncovered_file_rows(tmp_path):
    from ogami_oanda.adapters.repositories.historical_store import HistoricalStore

    store = HistoricalStore(tmp_path, 'USD_JPY')
    store.write_interval(START, START + timedelta(hours=6), [candle()])
    store.manifest['intervals'][0]['count'] = 0
    with pytest.raises(ValueError, match='count'):
        store.validate(START, START + timedelta(hours=6))
    store.manifest['intervals'][0]['count'] = 1
    store.manifest['intervals'][0]['from'] = (START + timedelta(seconds=5)).isoformat()
    with pytest.raises(ValueError, match='outside|acquisition'):
        store.validate(START + timedelta(seconds=5), START + timedelta(hours=6))


def test_full_day_preflight_parses_rows_even_when_hash_matches(tmp_path):
    import gzip
    from ogami_oanda.adapters.repositories.historical_store import HistoricalStore, file_hash

    store = HistoricalStore(tmp_path, 'USD_JPY')
    store.write_interval(START, START + timedelta(hours=6), [candle()])
    store.write_interval(START + timedelta(hours=6), START + timedelta(hours=12), [])
    entry = store.manifest['files']['2024-01-02']
    path = tmp_path / entry['path']
    original = gzip.decompress(path.read_bytes()).decode()
    lines = original.splitlines()
    fields = lines[1].split(',')
    fields[1] = 'not-a-price'
    lines[1] = ','.join(fields)
    path.write_bytes(gzip.compress(('\n'.join(lines) + '\n').encode()))
    entry['sha256'] = file_hash(path)
    with pytest.raises(ValueError, match='candle|row'):
        store.validate(START, START + timedelta(hours=12))


def test_interrupted_manifest_commit_retains_old_snapshot(tmp_path, monkeypatch):
    from ogami_oanda.adapters.repositories import historical_store as module

    store = module.HistoricalStore(tmp_path, 'USD_JPY')
    store.write_interval(START, START + timedelta(hours=1), [candle()])
    before = store.manifest_path.read_bytes()
    def interrupt(*args):
        raise OSError('interrupted manifest commit')
    monkeypatch.setattr(module, 'atomic_json', interrupt)
    with pytest.raises(OSError):
        store.write_interval(START + timedelta(hours=1), START + timedelta(hours=2), [])
    assert store.manifest_path.read_bytes() == before
    reopened = module.HistoricalStore(tmp_path, 'USD_JPY')
    reopened.validate(START, START + timedelta(hours=1))
    assert list(reopened.read(START, START + timedelta(hours=1))) == [candle()]
    assert not reopened.covers(START, START + timedelta(hours=2))


def test_authorization_failure_is_not_retried_or_recorded(tmp_path):
    from ogami_oanda.adapters.repositories.historical_store import HistoricalStore
    from ogami_oanda.application.errors import ExternalServiceAuthorizationError
    from ogami_oanda.application.services.history_download import download_history

    store = HistoricalStore(tmp_path, 'USD_JPY')
    attempts = []
    pauses = []
    class Source:
        def fetch(self, *args):
            attempts.append(1)
            raise ExternalServiceAuthorizationError('oanda', status_code=401, operation='InstrumentsCandles')
    with pytest.raises(ExternalServiceAuthorizationError):
        download_history(Source(), store, START, START + timedelta(hours=6), sleep=pauses.append)
    assert len(attempts) == 1
    assert pauses == []
    assert not store.manifest_path.exists()


@pytest.mark.parametrize('response', [
    {'candles': [{'time': 'sensitive-response-fragment'}]},
    {'candles': [{'time': START.isoformat(), 'complete': True, 'mid': {'o': 'sensitive-response-fragment'}}]},
    {'other': 'sensitive-response-fragment'},
])
def test_malformed_oanda_history_is_reported_without_response_leak(response):
    from ogami_oanda.adapters.oanda.history import OandaHistorySource

    class Client:
        def request(self, endpoint):
            return response
    with pytest.raises(ValueError, match='historical candle') as error:
        OandaHistorySource(Client()).fetch('USD_JPY', START, START + timedelta(hours=6))
    assert 'sensitive-response-fragment' not in str(error.value)


def test_oanda_history_sanitizes_exhausted_retry_error(tmp_path):
    from ogami_oanda.adapters.oanda.history import OandaHistorySource
    from ogami_oanda.adapters.repositories.historical_store import HistoricalStore
    from ogami_oanda.application.errors import TransientExternalServiceError
    from ogami_oanda.application.services.history_download import download_history

    class Client:
        def request(self, endpoint):
            raise TransientExternalServiceError('oanda', 'sensitive-response-fragment', retry_after_seconds=3)
    pauses = []
    with pytest.raises(TransientExternalServiceError) as error:
        download_history(OandaHistorySource(Client()), HistoricalStore(tmp_path, 'USD_JPY'), START, START + timedelta(hours=6), sleep=pauses.append)
    assert 'sensitive-response-fragment' not in str(error.value)
    assert pauses == [3, 3, 4]


@pytest.mark.parametrize('payload', [[], {'schema_version': 1, 'pair': 'USD_JPY', 'price_mode': 'MBA', 'files': {}, 'intervals': [{'from': START.isoformat(), 'to': START.isoformat(), 'count': 0}]}])
def test_store_rejects_invalid_manifest_shape_or_intervals(tmp_path, payload):
    import json
    from ogami_oanda.adapters.repositories.historical_store import HistoricalStore

    (tmp_path / 'manifest.json').write_text(json.dumps(payload))
    with pytest.raises(ValueError, match='manifest|interval'):
        HistoricalStore(tmp_path, 'USD_JPY')


def test_missing_daily_file_cannot_claim_acquired_coverage(tmp_path):
    from ogami_oanda.adapters.repositories.historical_store import HistoricalStore

    store = HistoricalStore(tmp_path, 'USD_JPY')
    store.write_interval(START, START + timedelta(hours=1), [])
    store.manifest['files'].clear()
    with pytest.raises(ValueError, match='missing'):
        store.validate(START, START + timedelta(hours=1))


def test_manifest_replace_interruption_does_not_publish_partial_progress(tmp_path, monkeypatch):
    from ogami_oanda.adapters.repositories import historical_store as module

    store = module.HistoricalStore(tmp_path, 'USD_JPY')
    store.write_interval(START, START + timedelta(hours=1), [candle()])
    old_bytes = store.manifest_path.read_bytes()
    replace = module.os.replace
    def fail_manifest(source, destination):
        if destination == store.manifest_path:
            raise OSError('interrupted replace')
        replace(source, destination)
    monkeypatch.setattr(module.os, 'replace', fail_manifest)
    with pytest.raises(OSError):
        store.write_interval(START + timedelta(hours=1), START + timedelta(hours=2), [])
    assert store.manifest_path.read_bytes() == old_bytes
    assert not store.covers(START, START + timedelta(hours=2))
    reopened = module.HistoricalStore(tmp_path, 'USD_JPY')
    reopened.validate(START, START + timedelta(hours=1))
    assert all(path.name == 'manifest.json' or path.name.endswith('.csv.gz') for path in tmp_path.iterdir())


def test_history_source_enforces_six_hour_limit_before_request():
    from ogami_oanda.adapters.oanda.history import OandaHistorySource

    class Client:
        def request(self, endpoint):
            raise AssertionError('invalid range must never reach the broker')
    with pytest.raises(ValueError, match='six hours'):
        OandaHistorySource(Client()).fetch('USD_JPY', START, START + timedelta(hours=7))


def test_download_lock_rejects_competing_writers_without_mutation(tmp_path):
    from ogami_oanda.adapters.repositories.historical_store import HistoricalStore

    first = HistoricalStore(tmp_path, 'USD_JPY')
    second = HistoricalStore(tmp_path, 'USD_JPY')
    with first.download_lock():
        first.write_interval(START, START + timedelta(hours=1), [])
        before = first.manifest_path.read_bytes()
        with pytest.raises(ValueError, match='already|writer|lock'):
            with second.download_lock():
                pytest.fail('second writer acquired the lock')
        assert first.manifest_path.read_bytes() == before
    with second.download_lock():
        assert second.covers(START, START + timedelta(hours=1))
        second.write_interval(START + timedelta(hours=1), START + timedelta(hours=2), [])
    reopened = HistoricalStore(tmp_path, 'USD_JPY')
    reopened.validate(START, START + timedelta(hours=2))


def test_download_lock_is_released_after_exception(tmp_path):
    from ogami_oanda.adapters.repositories.historical_store import HistoricalStore

    store = HistoricalStore(tmp_path, 'USD_JPY')
    with pytest.raises(RuntimeError):
        with store.download_lock():
            raise RuntimeError('interrupted download')
    with HistoricalStore(tmp_path, 'USD_JPY').download_lock():
        pass


def test_existing_reader_retains_immutable_daily_snapshot_after_append(tmp_path):
    from ogami_oanda.adapters.repositories.historical_store import HistoricalStore

    writer = HistoricalStore(tmp_path, 'USD_JPY')
    first_end = START + timedelta(hours=6)
    writer.write_interval(START, first_end, [candle()])
    reader = HistoricalStore(tmp_path, 'USD_JPY')
    pinned_file = reader.manifest['files']['2024-01-02']['path']
    writer.write_interval(first_end, first_end + timedelta(hours=6), [candle(first_end)])
    assert (tmp_path / pinned_file).exists()
    reader.validate(START, first_end)
    assert list(reader.read(START, first_end)) == [candle()]
