import pytest

import fGeneric as generic


@pytest.mark.unit
@pytest.mark.parametrize(
    ("name", "pip_value", "round_keta"),
    [
        ("USD_JPY", 0.01, 3),
        ("EUR_USD", 0.0001, 5),
        ("AUD_USD", 0.0001, 5),
    ],
)
def test_currency_pair_contract(name, pip_value, round_keta):
    pair = generic.currency_pair(name)

    assert pair.pip_value == pip_value
    assert pair.round_keta == round_keta
    assert pair.price_to_pips(pair.pips_to_price(10)) == 10


@pytest.mark.unit
def test_calculate_units_preserves_small_order_rounding_contract():
    pair = generic.currency_pair("USD_JPY")

    units = generic.calculate_units(pair, lc_range=0.1, risk_yen=500)

    assert units == 501
    assert units % 5 == 1


@pytest.mark.unit
def test_unsupported_pair_is_rejected():
    with pytest.raises(ValueError, match="Unsupported currency pair"):
        generic.currency_pair("GBP_USD")
