from __future__ import annotations

import json
from datetime import datetime

import pytest

from ogami_oanda.adapters.repositories.json_position_state import (
    JsonPositionStateRepository,
    PositionStateWriteError,
)
from ogami_oanda.application.ports.position_state import (
    CheckpointLoadStatus,
    PortfolioAnalyticsState,
    PositionStateCheckpoint,
    account_identity_hash,
)
from ogami_oanda.application.services.order_planner import OrderPlanner
from ogami_oanda.domain.orders.models import (
    Direction,
    OrderContext,
    OrderIntent,
    OrderType,
)
from ogami_oanda.domain.positions.managed_position import ManagedPosition


def _checkpoint(account_id="account-1", *, transaction_cursor="100"):
    plan = OrderPlanner().plan(
        OrderIntent(
            pair="USD_JPY",
            direction=Direction.BUY,
            order_type=OrderType.STOP,
            target=150.1,
            target_is_price=True,
            take_profit=0.2,
            take_profit_is_price=False,
            stop_loss=0.1,
            stop_loss_is_price=False,
            units=100,
            name="persisted-position",
            priority=10,
            order_timeout_min=30,
            trade_timeout_min=240,
            lc_change=(
                {
                    "exe": True,
                    "trigger": 0.03,
                    "ensure": 0.01,
                    "time_after": 60,
                },
            ),
            metadata={
                "source": "line",
                "line_strategy": "restart-contract",
                "linkage_id": "link-1",
                "linkage_order_names": ("linked-position",),
                "trade_timeout_enabled": False,
                "name_ymdhms": "persisted-position_2026/01/02 10:00:00",
                "memo": "checkpoint",
                "unsupported_runtime_object": object(),
            },
        ),
        OrderContext(150.0, "2026/01/02 10:00:00", 0.04),
    )
    position = (
        ManagedPosition.registered("persisted-position", "USD_JPY")
        .with_order_plan(plan, datetime(2026, 1, 2, 10, 0, 0))
        .pending("order-1")
        .filled(
            "trade-1",
            datetime(2026, 1, 2, 10, 1, 0),
            order_id="order-1",
            fill_price=150.11,
        )
        .with_runtime(
            applied_lc_change_index=0,
            candle_stop_loss_done=True,
            linkage_done=True,
            close_requested=False,
            unrealized_pl=12.5,
            realized_pl=0.0,
            max_unrealized_pl=18.0,
            min_unrealized_pl=-3.0,
            submission_reason="",
        )
    )
    analytics = PortfolioAnalyticsState(
        total_yen=120.0,
        total_yen_max=150.0,
        total_yen_min=-20.0,
        total_price_diff=0.12,
        total_price_diff_max=0.15,
        total_price_diff_min=-0.02,
        total_pips=12.0,
        total_pips_max=15.0,
        total_pips_min=-2.0,
        plus_yen_position_num=2,
        minus_yen_position_num=1,
        lc_change_num=1,
        before_latest_price_diff=0.05,
        before_latest_pl_pips=5.0,
        before_latest_plu=5.0,
        before_latest_name="closed-position",
        history_plus_minus=(0.0, 5.0),
        history_names=("0", "closed-position"),
        history_name_plus_minus=(
            {"name": "closed-", "price_diff": 0.05, "pl_pips": 5.0},
        ),
        result_dic_arr=(
            {
                "name": "closed-position",
                "pair": "USD_JPY",
                "res": "50",
                "pl_per_units": 5.0,
            },
        ),
        result_row=7,
    )
    return PositionStateCheckpoint(
        account_hash=account_identity_hash(account_id),
        pair="USD_JPY",
        slots=(position,) + (None,) * 14,
        transaction_cursor=transaction_cursor,
        emitted_event_ids=frozenset({"trade_opened:trade-1"}),
        reported_event_ids=frozenset({"trade_closed:trade-old"}),
        analytics=analytics,
    )


@pytest.mark.contract
def test_json_position_state_round_trips_full_runtime_without_arbitrary_metadata(tmp_path):
    repository = JsonPositionStateRepository(tmp_path / "runtime.json")
    expected = _checkpoint()

    repository.save(expected)
    loaded = repository.load(
        expected_account_hash=expected.account_hash,
        expected_pair="USD_JPY",
    )

    assert loaded.status is CheckpointLoadStatus.LOADED
    assert loaded.checkpoint == expected
    raw = json.loads((tmp_path / "runtime.json").read_text(encoding="utf-8"))
    persisted_metadata = raw["slots"][0]["runtime"]["order_plan"]["intent"]["metadata"]
    assert "unsupported_runtime_object" not in persisted_metadata
    assert persisted_metadata["linkage_order_names"] == ["linked-position"]


@pytest.mark.contract
def test_json_position_state_uses_last_known_good_backup_when_primary_is_corrupt(tmp_path):
    path = tmp_path / "runtime.json"
    repository = JsonPositionStateRepository(path)
    first = _checkpoint(transaction_cursor="100")
    second = _checkpoint(transaction_cursor="101")
    repository.save(first)
    repository.save(second)
    path.write_text("{broken", encoding="utf-8")

    loaded = repository.load(
        expected_account_hash=first.account_hash,
        expected_pair="USD_JPY",
    )

    assert loaded.status is CheckpointLoadStatus.LOADED_FROM_BACKUP
    assert loaded.checkpoint == first


@pytest.mark.contract
def test_json_position_state_quarantines_corrupt_unknown_and_wrong_identity(tmp_path):
    path = tmp_path / "runtime.json"
    repository = JsonPositionStateRepository(path)
    expected = _checkpoint()
    repository.save(expected)

    wrong_account = repository.load(
        expected_account_hash=account_identity_hash("other-account"),
        expected_pair="USD_JPY",
    )
    wrong_pair = repository.load(
        expected_account_hash=expected.account_hash,
        expected_pair="EUR_USD",
    )
    assert wrong_account.status is CheckpointLoadStatus.ACCOUNT_MISMATCH
    assert wrong_pair.status is CheckpointLoadStatus.PAIR_MISMATCH

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["unexpected"] = True
    path.write_text(json.dumps(raw), encoding="utf-8")
    repository.backup_path.write_text("{also-broken", encoding="utf-8")
    unknown = repository.load(
        expected_account_hash=expected.account_hash,
        expected_pair="USD_JPY",
    )
    assert unknown.status is CheckpointLoadStatus.QUARANTINED
    assert unknown.checkpoint is None


@pytest.mark.contract
def test_json_position_state_preserves_old_state_when_atomic_replace_fails(tmp_path, monkeypatch):
    path = tmp_path / "runtime.json"
    repository = JsonPositionStateRepository(path)
    first = _checkpoint(transaction_cursor="100")
    repository.save(first)
    real_replace = repository._replace
    calls = 0

    def fail_new_primary(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated replace failure")
        return real_replace(source, destination)

    monkeypatch.setattr(repository, "_replace", fail_new_primary)

    with pytest.raises(PositionStateWriteError, match="simulated replace failure"):
        repository.save(_checkpoint(transaction_cursor="101"))

    loaded = JsonPositionStateRepository(path).load(
        expected_account_hash=first.account_hash,
        expected_pair="USD_JPY",
    )
    assert loaded.checkpoint == first


@pytest.mark.contract
def test_json_position_state_reports_missing_checkpoint(tmp_path):
    loaded = JsonPositionStateRepository(tmp_path / "missing.json").load(
        expected_account_hash=account_identity_hash("account-1"),
        expected_pair="USD_JPY",
    )

    assert loaded.status is CheckpointLoadStatus.MISSING
    assert loaded.checkpoint is None
