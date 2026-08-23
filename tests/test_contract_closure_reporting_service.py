import csv
from datetime import datetime
from math import isinf

import pytest

from ogami_oanda.adapters.repositories.csv_trade_history import (
    CsvTradeHistoryRepository,
)
from ogami_oanda.application.services.closure_reporting_service import (
    LEGACY_HISTORY_COLUMNS,
    ClosureReportingService,
    PortfolioAnalytics,
)
from ogami_oanda.application.services.order_planner import OrderPlanner
from ogami_oanda.domain.orders.models import (
    Direction,
    OrderContext,
    OrderIntent,
    OrderType,
)
from ogami_oanda.domain.positions.managed_position import ManagedPosition
from ogami_oanda.domain.positions.models import (
    OrderState,
    PositionEvent,
    PositionSnapshot,
    TradeState,
)
from tests.fakes import FakeNotifier


@pytest.mark.contract
def test_closure_reporting_preserves_legacy_columns_totals_and_deduplication(
    tmp_path,
):
    plan = OrderPlanner().plan(
        OrderIntent(
            "USD_JPY",
            Direction.BUY,
            OrderType.LIMIT,
            150.0,
            True,
            0.2,
            False,
            0.1,
            False,
            1000,
            "close-test-12:00",
            1,
            30,
            lc_change=({"trigger": 0.03, "ensure": 0.01},),
            metadata={
                "name_ymdhms": "close-test_2026/01/02 12:00:00",
                "memo": "close memo",
                "current_price_gap": 0.02,
                "target_distance_pips": 3.5,
                "move_ave60": 0.15,
                "lc_price_original": 149.85,
                "tp_price_original": 150.3,
            },
        ),
        OrderContext(150.0, "2026/01/02 12:00:00", move_average=0.05),
    )
    position = ManagedPosition.registered(plan.intent.name, "USD_JPY").with_order_plan(
        plan,
        datetime(2026, 1, 2, 12, 0, 0),
    ).pending("order-1").filled(
        "trade-1",
        datetime(2026, 1, 2, 12, 0, 30),
    ).with_runtime(
        max_unrealized_pl=120,
        min_unrealized_pl=-40,
        applied_lc_change_index=0,
        current_stop_loss=149.95,
    )
    broker_snapshot = PositionSnapshot(
        plan.intent.name,
        "USD_JPY",
        OrderState.FILLED,
        TradeState.CLOSED,
        order_id="order-1",
        trade_id="trade-1",
        direction=1,
        target_price=150.0,
        units=1000,
        realized_pl=200,
        average_close_price=150.2,
        elapsed_seconds=600,
    )
    event = PositionEvent(
        "trade_closed:trade-1",
        "trade_closed",
        plan.intent.name,
        "USD_JPY",
        datetime(2026, 1, 2, 12, 10, 30),
        {"position": position, "broker_snapshot": broker_snapshot},
    )
    history = CsvTradeHistoryRepository(tmp_path / "history.csv")
    notifier = FakeNotifier()
    analytics = PortfolioAnalytics()
    service = ClosureReportingService(history, notifier, analytics)

    first = service.report(event)
    second = service.report(event)

    assert first is not None
    assert tuple(first) == LEGACY_HISTORY_COLUMNS
    assert first == {
        "name": "close-test-12:00",
        "pair": "USD_JPY",
        "res": "200",
        "pl_per_units": 20,
        "units": "1000.0",
        "max_plus": 12,
        "max_minus": -4,
        "order_time": datetime(2026, 1, 2, 12, 0, 0),
        "target_price": 150,
        "take_time": datetime(2026, 1, 2, 12, 0, 30),
        "take_price": "150.0",
        "end_time": datetime(2026, 1, 2, 12, 10, 30),
        "end_price": "150.2",
        "lc_price": 149.95,
        "lc_price_original_plan": 149.85,
        "lc_range": 10,
        "tp_price": 150.2,
        "tp_range": 20,
        "lc_change": ",(3.0p-1.0p)",
        "orderID": "order-1",
        "tradeID": "trade-1",
        "name_only": "close-test-",
        "plus_minus": 1,
        "position_keep_time": "600",
        "name_ymdhms": "close-test_2026/01/02 12:00:00",
        "tp_price_original_plan": 150.3,
        "move_ave5": 5,
        "move_ave60": 15,
        "memo": "close memo",
        "current_price_gap": 2,
        "rr": 2,
        "target_price_range": 3.5,
    }
    assert second is None
    with history.path.open(newline="", encoding="utf-8") as history_file:
        reader = csv.DictReader(history_file)
        history_rows = list(reader)
    assert tuple(reader.fieldnames or ()) == LEGACY_HISTORY_COLUMNS
    assert len(history_rows) == 1
    assert history_rows[0]["name"] == "close-test-12:00"
    assert history_rows[0]["max_plus"] == "12.0"
    assert history_rows[0]["max_minus"] == "-4.0"
    assert history_rows[0]["tradeID"] == "trade-1"
    assert analytics.total_yen == 200
    assert analytics.total_pips == 20
    assert analytics.total_yen_max == 200
    assert isinf(analytics.total_yen_min)
    assert analytics.total_price_diff == 0.2
    assert analytics.total_price_diff_max == 0.2
    assert isinf(analytics.total_price_diff_min)
    assert analytics.total_pips_min == 20
    assert analytics.plus_yen_position_num == 1
    assert analytics.minus_yen_position_num == 0
    assert analytics.lc_change_num == 1
    assert analytics.before_latest_name == "close-test-12:00"
    assert analytics.before_latest_price_diff == 0.2
    assert analytics.before_latest_pl_pips == 20
    assert analytics.before_latest_plu == 20
    assert analytics.history_plus_minus == [0, 20]
    assert analytics.history_names == ["0", "close-test-12:00"]
    assert analytics.result_dic_arr == [first]
    assert first["units"] == "1000.0"
    assert first["max_plus"] == 12
    assert first["max_minus"] == -4
    assert first["lc_change"] == ",(3.0p-1.0p)"
    assert first["current_price_gap"] == 2
    assert first["target_price_range"] == 3.5
    assert analytics.result_summary["total_pips"] == 20
    assert analytics.latest_summary() == {
        "rows": (first,),
        "res_sum": 200,
    }
    assert analytics.pivot_summary() == (
        {
            "name_only": "close-test-",
            "res_sum": 200,
            "positive_count": 1,
            "negative_count": 0,
        },
    )
    assert notifier.messages

    restarted_notifier = FakeNotifier()
    restarted = ClosureReportingService(history, restarted_notifier)

    assert restarted.report(event) is None
    assert restarted_notifier.messages == []
    assert restarted.analytics.total_yen == 200
    assert restarted.analytics.total_pips == 20
    with history.path.open(newline="", encoding="utf-8") as history_file:
        assert len(list(csv.DictReader(history_file))) == 1


@pytest.mark.contract
def test_portfolio_analytics_keeps_legacy_minima_latest_and_pivot_semantics():
    analytics = PortfolioAnalytics()
    winning = {
        "name": "pivot-a-12345",
        "name_only": "pivot-a-",
        "pair": "USD_JPY",
        "res": "200",
        "pl_per_units": 20,
    }
    losing = {
        "name": "pivot-b-12345",
        "name_only": "pivot-b-",
        "pair": "USD_JPY",
        "res": "-350",
        "pl_per_units": -35,
    }

    analytics.apply(winning, 0.2, lc_change_count=1)
    assert isinf(analytics.total_yen_min)
    assert isinf(analytics.total_price_diff_min)

    analytics.apply(losing, -0.35)

    assert analytics.result_summary == {
        "total_yen": -150,
        "total_yen_max": 200,
        "total_yen_min": -150,
        "total_price_diff": -0.15,
        "total_price_diff_max": 0.2,
        "total_price_diff_min": -0.15,
        "total_pips": -15,
        "total_pips_max": 20,
        "total_pips_min": -15,
        "plus_yen_position_num": 1,
        "minus_yen_position_num": 1,
        "lc_change_num": 1,
    }
    assert analytics.before_latest_name == "pivot-b-12345"
    assert analytics.before_latest_plu == -35
    assert analytics.latest_summary()["res_sum"] == -150
    assert analytics.pivot_summary() == (
        {
            "name_only": "pivot-a-",
            "res_sum": 200,
            "positive_count": 1,
            "negative_count": 0,
        },
        {
            "name_only": "pivot-b-",
            "res_sum": -350,
            "positive_count": 0,
            "negative_count": 1,
        },
    )


@pytest.mark.contract
def test_root_reporting_view_projects_the_src_owned_analytics():
    import classPosition

    analytics = PortfolioAnalytics()
    record = {
        "name": "root-view-12345",
        "name_only": "root-view-",
        "pair": "USD_JPY",
        "res": "50",
        "pl_per_units": 5,
    }
    analytics.apply(record, 0.05, lc_change_count=1)

    classPosition.order_information.sync_reporting_view(analytics)

    view = classPosition.order_information
    assert view.total_yen == 50
    assert view.total_price_diff == 0.05
    assert view.before_latest_plu == 5
    assert view.lc_change_num == 1
    assert view.result_dic_arr == [record]
    assert view.latest_result_summary["res_sum"] == 50
    assert view.pivot_result_summary[0]["name_only"] == "root-view-"
