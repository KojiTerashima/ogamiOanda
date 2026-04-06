"""Unit tests for PositionCoreMixin."""

from unittest.mock import MagicMock

from position_core import PositionCoreMixin


class _FakeNotifier:
    def __init__(self):
        self.calls = []

    def notify(self, *args):
        self.calls.append(args)


class _ConcretePosition(PositionCoreMixin):
    """Minimal concrete class that satisfies all attribute requirements used by the mixin."""

    def __init__(self, is_live=False):
        self.is_live = is_live
        self._notifier = _FakeNotifier()
        self.name = "TEST_POS"
        self.life = True
        self.order_permission = True
        self.plan_json = {}
        self.o_id = 0
        self.o_time = None
        self.o_state = "NONE"
        self.o_time_past_sec = 0
        self.t_id = 0
        self.t_execution_price = 0.0
        self.t_type = "LONG"
        self.t_initial_units = 0
        self.t_current_units = 0
        self.t_time = None
        self.t_time_past_sec = 0
        self.t_state = "OPEN"
        self.t_realize_pl = 0.0
        self.t_close_time = None
        self.t_close_price = 0.0
        self.t_unrealize_pl = 0.0
        self.t_pl_u = 0.0
        self.try_update_num = 0
        self.win_lose_border_range = 0.05
        self.win_hold_time_sec = 0
        self.lose_hold_time_sec = 0
        self.lose_max_plu = 0.0
        self.win_max_plu = 0.0
        # select_oa stubs
        self.oa = None
        self.oa_mode = 0
        self.oanda_factory = MagicMock(return_value=MagicMock())
        self.account_config = MagicMock()


# ---------------------------------------------------------------------------
# life_set
# ---------------------------------------------------------------------------


def test_life_set_true():
    pos = _ConcretePosition()
    pos.life_set(True)
    assert pos.life is True


def test_life_set_false(capsys):
    pos = _ConcretePosition()
    pos.life_set(False)
    assert pos.life is False
    captured = capsys.readouterr()
    assert "LIFE 終了" in captured.out


# ---------------------------------------------------------------------------
# count_up_position_check
# ---------------------------------------------------------------------------


def test_count_up_when_alive():
    pos = _ConcretePosition()
    pos.count_up_position_check()
    pos.count_up_position_check()
    assert pos.try_update_num == 2


def test_count_up_when_dead():
    pos = _ConcretePosition()
    pos.life = False
    pos.count_up_position_check()
    assert pos.try_update_num == 0


# ---------------------------------------------------------------------------
# send_line — practice mode
# ---------------------------------------------------------------------------


def test_send_line_practice_normal():
    pos = _ConcretePosition(is_live=False)
    pos.send_line("■■■通常:", "some message")
    assert len(pos._notifier.calls) == 1
    first_arg = pos._notifier.calls[0][0]
    assert "☆☆練習環境:" == first_arg


def test_send_line_practice_close():
    pos = _ConcretePosition(is_live=False)
    pos.send_line("■■■解消:", "close message")
    assert pos._notifier.calls[0][1] == "□□□解消:"


def test_send_line_practice_order_close():
    pos = _ConcretePosition(is_live=False)
    pos.send_line("■■■オーダー解消", "msg")
    assert pos._notifier.calls[0][1] == "□□□解消:"


def test_send_line_live():
    pos = _ConcretePosition(is_live=True)
    pos.send_line("■■■解消:", "live msg")
    # Live mode must forward args as-is (no prefix)
    assert pos._notifier.calls[0] == ("■■■解消:", "live msg")


# ---------------------------------------------------------------------------
# updateWinLoseTime
# ---------------------------------------------------------------------------


def test_update_win_lose_winning_streak():
    pos = _ConcretePosition()
    pos.t_pl_u = 0.1  # previous pl positive
    pos.updateWinLoseTime(0.15)  # still winning
    assert pos.win_hold_time_sec == 2
    assert pos.lose_hold_time_sec == 0


def test_update_win_lose_start_win():
    pos = _ConcretePosition()
    pos.t_pl_u = -0.05  # previously losing
    pos.updateWinLoseTime(0.1)  # now winning
    assert pos.win_hold_time_sec == 0  # reset to 0 (start point)
    assert pos.lose_hold_time_sec == 0


def test_update_win_lose_losing_streak():
    pos = _ConcretePosition()
    pos.t_pl_u = -0.05  # previously losing
    pos.updateWinLoseTime(-0.1)  # still losing
    assert pos.lose_hold_time_sec == 2
    assert pos.win_hold_time_sec == 0


def test_update_win_lose_max_tracking():
    pos = _ConcretePosition()
    pos.t_pl_u = -0.20
    pos.lose_max_plu = 0.0
    pos.updateWinLoseTime(-0.25)
    assert pos.lose_max_plu == -0.20  # updated to min

    pos.t_pl_u = 0.30
    pos.win_max_plu = 0.0
    pos.updateWinLoseTime(0.35)
    assert pos.win_max_plu == 0.30


# ---------------------------------------------------------------------------
# select_oa
# ---------------------------------------------------------------------------


def test_select_oa_practice():
    pos = _ConcretePosition(is_live=False)
    pos.select_oa(1)
    pos.oanda_factory.assert_called_once_with(
        pos.account_config.practice_account_id,
        pos.account_config.practice_access_token,
        pos.account_config.practice_environment,
    )


def test_select_oa_live_mode1():
    pos = _ConcretePosition(is_live=True)
    pos.select_oa(1)
    pos.oanda_factory.assert_called_once_with(
        pos.account_config.live_account_id,
        pos.account_config.live_access_token,
        pos.account_config.live_environment,
    )


def test_select_oa_live_mode2():
    pos = _ConcretePosition(is_live=True)
    pos.select_oa(2)
    pos.oanda_factory.assert_called_once_with(
        pos.account_config.live_sub_account_id,
        pos.account_config.live_access_token,
        pos.account_config.live_environment,
    )
