from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import classPositionControl
from ogami_oanda.adapters.legacy.order_dict import order_plan_to_legacy_dict
from ogami_oanda.application.services.closure_reporting_service import (
    LEGACY_HISTORY_COLUMNS,
)
from ogami_oanda.application.services.order_planner import OrderPlanner
from ogami_oanda.application.services.position_portfolio_service import PositionPortfolioService
from ogami_oanda.application.services.position_service import PositionService
from ogami_oanda.domain.orders.models import Direction, OrderContext, OrderIntent, OrderType
from ogami_oanda.domain.positions.models import OrderState, PositionSnapshot, TradeState
from tests.fakes import FakeBroker, FakeNotifier, FixedClock, InMemoryTradeHistoryRepository


def _portfolio():
    clock = FixedClock(datetime(2026, 1, 2, 10, 0, 0))
    broker = FakeBroker()
    service = PositionService(
        broker,
        broker,
        FakeNotifier(),
        InMemoryTradeHistoryRepository(),
        clock,
    )
    return PositionPortfolioService("USD_JPY", service, broker, broker), broker


def _plan(
    name="facade",
    *,
    submit_type=OrderType.LIMIT,
    target=150.0,
    current_price=150.1,
):
    intent = OrderIntent(
        "USD_JPY",
        Direction.BUY,
        submit_type,
        target,
        True,
        10,
        False,
        10,
        False,
        1000,
        name,
        1,
        0,
    )
    return OrderPlanner().plan(
        intent,
        OrderContext(current_price, "2026/01/02 10:00:00"),
    )


def _legacy_order(plan, *, order_permission=True):
    legacy_plan = order_plan_to_legacy_dict(plan)
    legacy_plan["order_permission"] = order_permission
    return SimpleNamespace(
        name=plan.intent.name,
        current_price=plan.context.current_price,
        exe_order_plan=legacy_plan,
        linkage_order_classes=[],
    )


@pytest.mark.contract
def test_root_position_control_projects_src_portfolio_as_legacy_slot_views():
    portfolio, broker = _portfolio()
    portfolio.register_plans([_plan()], submit=False)

    controller = classPositionControl.position_control(False, "USD_JPY", portfolio_service=portfolio)

    assert len(controller.position_classes) == 15
    assert controller.position_classes[0].name == "facade"
    assert controller.position_classes[0].o_state == "Watching"
    assert controller.position_check()["watching_list"][0]["name"] == "facade"
    assert broker.requests == []
    assert broker.commands == []


@pytest.mark.contract
def test_root_position_control_default_constructor_uses_src_portfolio_not_legacy_oanda(monkeypatch):
    monkeypatch.setattr(
        classPositionControl.classOanda,
        "Oanda",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy Oanda must not be constructed")),
    )

    controller = classPositionControl.position_control(False, "USD_JPY")

    assert controller.portfolio_service is not None
    assert len(controller.position_classes) == 15
    assert all(type(slot).__name__ == "managed_position_view" for slot in controller.position_classes)
    execution = controller.portfolio_service.broker_execution
    query = controller.portfolio_service.broker_query
    assert execution.client is query.client
    assert controller.portfolio_service.position_service.broker_execution is execution
    assert controller.portfolio_service.position_service.broker_query is query


@pytest.mark.contract
def test_root_position_control_order_add_delegates_and_reprojects_slots():
    portfolio, broker = _portfolio()
    portfolio.register_plans = Mock(wraps=portfolio.register_plans)
    controller = classPositionControl.position_control(
        False,
        "USD_JPY",
        portfolio_service=portfolio,
    )
    legacy_order = SimpleNamespace(exe_order_plan=order_plan_to_legacy_dict(_plan("delegated")))

    result = controller.order_class_add([legacy_order])

    assert result == "delegated\n"
    portfolio.register_plans.assert_called_once()
    plans, = portfolio.register_plans.call_args.args
    assert [plan.intent.name for plan in plans] == ["delegated"]
    assert portfolio.register_plans.call_args.kwargs == {"submit": True}
    assert controller.position_classes[0].name == "delegated"
    assert controller.position_classes[0].o_state == "PENDING"
    assert len(broker.requests) == 1


@pytest.mark.contract
def test_root_position_control_honors_each_legacy_order_permission():
    portfolio, broker = _portfolio()
    controller = classPositionControl.position_control(
        False,
        "USD_JPY",
        portfolio_service=portfolio,
    )
    watching = _legacy_order(
        _plan("watching-permission", target=150.0, current_price=150.0),
        order_permission=False,
    )
    submitted = _legacy_order(
        _plan("submitted-permission", target=150.1, current_price=150.0),
        order_permission=True,
    )

    result = controller.order_class_add([watching, submitted])

    assert result == "watching-permission\nsubmitted-permission\n"
    positions = {
        slot.snapshot.name: slot
        for slot in portfolio.slots
        if slot is not None
    }
    assert positions["watching-permission"].snapshot.order_state is OrderState.WATCHING
    assert positions["watching-permission"].snapshot.waiting_order is True
    assert positions["submitted-permission"].snapshot.order_state is OrderState.PENDING
    assert positions["submitted-permission"].snapshot.waiting_order is False
    assert len(broker.requests) == 1
    views = {view.name: view for view in controller.position_classes if view.life}
    assert views["watching-permission"].o_state == "Watching"
    assert views["submitted-permission"].o_state == "PENDING"


@pytest.mark.contract
def test_root_position_control_preserves_legacy_object_linkage_with_stable_id():
    def register(ordering):
        portfolio, _ = _portfolio()
        controller = classPositionControl.position_control(
            False,
            "USD_JPY",
            portfolio_service=portfolio,
        )
        left = _legacy_order(
            _plan("linked-left", target=149.9, current_price=150.0),
        )
        right = _legacy_order(
            _plan("linked-right", target=150.1, current_price=150.0),
        )
        left.linkage_order_classes.append(right)
        by_name = {"linked-left": left, "linked-right": right}

        controller.order_class_add([by_name[name] for name in ordering])

        positions = {
            slot.snapshot.name: slot
            for slot in portfolio.slots
            if slot is not None
        }
        views = {
            view.name: view
            for view in controller.position_classes
            if view.life
        }
        return positions, views

    positions, views = register(("linked-left", "linked-right"))
    reversed_positions, _ = register(("linked-right", "linked-left"))

    linkage_id = positions["linked-left"].runtime.linkage_id
    assert linkage_id is not None
    assert linkage_id == positions["linked-right"].runtime.linkage_id
    assert linkage_id == reversed_positions["linked-left"].runtime.linkage_id
    assert linkage_id == reversed_positions["linked-right"].runtime.linkage_id
    assert positions["linked-left"].runtime.order_plan.intent.metadata[
        "linkage_order_names"
    ] == ("linked-right",)
    assert positions["linked-right"].runtime.order_plan.intent.metadata[
        "linkage_order_names"
    ] == ("linked-left",)
    assert views["linked-left"].plan_json["linkage_id"] == linkage_id
    assert views["linked-left"].plan_json["linkage_order_names"] == (
        "linked-right",
    )
    assert [view.name for view in views["linked-left"].linkage_class_slots] == [
        "linked-right",
    ]
    assert [view.name for view in views["linked-right"].linkage_order_classes] == [
        "linked-left",
    ]


@pytest.mark.contract
def test_root_position_control_preserves_explicit_legacy_linkage_id():
    portfolio, _ = _portfolio()
    controller = classPositionControl.position_control(
        False,
        "USD_JPY",
        portfolio_service=portfolio,
    )
    left = _legacy_order(_plan("explicit-left", target=149.9))
    right = _legacy_order(_plan("explicit-right", target=150.1))
    left.exe_order_plan["linkage_id"] = "legacy-pair-42"
    right.exe_order_plan["linkage_id"] = "legacy-pair-42"

    controller.order_class_add([left, right])

    positions = {
        slot.snapshot.name: slot
        for slot in portfolio.slots
        if slot is not None
    }
    assert positions["explicit-left"].runtime.linkage_id == "legacy-pair-42"
    assert positions["explicit-right"].runtime.linkage_id == "legacy-pair-42"
    assert positions["explicit-left"].runtime.order_plan.intent.metadata[
        "linkage_order_names"
    ] == ("explicit-right",)
    assert positions["explicit-right"].runtime.order_plan.intent.metadata[
        "linkage_order_names"
    ] == ("explicit-left",)


@pytest.mark.contract
def test_root_position_control_order_add_preserves_decision_price_for_dedup_order():
    portfolio, _ = _portfolio()
    controller = classPositionControl.position_control(
        False,
        "USD_JPY",
        portfolio_service=portfolio,
    )
    farther = SimpleNamespace(
        current_price=150.0,
        exe_order_plan=order_plan_to_legacy_dict(
            _plan("farther", target=150.03, current_price=150.0),
        ),
    )
    nearer = SimpleNamespace(
        current_price=150.0,
        exe_order_plan=order_plan_to_legacy_dict(
            _plan("nearer", target=150.01, current_price=150.0),
        ),
    )

    result = controller.order_class_add([farther, nearer])

    assert result == "nearer\n"
    assert controller.position_classes[0].name == "nearer"


@pytest.mark.contract
def test_root_position_control_updates_delegate_and_publish_legacy_class_state():
    portfolio, broker = _portfolio()
    portfolio.register_plans([_plan("pending")], submit=True)
    broker.orders["order-1"] = PositionSnapshot(
        "pending",
        "USD_JPY",
        OrderState.FILLED,
        TradeState.OPEN,
        order_id="order-1",
        trade_id="trade-1",
        life=True,
        units=1000,
    )
    portfolio.sync_all = Mock(wraps=portfolio.sync_all)
    controller = classPositionControl.position_control(
        False,
        "USD_JPY",
        portfolio_service=portfolio,
    )

    assert controller.all_update_information_at_out_time(object()) is None
    result = controller.all_update_information(object())

    assert portfolio.sync_all.call_count == 2
    assert all(
        call.kwargs == {"current_price": None, "dry_run": False}
        for call in portfolio.sync_all.call_args_list
    )
    assert result["position_exist"] is True
    assert result["open_positions"][0]["name"] == "pending"
    assert classPositionControl.classPosition.order_information.positions_information is result
    assert (
        classPositionControl.classPosition.managed_position_view.positions_information
        is result
    )


@pytest.mark.contract
def test_root_position_control_passes_candle_price_to_watching_policy():
    portfolio, broker = _portfolio()
    portfolio.register_plans(
        [_plan("watching", submit_type=OrderType.STOP, current_price=149.9)],
        submit=False,
    )
    controller = classPositionControl.position_control(
        False,
        "USD_JPY",
        portfolio_service=portfolio,
    )
    candle = SimpleNamespace(current_price=150.01)

    controller.all_update_information(candle)
    assert controller.position_classes[0].step1_filled is True

    portfolio.position_service.clock.value = datetime(2026, 1, 2, 10, 0, 31)
    controller.all_update_information(candle)

    assert controller.position_classes[0].o_state == "PENDING"
    assert len(broker.requests) == 1


@pytest.mark.contract
def test_root_position_control_projects_broker_metrics_and_records_close_view():
    portfolio, broker = _portfolio()
    portfolio.register_plans(
        [_plan("metrics", target=150.0, current_price=149.9)],
        submit=True,
    )
    broker.orders["order-1"] = PositionSnapshot(
        "metrics",
        "USD_JPY",
        OrderState.FILLED,
        TradeState.OPEN,
        order_id="order-1",
        trade_id="trade-1",
        life=True,
        direction=1,
        target_price=150.0,
        units=1000,
        unrealized_pl=120,
        elapsed_seconds=240,
    )
    controller = classPositionControl.position_control(
        False,
        "USD_JPY",
        portfolio_service=portfolio,
    )

    opened = controller.all_update_information(
        SimpleNamespace(current_price=150.12),
    )

    assert opened["max_position_time_sec"] == 240
    assert opened["total_pl"] == 120
    assert opened["open_positions"][0]["pl"] == 12
    assert len(controller.result_class_arr) == 0

    broker.trades["trade-1"] = PositionSnapshot(
        "metrics",
        "USD_JPY",
        OrderState.FILLED,
        TradeState.CLOSED,
        order_id="order-1",
        trade_id="trade-1",
        life=False,
        direction=1,
        target_price=150.0,
        units=1000,
        realized_pl=200,
        elapsed_seconds=600,
        average_close_price=150.2,
    )

    closed = controller.all_update_information(
        SimpleNamespace(current_price=150.2),
    )

    assert closed["position_exist"] is False
    assert len(controller.result_class_arr) == 1
    closed_view = controller.result_class_arr[0]
    assert closed_view.name == "metrics"
    assert closed_view.t_state == "CLOSED"
    assert closed_view.t_realize_pl == 200
    assert closed_view.t_pl_pips == 20
    assert closed_view.t_time_past_sec == 600
    assert closed_view.win_max_pips == 12
    assert closed_view.lose_max_pips == 0
    reporting = classPositionControl.classPosition.order_information
    assert reporting.total_yen == 200
    assert reporting.total_price_diff == 0.2
    assert reporting.total_pips == 20
    assert reporting.plus_yen_position_num == 1
    assert reporting.before_latest_name == "metrics"
    assert tuple(reporting.result_dic_arr[-1]) == LEGACY_HISTORY_COLUMNS
    assert reporting.result_dic_arr[-1]["max_plus"] == 12
    assert reporting.result_dic_arr[-1]["max_minus"] == 0
    assert reporting.latest_result_summary["res_sum"] == 200
    assert reporting.pivot_result_summary == (
        {
            "name_only": "me",
            "res_sum": 200,
            "positive_count": 1,
            "negative_count": 0,
        },
    )

    portfolio.register_plans(
        [_plan("replacement", target=149.8, current_price=149.9)],
        submit=False,
    )
    controller.position_check()

    assert controller.position_classes[0].name == "replacement"
    assert controller.position_classes[0].t_pl_pips == 0
    assert controller.position_classes[0].t_time_past_sec == 0


@pytest.mark.contract
def test_root_position_control_queries_reproject_src_state_before_reporting():
    portfolio, _ = _portfolio()
    portfolio.register_plans([_plan("source-state")], submit=False)
    controller = classPositionControl.position_control(
        False,
        "USD_JPY",
        portfolio_service=portfolio,
    )
    controller.position_classes[0].reset()

    life = controller.life_check()
    positions = controller.position_check()

    assert life == {"life_exist": True, "one_line_comment": ""}
    assert positions["watching_list"][0]["name"] == "source-state"
    assert controller.position_classes[0].o_state == "Watching"


@pytest.mark.contract
def test_root_position_control_catch_up_and_reset_delegate_with_legacy_returns():
    portfolio, broker = _portfolio()
    broker.positions["trade-1"] = PositionSnapshot(
        "restored",
        "USD_JPY",
        OrderState.FILLED,
        TradeState.OPEN,
        trade_id="trade-1",
        life=True,
        direction=-1,
        target_price=149.8,
        units=500,
    )
    broker.orders["pending-1"] = PositionSnapshot(
        "pending",
        "USD_JPY",
        OrderState.PENDING,
        TradeState.NONE,
        order_id="pending-1",
        life=True,
    )
    portfolio.restore_open_positions = Mock(wraps=portfolio.restore_open_positions)
    portfolio.cancel_pending_on_start = Mock(
        wraps=portfolio.cancel_pending_on_start,
    )
    portfolio.sync_all = Mock(wraps=portfolio.sync_all)
    controller = classPositionControl.position_control(
        False,
        "USD_JPY",
        portfolio_service=portfolio,
    )

    assert controller.catch_up_position_and_del_order() is None
    assert controller.position_classes[0].name == "restored"
    portfolio.restore_open_positions.assert_called_once_with()

    assert controller.reset_all_position() is None
    portfolio.cancel_pending_on_start.assert_called_once_with(True)
    portfolio.sync_all.assert_called_once_with(dry_run=False)
    assert ("cancel_order", ("pending-1",)) in broker.commands


@pytest.mark.contract
def test_root_position_control_catch_up_keeps_zero_return_when_nothing_exists():
    portfolio, _ = _portfolio()
    controller = classPositionControl.position_control(
        False,
        "USD_JPY",
        portfolio_service=portfolio,
    )

    assert controller.catch_up_position_and_del_order() == 0
