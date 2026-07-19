from datetime import datetime

import pytest

import classPositionControl
from ogami_oanda.application.services.order_planner import OrderPlanner
from ogami_oanda.application.services.position_portfolio_service import PositionPortfolioService
from ogami_oanda.application.services.position_service import PositionService
from ogami_oanda.domain.orders.models import Direction, OrderContext, OrderIntent, OrderType
from tests.fakes import FakeBroker, FakeNotifier, FixedClock, InMemoryTradeHistoryRepository


@pytest.mark.contract
def test_root_position_control_projects_src_portfolio_as_legacy_slot_views():
    clock = FixedClock(datetime(2026, 1, 2, 10, 0, 0))
    broker = FakeBroker()
    service = PositionService(broker, broker, FakeNotifier(), InMemoryTradeHistoryRepository(), clock)
    portfolio = PositionPortfolioService("USD_JPY", service, broker, broker)
    intent = OrderIntent("USD_JPY", Direction.BUY, OrderType.LIMIT, 150.0, True, 10, False, 10, False, 1000, "facade", 1, 0)
    plan = OrderPlanner().plan(intent, OrderContext(150.1, "2026/01/02 10:00:00"))
    portfolio.register_plans([plan], submit=False)

    controller = classPositionControl.position_control(False, "USD_JPY", portfolio_service=portfolio)

    assert len(controller.position_classes) == 15
    assert controller.position_classes[0].name == "facade"
    assert controller.position_classes[0].o_state == "Watching"
    assert controller.position_check()["watching_list"][0]["name"] == "facade"
    assert broker.requests == []
    assert broker.commands == []
