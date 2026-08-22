import pytest

from ogami_oanda.domain.market.currency_pair import currency_pair
from ogami_oanda.strategy.position_sizing import PositionSizingPolicy


@pytest.mark.contract
def test_position_sizing_matches_legacy_risk_formula_and_strategy_multiplier():
    policy = PositionSizingPolicy(risk_yen=500)

    assert policy.units_for(currency_pair("EUR_USD"), stop_loss_pips=7.5, multiplier=0.25) == 166
    assert policy.units_for(currency_pair("USD_JPY"), stop_loss_pips=10, multiplier=1) == 500


@pytest.mark.contract
@pytest.mark.parametrize(
    ("risk_yen", "stop_loss_pips", "multiplier"),
    [(0, 10, 1), (500, 0, 1), (500, 10, 0)],
)
def test_position_sizing_rejects_non_positive_risk_inputs(risk_yen, stop_loss_pips, multiplier):
    with pytest.raises(ValueError):
        PositionSizingPolicy(risk_yen).units_for(
            currency_pair("USD_JPY"),
            stop_loss_pips,
            multiplier,
        )
