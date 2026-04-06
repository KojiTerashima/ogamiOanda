import turn_bb_analysis as tbb
from turn_state import runtime_state


class _Row(dict):
    pass


class _ILoc:
    def __init__(self, row):
        self._row = row

    def __getitem__(self, index):
        if index != 0:
            raise IndexError(index)
        return self._row


class _Df:
    def __init__(self, row):
        self.iloc = _ILoc(row)


def test_runtime_state_defaults():
    assert runtime_state.line_send_enabled is False
    assert runtime_state.units_std == 1


def test_latest_price_position_from_row():
    row = _Row(bb_upper=110.0, bb_lower=100.0, close=109.0)
    assert tbb.latest_price_position_from_row(row) == 1


def test_latest_price_position_from_df():
    row = _Row(bb_upper=110.0, bb_lower=100.0, close=101.0)
    df = _Df(row)
    assert tbb.latest_price_position_from_df(df) == -1
