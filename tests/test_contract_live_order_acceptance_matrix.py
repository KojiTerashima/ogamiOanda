from __future__ import annotations

from datetime import datetime

import pytest

from ogami_oanda.adapters.oanda.mappers import broker_request_to_oanda
from ogami_oanda.application.services.market_analysis_service import (
    MarketAnalysisResult,
)
from ogami_oanda.application.services.order_planner import OrderPlanner
from ogami_oanda.application.services.position_portfolio_service import (
    PositionPortfolioService,
)
from ogami_oanda.application.services.position_service import PositionService
from ogami_oanda.domain.market.currency_pair import currency_pair
from ogami_oanda.domain.orders.models import (
    Direction,
    OrderContext,
    OrderIntent,
    OrderType,
)
from ogami_oanda.entrypoints.live import LiveApplication
from tests.fakes import (
    FakeBroker,
    FakeMarketData,
    FakeNotifier,
    FixedClock,
    InMemoryTradeHistoryRepository,
)


class _Analysis:
    def __init__(self, intents, context):
        self.intents = tuple(intents)
        self.context = context

    def analyze(self, pair, decision_time, *, current_price=None):
        del pair, decision_time, current_price
        return MarketAnalysisResult(
            self.intents,
            {},
            {},
            order_context=self.context,
        )


@pytest.mark.contract
@pytest.mark.parametrize(
    ("pair_name", "current_price"),
    [
        ("USD_JPY", 150.0),
        ("EUR_USD", 1.1),
        ("AUD_USD", 0.65),
    ],
)
def test_three_pair_three_order_type_live_pipeline_submits_wire_ready_requests(
    pair_name,
    current_price,
):
    pair = currency_pair(pair_name)
    context = OrderContext(
        current_price,
        "2026/01/02 10:00:00",
    )
    intents = []
    for index, order_type in enumerate(
        (OrderType.MARKET, OrderType.LIMIT, OrderType.STOP)
    ):
        target_price = pair.round_price(
            current_price
            + pair.pips_to_price(
                0 if order_type is OrderType.MARKET else 20 + index * 20
            )
        )
        intents.append(
            OrderIntent(
                pair_name,
                Direction.BUY,
                order_type,
                target_price,
                order_type is not OrderType.MARKET,
                pair.pips_to_price(100),
                False,
                pair.pips_to_price(100),
                False,
                10 + index,
                f"{pair_name}-{order_type.value}",
                index + 1,
                30,
                metadata={
                    "source": "acceptance",
                    "line_strategy": order_type.value,
                },
            )
        )

    broker = FakeBroker()
    clock = FixedClock(datetime(2026, 1, 2, 10, 0, 0))
    position_service = PositionService(
        broker,
        broker,
        FakeNotifier(),
        InMemoryTradeHistoryRepository(),
        clock,
    )
    application = LiveApplication(
        pair_name,
        FakeMarketData({}, {pair_name: current_price}),
        _Analysis(intents, context),
        OrderPlanner(),
        PositionPortfolioService(
            pair_name,
            position_service,
            broker,
            broker,
        ),
        clock,
    )

    result = application.run_once(dry_run=False)

    assert len(result.plans) == 3
    assert len(broker.requests) == 3
    assert result.registration.accepted == tuple(
        plan.intent.name for plan in result.plans
    )
    for request, order_type in zip(
        broker.requests,
        (OrderType.MARKET, OrderType.LIMIT, OrderType.STOP),
    ):
        wire = broker_request_to_oanda(request)["order"]
        assert request.instrument == pair_name
        assert request.units > 0
        assert request.client_reference.startswith("ogm-")
        assert wire["type"] == order_type.value
        assert wire["timeInForce"] == (
            "FOK" if order_type is OrderType.MARKET else "GTC"
        )
        assert ("price" in wire) is (order_type is not OrderType.MARKET)
        assert wire["takeProfitOnFill"]["price"]
        assert wire["stopLossOnFill"]["price"]
