import datetime


class PositionCoreMixin:
    """Shared behaviour extracted from classPosition and classPositionForTest.

    Both production and test position classes inherit from this mixin to avoid
    duplicate method bodies.  All methods here rely only on instance attributes
    that both concrete classes initialise in their own __init__ blocks.
    """

    def select_oa(self, oa_mode):
        self.oa_mode = oa_mode
        if self.is_live:
            if self.oa_mode == 1:
                # 通常アカウント
                self.oa = self.oanda_factory(
                    self.account_config.live_account_id,
                    self.account_config.live_access_token,
                    self.account_config.live_environment,
                )
            else:
                # 両建て用アカウント
                self.oa = self.oanda_factory(
                    self.account_config.live_sub_account_id,
                    self.account_config.live_access_token,
                    self.account_config.live_environment,
                )
        else:
            # デモ口座
            self.oa = self.oanda_factory(
                self.account_config.practice_account_id,
                self.account_config.practice_access_token,
                self.account_config.practice_environment,
            )

    def print_info(self):
        print("   <表示>", self.name, datetime.datetime.now().replace(microsecond=0))
        print("　 【life】", self.life)
        print("   【name】", self.name)
        print("   【order_permission】", self.order_permission)
        print("   【plan】", self.plan_json)
        print(
            "   【order1】", self.o_id, self.o_time, self.o_state, self.o_time_past_sec
        )
        print(
            "   【trade1】",
            self.t_id,
            self.t_execution_price,
            self.t_type,
            self.t_initial_units,
            self.t_current_units,
        )
        print("   【trade1】", self.t_time, self.t_time_past_sec)
        print(
            "   【trade2】",
            self.t_state,
            self.t_realize_pl,
            self.t_close_time,
            self.t_close_price,
        )

    def print_info_short(self):
        print("   <表示>", self.name, datetime.datetime.now().replace(microsecond=0))
        print("　 【life】", self.life)
        print("   【name】", self.name)
        print(
            "   【order1】", self.o_id, self.o_time, self.o_state, self.o_time_past_sec
        )
        print(
            "   【trade1】",
            self.t_id,
            self.t_initial_units,
            self.t_current_units,
            self.t_execution_price,
        )
        print("   【trade1】", self.t_unrealize_pl, self.t_pl_u, self.t_time_past_sec)

    def life_set(self, boo):
        self.life = boo
        if not boo:
            # Life終了時（＝能動オーダークローズ、能動ポジションクローズ、市場で発生した成り行きのポジションクローズで発動）
            print(" LIFE 終了", self.name)

    def count_up_position_check(self):
        """外部から呼ばれ、謎な状態が続く場合のトライ回数をカウントアップする。"""
        if self.life:
            self.try_update_num = self.try_update_num + 1

    def send_line(self, *args):
        """本番 → 通知; 練習 → プレフィックスを付けて通知。"""
        if self.is_live:
            self._notifier.notify(*args)
        else:
            print(" 練習用送信関数")
            args = ("☆☆練習環境:",) + args
            if args[1] == "■■■解消:":
                args_list = list(args)
                args_list[1] = "□□□解消:"
                self._notifier.notify(*tuple(args_list))
            elif args[1] == "■■■オーダー解消":
                args_list = list(args)
                args_list[1] = "□□□解消:"
                self._notifier.notify(*tuple(args_list))
            else:
                self._notifier.notify(*args)

    def updateWinLoseTime(self, new_pl):
        """最新 PLu を受け取り、勝ち/負け継続時間と最大値を更新する。"""
        if new_pl >= self.win_lose_border_range:
            self.lose_hold_time_sec = 0
            if self.t_pl_u <= 0:
                self.win_hold_time_sec = 0
            else:
                self.win_hold_time_sec += 2
        else:
            self.win_hold_time_sec = 0
            if self.t_pl_u >= 0:
                self.lose_hold_time_sec = 0
            else:
                self.lose_hold_time_sec += 2

        if self.lose_max_plu > self.t_pl_u:
            self.lose_max_plu = self.t_pl_u
        if self.win_max_plu < self.t_pl_u:
            self.win_max_plu = self.t_pl_u
