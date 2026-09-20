"""Offline progress/ETA contracts: conditional work, restart, and stopped jobs."""

from datetime import datetime, timezone
import json
import os
import threading
import time
from pathlib import Path

import pytest

from scripts.backtest_comparison.common import write_json
from scripts.backtest_comparison.progress import (
    build_status, last_record, local_time, observer_lock, render, update_rates,
)


START = "2024-09-01T00:00:00+00:00"
PILOT = "2024-09-08T00:00:00+00:00"
MONTH = "2024-10-01T00:00:00+00:00"
NOW = datetime(2026, 9, 17, tzinfo=timezone.utc).timestamp()
OPEN = datetime(2024, 9, 1, 21, tzinfo=timezone.utc).timestamp()
CONDITIONS = {"from": START, "pilot_to": PILOT, "max_to": MONTH, "pairs": ["USD_JPY"]}
CALENDARS = {PILOT: tuple(OPEN+300*i for i in range(24)), MONTH: tuple(OPEN+300*i for i in range(120))}


def job(root, *, end=PILOT, attempt="run", units=12, elapsed=120, stamp=NOW,
        stage="analysis", complete=False, extension=False, failed=False):
    directory = root/f"{START[:10]}_{end[:10]}"/"USD_JPY"/attempt
    write_json(directory/"progress.json", {
        "status": "complete" if complete else "running", "stage": stage,
        "elapsed_seconds": elapsed, "at": datetime.fromtimestamp(OPEN+300*units, timezone.utc).isoformat(),
        "counts": {"scheduled": units+252, "evaluated": units, "market_closed": 252}})
    os.utime(directory/"progress.json", (stamp, stamp))
    if complete:
        write_json(directory/"result.json", {"status": "complete", "needs_extension": extension})
        write_json(directory/"normalized-hashes.json", {})
    if failed:
        write_json(directory/"result.json", {"status": "failed"})
    return directory


def status(root, controller=None, **kwargs):
    return build_status(root, CONDITIONS, controller or {"status": "running", "workers": 1},
                        now=NOW, calendars=CALENDARS, **kwargs)


def test_progress_excludes_closed_slots_and_includes_both_repeat_scenarios(tmp_path):
    job(tmp_path)
    result = status(tmp_path)
    assert result["pairs"][0]["current"]["phase_percent"] == 50
    short = result["scenarios"]["without_optional_extension"]
    long = result["scenarios"]["with_optional_extension"]
    assert short["total_units"] == 24*3*2
    assert short["percent"] == 8.33
    assert short["remaining_seconds"] == 1320
    assert long["total_units"] == 24*3+120*3*2
    assert long["remaining_seconds"] == 7800
    assert "2026-09-17 09:22:00 JST" in render(result)
    assert short["assumed_analysis_speed_for"] == ["C-fixed", "C-mba"]


def test_missing_samples_and_initial_preparation_never_mean_complete(tmp_path):
    result = status(tmp_path)
    assert all(item["percent"] == 0 and item["estimated_finish"] is None for item in result["scenarios"].values())
    job(tmp_path, stage="load", units=0)
    result = status(tmp_path)
    assert result["pairs"][0]["current"]["phase_percent"] == 0
    assert all(item["estimated_finish"] is None for item in result["scenarios"].values())


def test_extension_and_restart_select_new_attempt_without_double_counting(tmp_path):
    job(tmp_path, complete=True, extension=True, stamp=NOW-1000)
    job(tmp_path, end=MONTH, stamp=NOW-500)
    latest = job(tmp_path, end=MONTH, attempt="run-2", elapsed=10, units=0)
    result = status(tmp_path)
    assert result["pairs"][0]["current"]["directory"] == str(latest)
    assert list(result["scenarios"]) == ["selected"]
    assert result["scenarios"]["selected"]["done_units"] == 72
    assert result["scenarios"]["selected"]["total_units"] == 792


def test_reports_must_finish_before_progress_reaches_one_hundred(tmp_path):
    job(tmp_path, complete=True, stamp=NOW-300)
    job(tmp_path, attempt="repeat", complete=True)
    result = status(tmp_path)
    assert result["scenarios"]["selected"]["percent"] == 99.9
    assert result["scenarios"]["selected"]["estimated_finish"] is None
    assert status(tmp_path, {"status": "complete"})["scenarios"]["selected"]["percent"] == 100


@pytest.mark.parametrize("controller,active,stamp", [
    ({"status": "running"}, False, NOW),
    ({"status": "failed"}, True, NOW),
    ({"status": "running"}, True, NOW-901),
])
def test_no_completion_forecast_for_stopped_failed_or_stale_job(tmp_path, controller, active, stamp):
    job(tmp_path, stamp=stamp)
    result = status(tmp_path, controller, active=active)
    assert all(item["estimated_finish"] is None for item in result["scenarios"].values())
    assert all(item["percent"] < 100 for item in result["scenarios"].values())


def test_live_trace_tail_can_advance_older_worker_progress_without_rewriting_it(tmp_path):
    directory = job(tmp_path)
    original = (directory/"progress.json").read_bytes()
    latest = datetime.fromtimestamp(OPEN+300*17, timezone.utc).isoformat()
    trace = directory/"analysis.jsonl"
    trace.write_text(json.dumps({"at": latest})+'\n{"at":')
    os.utime(trace, (NOW, NOW))
    result = status(tmp_path)
    assert result["pairs"][0]["current"]["phase_percent"] == 75
    assert (directory/"progress.json").read_bytes() == original
    assert last_record(trace) == latest


def test_stage_slope_uses_elapsed_measurements_and_survives_monitor_restart():
    first = {"directory": "run", "stage": "C-fixed", "status": "running", "units": 5, "elapsed_seconds": 500}
    state = update_rates([("USD_JPY", first)], {})
    later = {**first, "units": 25, "elapsed_seconds": 560}
    state = update_rates([("USD_JPY", later)], json.loads(json.dumps(state)))
    assert state["rates"]["USD_JPY:C-fixed"] == 3
    assert update_rates([("USD_JPY", later)], state) == state


def test_observer_excludes_duplicate_writers_and_releases_lock(tmp_path):
    with observer_lock(tmp_path), pytest.raises(ValueError, match="already running"):
        with observer_lock(tmp_path):
            pass
    with observer_lock(tmp_path):
        assert local_time("2026-09-17T00:00:00+00:00") == "2026-09-17 09:00:00 JST"


def test_serial_pairs_take_longer_than_parallel_pairs(tmp_path):
    directory = job(tmp_path)
    conditions = {**CONDITIONS, "pairs": ["USD_JPY", "EUR_USD"]}
    values = []
    for workers in (1, 2):
        result = build_status(tmp_path, conditions, {"status": "running", "workers": workers},
                              now=NOW, calendars=CALENDARS)
        values.append(result["scenarios"]["without_optional_extension"]["remaining_seconds"])
    assert directory.is_dir()
    assert values == [2760, 1440]


def test_large_or_incomplete_tail_does_not_parse_fragments_as_progress(tmp_path):
    path = Path(tmp_path)/"trace.jsonl"
    path.write_text('{"at":"2024-01-01", "large":"'+'x'*100_000+'"}\n')
    assert last_record(path) is None
    path.write_text('time,balance\n2024-09-01T21:00:05+00:00,100\n2024-09-01T21:00')
    assert last_record(path, csv=True) == "2024-09-01T21:00:05+00:00"
    path.write_text("time,balance\n")
    assert last_record(path, csv=True) is None


def test_failed_worker_suppresses_eta_while_other_controller_tasks_finish(tmp_path):
    job(tmp_path, failed=True)
    result = status(tmp_path)
    assert result["status"] == "failed"
    assert all(item["estimated_finish"] is None for item in result["scenarios"].values())


def test_frozen_controller_worker_count_is_retained_after_partial_completion(tmp_path):
    job(tmp_path)
    conditions = {**CONDITIONS, "pairs": ["USD_JPY", "EUR_USD"]}
    first = build_status(tmp_path, conditions, {"status": "running", "workers": 1},
                         now=NOW, calendars=CALENDARS)
    later = build_status(tmp_path, conditions, {"status": "running", "completed": {}},
                         first["estimator_state"], now=NOW, calendars=CALENDARS)
    assert later["scenarios"] == first["scenarios"]


def test_automatic_observer_publishes_terminal_state_and_releases_writer_lock(tmp_path, monkeypatch):
    from scripts.backtest_comparison import progress
    from scripts.backtest_comparison.controller import controller_lock

    write_json(tmp_path/"conditions.json", CONDITIONS)
    write_json(tmp_path/"controller.json", {"status": "running", "workers": 1})
    job(tmp_path, stamp=time.time())
    monkeypatch.setattr(progress, "open_slots", lambda root, start, end: CALENDARS[end])
    published = threading.Event()
    refresh = progress.refresh

    def observe(root):
        result = refresh(root)
        published.set()
        return result

    monkeypatch.setattr(progress, "refresh", observe)
    with controller_lock(tmp_path):
        with progress.background_progress(tmp_path):
            assert published.wait(5)
            assert json.loads((tmp_path/"progress.json").read_text())["status"] == "running"
            job(tmp_path, complete=True)
            job(tmp_path, attempt="repeat", complete=True)
            write_json(tmp_path/"controller.json", {"status": "complete", "workers": 1})
        assert json.loads((tmp_path/"progress.json").read_text())["status"] == "complete"
        assert "100.0%" in (tmp_path/"RUNNING.md").read_text()
    with observer_lock(tmp_path):
        pass
