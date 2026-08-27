from __future__ import annotations

import json
from datetime import datetime

import pytest

from ogami_oanda.adapters.repositories.json_position_state import (
    JsonPositionStateRepository,
)
from ogami_oanda.application.ports.position_state import (
    BUILTIN_LINE_STRATEGY_ID,
    CheckpointLoadResult,
    CheckpointLoadStatus,
    PendingBrokerMutation,
    PositionStateCheckpoint,
    account_identity_hash,
)
from ogami_oanda.application.services.position_portfolio_service import (
    PortfolioStartupState,
    PositionPortfolioService,
)
from ogami_oanda.application.services.position_service import PositionService
from ogami_oanda.domain.positions.managed_position import ManagedPosition
from ogami_oanda.domain.positions.models import (
    OrderState,
    PositionSnapshot,
    TradeState,
)
from tests.fakes import (
    FakeBroker,
    FakeNotifier,
    FixedClock,
    InMemoryTradeHistoryRepository,
)


def _checkpoint(*, strategy_id=BUILTIN_LINE_STRATEGY_ID, state=None, slots=None, pending=()):
    return PositionStateCheckpoint(
        account_hash=account_identity_hash("id"),
        pair="USD_JPY",
        slots=tuple(slots or (None,) * 15),
        pending_mutations=pending,
        strategy_id=strategy_id,
        strategy_state={} if state is None else state,
    )


def _service(repository, broker, *, strategy_id=BUILTIN_LINE_STRATEGY_ID):
    position_service = PositionService(
        broker,
        broker,
        FakeNotifier(),
        InMemoryTradeHistoryRepository(),
        FixedClock(datetime(2026, 1, 2)),
    )
    return PositionPortfolioService(
        "USD_JPY",
        position_service,
        broker,
        broker,
        state_repository=repository,
        account_hash=account_identity_hash("id"),
        strategy_id=strategy_id,
    )


class _Repository:
    def __init__(self, result):
        self.result = result
        self.saved = []

    def load(self, **_kwargs):
        return self.result

    def save(self, checkpoint):
        self.saved.append(checkpoint)


@pytest.mark.contract
def test_json_checkpoint_v2_round_trip_preserves_nested_strategy_state(tmp_path):
    repository = JsonPositionStateRepository(tmp_path / "state.json")
    expected = _checkpoint(
        strategy_id="strategy-plugin",
        state={"last_candle": ["2026-01-02T00:01:00Z", {"close": 150.1}]},
    )

    repository.save(expected)
    loaded = repository.load(
        expected_account_hash=expected.account_hash,
        expected_pair=expected.pair,
    )

    assert loaded.status is CheckpointLoadStatus.LOADED
    assert loaded.checkpoint == expected
    raw = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert raw["version"] == 2
    assert raw["strategy_id"] == "strategy-plugin"
    assert raw["strategy_state"] == expected.strategy_state


@pytest.mark.contract
def test_checkpoint_rejects_recursive_non_json_strategy_state():
    with pytest.raises(ValueError, match="strategy_state"):
        _checkpoint(state={"nested": {"unsupported": object()}})


@pytest.mark.contract
def test_repository_decodes_v1_as_builtin_then_saves_v2(tmp_path):
    path = tmp_path / "state.json"
    repository = JsonPositionStateRepository(path)
    checkpoint = _checkpoint()
    repository.save(checkpoint)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["version"] = 1
    raw.pop("strategy_id")
    raw.pop("strategy_state")
    path.write_text(json.dumps(raw), encoding="utf-8")

    loaded = repository.load(
        expected_account_hash=checkpoint.account_hash,
        expected_pair=checkpoint.pair,
    )

    assert loaded.status is CheckpointLoadStatus.LOADED
    assert loaded.checkpoint is not None
    assert loaded.checkpoint.strategy_id == BUILTIN_LINE_STRATEGY_ID
    assert loaded.checkpoint.strategy_state == {}
    repository.save(loaded.checkpoint)
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 2


@pytest.mark.contract
def test_v1_rejects_v2_strategy_fields_as_unknown(tmp_path):
    path = tmp_path / "state.json"
    repository = JsonPositionStateRepository(path)
    checkpoint = _checkpoint()
    repository.save(checkpoint)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["version"] = 1
    path.write_text(json.dumps(raw), encoding="utf-8")

    loaded = repository.load(
        expected_account_hash=checkpoint.account_hash,
        expected_pair=checkpoint.pair,
    )

    assert loaded.status is CheckpointLoadStatus.QUARANTINED


@pytest.mark.contract
def test_future_checkpoint_schema_fails_closed_even_with_usable_backup(tmp_path):
    path = tmp_path / "state.json"
    repository = JsonPositionStateRepository(path)
    checkpoint = _checkpoint()
    repository.save(checkpoint)
    repository.save(checkpoint)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["version"] = 3
    path.write_text(json.dumps(raw), encoding="utf-8")

    loaded = repository.load(
        expected_account_hash=checkpoint.account_hash,
        expected_pair=checkpoint.pair,
    )

    assert loaded.status is CheckpointLoadStatus.SCHEMA_MISMATCH


@pytest.mark.contract
@pytest.mark.parametrize("version", [True, 1.0, 2.0])
def test_non_integer_checkpoint_schema_versions_fail_closed(tmp_path, version):
    path = tmp_path / "state.json"
    repository = JsonPositionStateRepository(path)
    checkpoint = _checkpoint()
    repository.save(checkpoint)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["version"] = version
    path.write_text(json.dumps(raw), encoding="utf-8")

    loaded = repository.load(
        expected_account_hash=checkpoint.account_hash,
        expected_pair=checkpoint.pair,
    )

    assert loaded.status is CheckpointLoadStatus.SCHEMA_MISMATCH


@pytest.mark.contract
def test_empty_checkpoint_adopts_selected_strategy_and_persists(tmp_path):
    checkpoint = _checkpoint()
    repository = _Repository(
        CheckpointLoadResult(CheckpointLoadStatus.LOADED, checkpoint)
    )
    service = _service(repository, FakeBroker(), strategy_id="strategy-plugin")

    result = service.restore_and_reconcile()

    assert result.state is PortfolioStartupState.READY
    assert service.strategy_id == "strategy-plugin"
    assert service.strategy_state == {}
    assert repository.saved[-1].strategy_id == "strategy-plugin"
    assert repository.saved[-1].strategy_state == {}


@pytest.mark.contract
def test_active_checkpoint_identity_mismatch_quarantines_without_adoption_or_save():
    checkpoint = _checkpoint(strategy_id=BUILTIN_LINE_STRATEGY_ID)
    checkpoint = PositionStateCheckpoint(
        account_hash=checkpoint.account_hash,
        pair=checkpoint.pair,
        slots=(None,) * 14 + (ManagedPosition.registered("active", "USD_JPY"),),
        strategy_id=checkpoint.strategy_id,
    )
    repository = _Repository(
        CheckpointLoadResult(CheckpointLoadStatus.LOADED, checkpoint)
    )
    service = _service(repository, FakeBroker(), strategy_id="strategy-plugin")

    result = service.restore_and_reconcile()

    assert result.state is PortfolioStartupState.QUARANTINED
    assert result.reason == "checkpoint strategy does not match selected strategy"
    assert repository.saved == []
    assert service.slots == [None] * 15
    assert service.strategy_id == "strategy-plugin"


@pytest.mark.contract
def test_pending_mutation_identity_mismatch_quarantines_without_save():
    checkpoint = _checkpoint(
        pending=(PendingBrokerMutation("submit_order", "pending"),),
    )
    repository = _Repository(
        CheckpointLoadResult(CheckpointLoadStatus.LOADED, checkpoint)
    )
    service = _service(repository, FakeBroker(), strategy_id="strategy-plugin")

    result = service.restore_and_reconcile()

    assert result.state is PortfolioStartupState.QUARANTINED
    assert repository.saved == []


@pytest.mark.contract
def test_broker_state_identity_mismatch_quarantines_without_save():
    broker = FakeBroker()
    broker.orders["external-order"] = PositionSnapshot(
        "external",
        "USD_JPY",
        OrderState.PENDING,
        TradeState.NONE,
        order_id="external-order",
        life=True,
    )
    repository = _Repository(
        CheckpointLoadResult(CheckpointLoadStatus.LOADED, _checkpoint())
    )
    service = _service(repository, broker, strategy_id="strategy-plugin")

    result = service.restore_and_reconcile()

    assert result.state is PortfolioStartupState.QUARANTINED
    assert repository.saved == []


@pytest.mark.contract
def test_v1_active_checkpoint_identity_mismatch_quarantines():
    active = ManagedPosition.registered("active", "USD_JPY")
    checkpoint = _checkpoint(slots=(active,) + (None,) * 14)
    repository = _Repository(
        CheckpointLoadResult(CheckpointLoadStatus.LOADED, checkpoint)
    )
    service = _service(repository, FakeBroker(), strategy_id="strategy-plugin")

    result = service.restore_and_reconcile()

    assert result.state is PortfolioStartupState.QUARANTINED
    assert repository.saved == []


@pytest.mark.contract
def test_same_checkpoint_identity_restores_strategy_state():
    checkpoint = _checkpoint(
        strategy_id="strategy-plugin",
        state={"counter": 4, "nested": [True, None]},
    )
    repository = _Repository(
        CheckpointLoadResult(CheckpointLoadStatus.LOADED, checkpoint)
    )
    service = _service(repository, FakeBroker(), strategy_id="strategy-plugin")

    service.restore_and_reconcile()

    assert service.strategy_state == checkpoint.strategy_state


@pytest.mark.contract
def test_strategy_state_setter_copies_nested_values():
    service = _service(None, FakeBroker(), strategy_id="strategy-plugin")
    state = {"nested": {"values": [1]}}

    service.set_strategy_checkpoint_state(state, persist=False)
    state["nested"]["values"].append(2)
    exposed = service.strategy_state
    exposed["nested"]["values"].append(3)

    assert service.strategy_state == {"nested": {"values": [1]}}


@pytest.mark.contract
def test_default_line_checkpoint_identity_is_stable_without_strategy_arguments():
    service = _service(None, FakeBroker())

    checkpoint = service._checkpoint()

    assert checkpoint.strategy_id == BUILTIN_LINE_STRATEGY_ID
    assert checkpoint.strategy_state == {}
