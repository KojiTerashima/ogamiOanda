import datetime  # 日付関係
import json

import numpy as np
import oandapyV20
import oandapyV20.endpoints.accounts as accounts
import oandapyV20.endpoints.instruments as instruments
import oandapyV20.endpoints.transactions as trans
import pandas as pd
from numpy import linalg as LA
from oandapyV20 import API
from oandapyV20.endpoints.positions import OpenPositions, PositionClose, PositionDetails

import classOandaSupport as oanda_support
from classOandaMarketData import OandaMarketDataService
from classOandaOrders import OandaOrdersService
from classOandaTrades import OandaTradesService
from config.notifier import Notifier, get_notifier


class Oanda:
    # ■クラス内の主な関数
    # (1)現在価格を取得する　NowPrice_exe
    # (2)キャンドルデータを取得(5000行以内)　InstrumentsCandles_exe
    # (3)キャンドルデータを取得(5000行以上 / 現在から)　InstrumentsCandles_multi_support_exe
    # (4)キャンドルデータを取得(サポート専用。通常利用無し）
    # (5)オーダーの発行を実施　OrderCreate_dic_exe
    # (6)指定のオーダーのキャンセル　OrderCancel_exe
    # (7)オーダーを全てキャンセル　OrderCancel_All_exe
    # (7-2)オーダーの全ての個数を取得 OrderCount_All_exe()
    # (8)指定のオーダーの内容詳細の取得　OrderDetails_exe
    # (9)指定のオーダーのステータス（オーダーとトレードの詳細）を取得　OrderDetailsState_exe
    # (10)オーダーの一覧（全て）を取得　OrdersPending_exe
    # (11)オーダーの一覧（新規トレード待ちのみ）を取得　OrdersWaitPending_exe
    # (12)トレードの一覧を取得　OpenTrades_exe
    # (13)指定のトレードの詳細を取得　TradeDetails_exe
    # (14)指定のトレードの変更　TradeCRCDO_exe
    # (15)指定のトレードの決済　TradeClose_exe
    # (16)トレードを全て決済　TradeAllClose_exe
    # (16-2)トレードの個数を取得する TradeAllcount_exe
    # (17)ポジションの一覧を取得　OpenPositions_exe [注]ポジションはトレードを通貨でひとまとめにしたもの。あんま使わん。
    # (18)指定のポジションの詳細　PositionDetails_exe
    # (19)指定のポジションの決済　PositionClose_exe
    # (20)口座残高の取得　GetBalance_exe
    # (21)トランザクション(取引履歴)の取得　GetActPrice_exe
    # (22)オーダーブックを取得する　OrderBook_exe
    #
    # ■サポート関数（クラス外。コード的には約700行目以降）
    # キャンドルデータに情報を付与する関数 (時系列降順のデータフレームに追加。おもに(2)~(4)で活用）
    #  add_basic_data：基本的情報列を付与（これに関係する関数l_func等も存在）
    #  add_macd：Macd情報列を付与
    #  add_ema_data：指数移動平均線の列を付与
    #  add_bb_data：ボリンジャーバンドの列を付与
    # その他、
    #  iso_to_jstdt_single / iso_to_jstdt：ISO時刻規格をJST時刻に変換（DateFrame用、個別用）
    #  str_to_time：文字列時刻（2023/5/24  21:55:00）をDateTimeに変換（大小比較や加減算が可能になる）
    #  cal_past_time_single：経過時間の算出
    #  等の関数有

    def __init__(self, accountID, access_token, env, notifier: Notifier | None = None):
        self.accountID = accountID  # インスタンス生成時に、引数で受け取る
        self.access_token = access_token  # インスタンス生成時に、引数で受け取る
        self.environment = env  # インスタンス生成時に、引数で受け取る
        self._notifier: Notifier = notifier if notifier is not None else get_notifier()
        self.api = API(
            access_token=access_token, environment=self.environment
        )  # API基盤の準備
        self.market_data = OandaMarketDataService(
            self.api,
            self.accountID,
            self.error_method,
        )
        self.orders = OandaOrdersService(
            self.api,
            self.accountID,
            self._notifier,
            self.error_method,
        )
        self.trades = OandaTradesService(
            self.api,
            self.accountID,
            self.error_method,
            func_make_dic,
        )
        self.print_words = ""  # 表示用。。
        self.print_words_bef = ""  # 表示用。。
        self.error_input_tp = (
            0.05  # マージン等がおかしい場合、この値を利用する（ドル用の場合0.05)
        )
        self.already_error_send1 = False  # エラーを一回だけスマホに送信したい場合

    def print_i(self, *msg):
        # 関数は可変複数のコンマ区切りの引数を受け付ける
        # temp = ""
        # 複数の引数を一つにする（数字が含まれる場合があるため、STRで文字化しておく）
        for item in msg:
            self.print_words = self.print_words + " " + str(item)
        self.print_words = self.print_words + "\n"  # 改行する

    def print_view(self):
        if self.print_words != self.print_words_bef:
            print(self.print_words)
            self.print_words_bef = self.print_words
            self.print_words = ""
        else:
            self.print_words = ""

    ############################################################
    # # Oanda操作系API 以下本チャン
    ############################################################
    # (1)現在価格を取得する
    def NowPrice_exe(self, instrument):
        """
        呼び出し:oa.NowPrice_exe("USD_JPY")
        返却値:Bid価格、Ask価格、Mid価格、スプレッド、左記４つを辞書形式で返却。返却値は、必ず小数点以下は３桁とする。
        """
        return self.market_data.now_price(instrument)

    # (2)キャンドルデータを取得(5000行以内/指定複雑)
    def InstrumentsCandles_exe(self, instrument, params):
        """
        過去情報（ローソク）の取得 （これが基本的にAPIを叩く関数）
        呼び出し方:oa.InstrumentsCandles_exe("USD_JPY",{"granularity": "M15","count": 30})　Countは最大5000。
        返却値:Dataframe[time,open.close,high,low,time_jp]の4列
        :param instrument:"USD_JPY"
        :param params:引数はそのままAPIに渡される。辞書形式となる。
            granularity:足幅。M1,M5,M15等。最小はS5（五秒足）
            count: 何行とるか。以下のtoを指定しない場合、直近からcount行を取得する
            price: 指定なし可。指定なしの場合AskとBidの中央価格（Mid）を取得。"A"でAsk価格、"B"でBid価格を取得
            to:2023-01-02T10:30:00.000000000Z の形式(ISOのEuro時間 JST-9)で指定。この時間"まで"のcount行のデータを取得する。
            from:2023-01-02T10:30:00.000000000Z の形式(ISOのEuro時間)で指定。この時間"から"のcount行のデータを取得する。
        :return:ここではmid列が辞書形式のままのデータフレーム
        <参考>
        ①指定した日本時刻をEuro時間に変更
        euro_time_datetime = datetime.datetime(2021, 4, 1, 20, 22, 33) - datetime.timedelta(hours=9)
        ②DateTime⇒ISOへの変換は以下のように実施
        euro_time_datetime_iso = str(euro_time_datetime.isoformat()) + ".000000000Z"  # ISOで文字型。.0z付き）
        ③Json例
        param = {"granularity": "M5", "count": 10, "to": euro_time_datetime_iso}
        oa.InstrumentsCandles_exe("USD_JPY", param)
        """
        return self.market_data.instruments_candles(instrument, params)

    # (3)キャンドルデータを取得(5000行以上/現在から/指定簡単（現在USD固定）)
    def InstrumentsCandles_multi_exe(self, pair, params, roop):
        """
        【注意】paramでFromを使うことはできない。toとcountの組み合わせのみMultiを有効に活用できる
        呼び出し方：oa.InstrumentsCandles_multi_exe("USD_JPY", {"granularity": "M5", "count": 30}, 1)
        過去情報をまとめて持ってくる【基本的にはこれを呼び出して過去の情報を取得する。InstrumentsCandles_exeとセット利用】
        なお、基本的にはMidの価格を取得する。AskやBidがほしい場合、
         oa.InstrumentsCandles_multi_exe("USD_JPY", {"granularity": "M5", "count": 50, "price": "B" }
         のように、priceで指定する（指定なし＝mid B＝bid A=ask ただし、221030日時点、Mid前提のクラスの為注意）
        返却値:Dataframe[time,open.close,high,low,time_jp]　＋　add_information関数達で情報追加
        :param pair: "USD_JPY" のような形式
        :param params:{"granularity": 'M5', "count": 5000}のように、足単位と何行取得するか(Max5000)。
                        デフォルトではmidlle価格（askとbidの中間）を取得。Ask/Bidを取得する場合、"price":"B"or"A"を追加。
        :param roop: 上記情報が何セット欲しいか(5000行以上欲しい場合に有効。5000以下は、この数は１の方が当然動きが早い）
        :return:
        """
        return self.market_data.instruments_candles_multi(pair, params, roop)

    # (4)キャンドルデータを取得(サポート専用。通常利用無し）
    def InstrumentsCandles_multi_support_exe(self, instrument, params):
        """
        過去情報（ローソク）の取得 （これが基本的にAPIを叩く関数）
        InstrumentsCandles_multi_exeから呼び出される専用
        """
        return self.market_data.instruments_candles_multi_support(instrument, params)

    # (5)オーダーの発行を実施
    def OrderCreate_dic_exe(self, for_api_json):
        """
                self.data = {  # オーダーのテンプレート！（一応書いておく）
                "order": {
                    "instrument": self.instrument,
                    "units": str(self.units * self.direction),
                    "type": self.ls_type,  # "STOP(逆指)" or "LIMIT" or "MARKET"
                    "positionFill": "DEFAULT",
                    "price": str(round(self.target_price, self.u)),  # 小数点3桁の文字列（それ以外はエラーとなる）
                    "takeProfitOnFill": {
                        "timeInForce": "GTC",
                        "price": str(round(self.tp_price, self.u))  # 小数点3桁の文字列（それ以外はエラーとなる）
                    },
                    "stopLossOnFill": {
                        "timeInForce": "GTC",
                        "price": str(round(self.lc_price, self.u))  # 小数点3桁の文字列（それ以外はエラーとなる）
                    },
                    # "trailingStopLossOnFill": {
                    #     "timeInForce": "GTC",
                    #     "distance": "0"  # 5pips以上,かつ,小数点3桁の文字列
                    # }
                }
            }
        ■オーダー種類について
          STOP:指値。順張り（現価格より高い値段で買い、現価格より低い値段で売りの指値）、また、ロスカット
          LIMIT:指値。逆張り（現価格より低い値段で買い、現価格より高い値段で売りの指値）、また、利確
          MARKET:成り行き。この場合、priceは設定しても無視される（ただし引数としてはテキトーな数字を入れる必要あり）。
        """
        return self.orders.order_create_dic_exe(for_api_json)

    # (6)オーダーのキャンセル
    def OrderCancel_exe(self, order_id):
        """
        注文（単品）キャンセルする。 a.OrderCancel_exe(order_id,"remark")
        ＜参考＞ロスカ注文やTP注文、通常の指値等、一つ一つにIDがある。ロスカIDのみのキャンセルが可能。
        :param order_id: キャンセルしたいオーダーのID（ポジションではなくオーダー）
        :return:基本的にはJsonで返却
        """
        return self.orders.order_cancel_exe(order_id)

    # (7)オーダーを全てキャンセル
    def OrderCancel_All_exe(self):
        """
        現在発行している、「新規にポジションを取るための注文」を全てキャンセルする。
        すでに所持しているポジションへのロスカ、利確、トレールの注文はキャンセルされない。
        (各ポジションのロスカや利確注文は削除しない（TPとLCを指値時に設定した場合、ポジションと同時にTP/LCオーダーが入る。）
        APIで「新規ポジションを取るための注文」はtypeがLimitかStopとなっており、それで上記を判定している）
        :return:
        """
        return self.orders.order_cancel_all_exe()

    # (7-2)オーダーの全ての個数を取得
    def OrderCount_All_exe(self):
        """
        現在発行している、「新規にポジションを取るための注文」の個数を取得する
        :return:
        """
        return self.orders.order_count_all_exe()

    # (8)オーダーの内容詳細の確認
    def OrderDetails_exe(self, order_id):
        """
        単品の注文内容の詳細を確認する
        :param order_id: 注文のID
        :return: あまり利用しないので、Jsonのままで返却
        """
        return self.orders.order_details_exe(order_id)

    # (9)指定のオーダーのステータス（オーダーとトレードの詳細）を取得
    def OrderDetailsState_exe(self, order_id):
        """
        単品の注文番号を渡すと、ポジションまで（ある場合）の情報を返却する
        order無し時でも、position有時でも、同一の辞書形式を返却する。
        :param order_id: 注文のID
        :return: Error有無、Data（どの場合も同一形式）
        """

        # 実行除外条件
        if order_id == 0:
            return 0

        # （１）オーダー状況取得
        order_ans = self.OrderDetails_exe(order_id)
        order_dic = order_ans["data"]["order"]
        print(order_dic)
        if order_dic["state"] == "FILLED":
            print("  ポジション移行有⇒ポジションを検索")
            if (
                "tradeClosedIDs" in order_dic["order"]
            ):  # 既にクローズまで行っている場合、これがPositionID
                position_id = order_dic["order"]["tradeClosedIDs"][
                    0
                ]  # PositionIDを取得
                position_type = "single"
            elif (
                "tradeReducedID" in order_dic["order"]
            ):  # 約定価格が同じ場合、グルーピングされる場合がある？？！
                position_id = order_dic["order"]["tradeReducedID"]
                position_type = "group"
            else:
                position_id = order_dic["order"][
                    "fillingTransactionID"
                ]  # PositionIDを取得
                position_type = "single"
        else:
            # Cancelやpendingの場合はやらない
            return 0

        # (2)ポジション情報の取得

        # (2) オーダーの情報を取得
        if order_id == 0:
            order_id = 0  # エラー同等
            error_flag = -1
            print(" ★OrderDetailState- orderID 0での問い合わせ発生", order_id)
        else:
            res_json_dic = self.OrderDetails_exe(order_id)
            if res_json_dic["error"] == -1:
                # オーダー無し（エラー含む）の場合
                print(" ★OrderDetailState- orderDetail ミス", order_id)
                res_json_dic["method"] = " ★OrderDetailState- orderDetail ミス"
                order_id = 0  # エラー同等
                error_flag = -1
            else:
                # オーダーありの場合、オーダー情報を取得する
                res_json = res_json_dic["data"]
                # orderの情報を取得する
                order_createtime = oanda_support.iso_to_jstdt_single(
                    res_json["order"]["createTime"]
                )
                order_time_past = cal_past_time_single(
                    oanda_support.iso_to_jstdt_single(res_json["order"]["createTime"])
                )
                order_units = res_json["order"]["units"]
                order_state = res_json["order"]["state"]  # オーダーのステータスを確認
                if (
                    "price" in res_json["order"]
                ):  # MARKET注文の場合、orderPriceが表示されない
                    order_price = res_json["order"]["price"]
                else:
                    order_price = 0

                # Positionを探しに行く
                if order_state == "PENDING" or order_state == "CANCELLED":  # 注文中
                    pass  # 初期値のまま（全て０）でOK
                else:  # order_state == 'FILLED':  # オーダー約定済み⇒ポジションIDを取得して情報を取得
                    # positionIDを取得
                    if (
                        "tradeClosedIDs" in res_json["order"]
                    ):  # 既にクローズまで行っている場合、これがPositionID
                        position_id = res_json["order"]["tradeClosedIDs"][
                            0
                        ]  # PositionIDを取得
                        position_type = "single"
                    elif (
                        "tradeReducedID" in res_json["order"]
                    ):  # 約定価格が同じ場合、グルーピングされる場合がある？？！
                        position_id = res_json["order"]["tradeReducedID"]
                        position_type = "group"
                    else:
                        position_id = res_json["order"][
                            "fillingTransactionID"
                        ]  # PositionIDを取得
                        position_type = "single"

                    # (2)ポジションの詳細を取得
                    position_js_dic = self.TradeDetails_exe(
                        position_id
                    )  # ★★★★★PositionIDから詳細を取得
                    if position_js_dic["error"] == -1:
                        # わかりやすいJsonを作っておく
                        position_js_dic["method"] = (
                            "★OrderDatailState- positionDetail ミス"
                        )
                        print(
                            "   ★OrderDatailState- positionDetail ミス",
                            position_id,
                            "(",
                            order_id,
                            ")",
                        )
                        error_flag = -1
                    else:
                        position_js = position_js_dic["data"]
                        if (
                            position_js["trade"]["state"] == "CLOSED"
                        ):  # すでに閉じたポジションの場合
                            # splitnumは本来１：１の分割ではないが、手間なのでとりあえず半々に分ける
                            split_num = float(
                                len(position_js["trade"]["closingTransactionIDs"])
                            )  # 複数が同時に出力される場合有
                            pips = round(
                                (float(position_js["trade"]["realizedPL"]) / split_num)
                                / abs(float(position_js["trade"]["initialUnits"])),
                                3,
                            )
                            position_initial_units = position_js["trade"][
                                "initialUnits"
                            ]
                            position_current_units = position_js["trade"][
                                "currentUnits"
                            ]
                            position_realize_pl = (
                                float(position_js["trade"]["realizedPL"]) / split_num
                            )
                            position_time = oanda_support.iso_to_jstdt_single(
                                position_js["trade"]["openTime"]
                            )  # ポジションした時間がうまる
                            position_close_time = oanda_support.iso_to_jstdt_single(
                                position_js["trade"]["closeTime"]
                            )  # ポジションがクローズした時間がうまる
                            position_price = position_js["trade"]["price"]  # 現在価格
                            position_state = position_js["trade"]["state"]
                            position_close_price = position_js["trade"][
                                "averageClosePrice"
                            ]
                        elif (
                            position_js["trade"]["state"] == "OPEN"
                        ):  # 所持中しているポジションの場合
                            pips = round(
                                float(position_js["trade"]["unrealizedPL"])
                                / abs(float(position_js["trade"]["initialUnits"])),
                                3,
                            )
                            position_initial_units = position_js["trade"][
                                "initialUnits"
                            ]
                            position_current_units = position_js["trade"][
                                "currentUnits"
                            ]
                            position_realize_pl = position_js["trade"]["unrealizedPL"]
                            position_time = oanda_support.iso_to_jstdt_single(
                                position_js["trade"]["openTime"]
                            )  # ポジションした時間がうまる
                            position_close_time = 0
                            position_price = position_js["trade"]["price"]
                            position_state = position_js["trade"]["state"]
                            position_close_price = 0
        # 返却の形式は以下に統一。
        res = {
            "func_complete": 0,  # APIエラーなく完了しているかどうか
            "order_id": order_id,
            "order_time": order_createtime,
            "order_time_past": order_time_past,
            "order_units": order_units,
            "order_price": order_price,  # Marketでは存在しない
            "order_state": order_state,
            "order_json": res_json,
            "position_id": position_id,
            "position_type": position_type,  # 両建てや部分解消の場合「group」が入る。
            "position_initial_units": position_initial_units,
            "position_current_units": position_current_units,
            "position_time": position_time,
            "position_time_past": cal_past_time_single(position_time)
            if position_time != 0
            else 0,
            "position_price": position_price,
            "position_state": position_state,
            "position_realize_pl": position_realize_pl,
            "position_pips": pips,
            "position_close_time": position_close_time,
            "position_close_price": position_close_price,
            "position_json": position_js_dic,
        }
        return {"data": res, "error": error_flag}

    # オーダーの一覧（全て）を取得
    def OrdersPending_exe(self):
        """
        注文中の一覧を取得する。
        APIからの返却情報に加え、オーダーの発行から現在までの経過時間（秒）も追加する。
        :return: データフレーム形式
        """
        return self.orders.orders_pending_exe()

    # (11)オーダーの一覧（新規トレード待ちのみ）を取得
    def OrdersWaitPending_exe(self):
        """
        注文の一覧を取得。
        ただし、新規にポジションを取得するための注文(typeがLimitかStopの物)のみ。
        typeがそれ以外の場合、ロスカット注文や利確注文の為、削除しない。
        ＜参考＞「新規のポジションを取得するための注文」は、APIではtypeがLimitかStopとなっている
        :return:
        """
        return self.orders.orders_wait_pending_exe()

    # (12)トレードの一覧を取得　OpenTrades_exe
    def OpenTrades_exe(self):
        """
        取引中の全ポジション一覧で取得。
        APIからの返却情報に加え、
        ・日本時間
        ・取得からの経過時間
        ・pips単位での含み損益（API返却値は円の為、ユニット数で商算したもの）
        を列に加える。
        :return: データフレーム形式
        """
        return self.trades.open_trades_exe()

    # (13)指定のトレードの詳細
    def TradeDetails_exe(self, trade_id):
        return self.trades.trade_details_exe(trade_id)

    # (14)指定のトレードの変更
    def TradeCRCDO_exe(self, trade_id, data):
        """
        :param trade_id:
        :param data:　以下の形式
            data = {
                "takeProfit": {"price": str(round(line, 3)),"timeInForce": "GTC",},
                "stopLoss": {"price": str(round(line, 3)),"timeInForce": "GTC",},
                "trailingStopLoss": {"distance": 0.05, "timeInForce": "GTC"},
            }
        :return:
        """
        return self.trades.trade_crcdo_exe(trade_id, data)

    # (15)指定のトレードの決済
    def TradeClose_exe(self, trade_id, data):
        """
        :param trade_id: 閉じたい対象のトレードID（数字）
        :param data: data=None　の場合は対象トレードを決済。部分決済したい場合は、data={"units": 30}
        :return:
        """
        return self.trades.trade_close_exe(trade_id, data)

    # (16)トレードを全て決済
    def TradeAllClose_exe(self):
        """
        引数無し。現在あるトレードを一括で消去する
        :return:
        """
        return self.trades.trade_all_close_exe()

    # (16-2)トレードの個数を取得する
    def TradeAllCount_exe(self):
        """
        引数無し。現在あるトレードノ個数を返却する
        :return:
        """
        return self.trades.trade_all_count_exe()

    # (17)ポジションの一覧を取得
    def OpenPositions_exe(self):
        try:
            ep = OpenPositions(accountID=self.accountID)
            res_json = eval(json.dumps(self.api.request(ep), indent=2))
            res_df = func_make_dic(res_json)  # 必要項目の抜出
            return res_df
        except Exception as e:
            print("★★APIエラー★★", e)
            return 0

    # (18)指定のポジションの詳細 instrument = "USD_JPY"
    def PositionDetails_exe(self, instrument):
        try:
            ep = PositionDetails(accountID=self.accountID, instrument=instrument)
            res_json = eval(json.dumps(self.api.request(ep), indent=2))
            return res_json
        except Exception as e:
            print("★★APIエラー★★", e)
            return 0

    # (19)指定のポジションの決済
    def PositionClose_exe(self, data):
        try:
            # 昔は引数が(self, instrument, data)　だった。instrumentを削除した
            ep = PositionClose(
                accountID=self.accountID, instrument="USD_JPY", data=data
            )
            res_json = eval(json.dumps(self.api.request(ep), indent=2))
            print(res_json)
            return res_json  # oa = Oanda(accountID, access_token)
        except Exception as e:
            print("★★APIエラー★★", e)
            return 0

    # (20)口座残高の取得
    def GetBalance_exe(self):
        client = oandapyV20.API(access_token=self.access_token)
        r = accounts.AccountSummary(self.accountID)
        response = client.request(r)
        res = response["account"]["balance"]
        return res  # oa = Oanda(accountID, access_token)

    # (21)トランザクション(取引履歴)の取得
    def GetActPrice_exe(self, transactionID):
        ep = trans.TransactionDetails(
            accountID=self.accountID, transactionID=transactionID
        )
        res_json = eval(json.dumps(self.api.request(ep), indent=2))
        print("トランザクション780行目")
        print(res_json)
        if "price" in res_json:
            act_price = res_json["price"]
        else:
            act_price = 99999999
        return act_price

    # (22)オーダーブックを取得する
    def OrderBook_exe(self, target_price):
        ep = instruments.InstrumentsOrderBook(instrument="USD_JPY")
        res_json = self.api.request(ep)  # 結果をjsonで取得
        df = pd.DataFrame(res_json["orderBook"]["buckets"])
        # 集計
        price = target_price

        from_price = price - 0.2
        from_price = from_price - (from_price % 0.05)
        from_price3 = "{:.3f}".format(from_price)
        from_index = df[df["price"] == from_price3].index.values[0]  # 一つのはず

        to_price = price + 0.2
        to_price = to_price - (to_price % 0.05)
        to_price3 = "{:.3f}".format(to_price)
        to_index = df[df["price"] == to_price3].index.values[0]

        df = df[from_index:to_index]
        df = df.sort_index(ascending=False)
        return df

    # (23)トランザクションデータの取得（単品）
    def get_transaction_single(self, num):
        ep = trans.TransactionIDRange(
            accountID=self.accountID, params={"to": num, "from": num}
        )
        resp = self.api.request(ep)
        return resp

    # (24) トランザクションデータを取得する（N　×　Row分）
    def get_base_data_multi(self, roop, num):
        """
        最新のデータから、N個さかのぼった分のデータをトランザクションデータを取得する。
        処理としては、まず最新の取引IDを取得し、そこからnum個分のデータを、roop回数取得する。
        numの最大値は、500(OandaのAPIの仕様上限。get_base_dataを利用してAPIを叩く事になる）
        例えば、num=3でroop=5とした場合、直近から３回分の取引データを５回分、ようするに直近１５回分の取引データを取得する。
        :param roop: N
        :param num:
        :return:
        """
        # 返却用DF
        for_ans = None
        # 最も新しいIDを取得する（TOに入れる用）
        ep = trans.TransactionIDRange(
            accountID=self.accountID, params={"to": 40746, "from": 40746}
        )
        resp = self.api.request(ep)
        latestT = resp["lastTransactionID"]

        for i in range(roop):
            params_temp = {"to": int(latestT), "from": int(latestT) - num + 1}
            ep = trans.TransactionIDRange(accountID=self.accountID, params=params_temp)
            resp = self.api.request(ep)
            # params内、toの変更
            latestT = int(latestT) - num

            # transactionの内の配列データを取得する
            transactions = resp["transactions"]
            print(len(transactions))

            all_info = []
            for item in transactions:
                # print("id=", item["id"])
                # print(item)
                # 考えるのめんどいので、必要項目だけ辞書形式にしてしまう
                dict = {
                    "id": item["id"],
                    "time": item["time"],
                    "type": item["type"],
                    # "reason": item["reason"],
                }
                # たまにreasonがないのが存在する。。41494とか
                if "reason" in item:
                    dict["reason"] = item["reason"]
                else:
                    dict["reason"] = 0
                #
                if "units" in item:
                    dict["units"] = item["units"]
                else:
                    dict["units"] = 0
                # ポジションオーダー時にある項目
                if "takeProfitOnFill" in item:
                    if "price" in item["takeProfitOnFill"]:
                        dict["price_tp"] = item["takeProfitOnFill"]["price"]
                    else:
                        dict["price_tp"] = 99999  # "N"
                else:
                    dict["price_tp"] = 0

                if "stopLossOnFill" in item:
                    if "price" in item["stopLossOnFill"]:
                        dict["price_lc"] = item["stopLossOnFill"]["price"]
                    else:
                        dict["price_lc"] = 99999  # "N"
                else:
                    dict["price_lc"] = 0
                # priceを含む場合（オーダーのキャンセル以外はpriceが入る）
                if "price" in item:
                    dict["price"] = item["price"]
                else:
                    dict["price"] = 0
                # ポジション解消時にある項目
                if "pl" in item:
                    dict["pl"] = item["pl"]
                else:
                    dict["pl"] = 0

                # 配列に追加する
                all_info.append(dict)

            t_df = pd.DataFrame(all_info)
            t_df["time_jp"] = t_df.apply(
                lambda x: oanda_support.iso_to_jstdt(x, "time"), axis=1
            )  # 日本時刻を追加する

            for_ans = pd.concat(
                [t_df, for_ans]
            )  # 結果用dataframeに蓄積（時間はテレコ状態）

        print("トランザクションデータ取得完了")
        return for_ans

    # (extra) エラー送信用
    def error_method(self, name, start_time, e):
        print("   ¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥")
        now_time = datetime.datetime.now().replace(microsecond=0)
        past_sec = (now_time - start_time).seconds

        print("　★API_Error【", name, "】", now_time, past_sec)
        # print(e)
        # エラーの種類によって表示やLINE送信を行う。
        if "OrderDetail" in name and not self.already_error_send1:
            self.already_error_send1 = True  # 一度きりの送信
            self._notifier.notify("おかしなオーダーdetailエラー発生⇒", e)

        # if name == "価格情報取得":
        #     print(e)

        if past_sec > 10:
            print("   時間切れエラー？")
        elif name == "オーダー" or name == "TradeClose":
            self._notifier.notify("オーダーエラー")
        else:
            pass
        # if type(e) == 'oandapyV20.exceptions.V20Error':
        #     e

        return {
            "error": -1,
            "method": name,
            "past_sec": past_sec,
            "now_time": now_time,
            "error_code": e,
        }


############################################################
# # 関連する関数
############################################################


# classOandaSupport.py と重複するヘルパーは一本化する
o_func = oanda_support.o_func
c_func = oanda_support.c_func
h_func = oanda_support.h_func
l_func = oanda_support.l_func
ih_func = oanda_support.ih_func
il_func = oanda_support.il_func
for_upper = oanda_support.for_upper
for_lower = oanda_support.for_lower
iso_to_jstdt = oanda_support.iso_to_jstdt
iso_to_jstdt_single = oanda_support.iso_to_jstdt_single
add_basic_data = oanda_support.add_basic_data
add_bb_data = oanda_support.add_bb_data


def func_d(t_dic, t_list):
    ans = len(t_list)
    # t1が指定のJsonにあれば
    if t_list[0] in t_dic:
        t_dic = t_dic[t_list[0]]
        # t2が指定のjsonにあれば
        if t_list[1] in t_dic:
            t_dic = t_dic[t_list[1]]
            if ans == 2:
                return t_dic
            else:
                # t3が指定のjsonにあれば
                if t_list[2] in t_dic:
                    t_dic = t_dic[t_list[2]]
                    return t_dic
                else:
                    return 0
        else:
            return 0
    else:  # 最初からなければ
        return 0


# クロス時の価格のみを抽出する
def cal_cross_price(x):
    """
    OandaClass内のadd_ema_data　から呼び出される。ゴールデンやデッドクロス時点の価格を求める関数
    """
    if x.cross != 0:  # cross がある場合
        ans = x.ema_s
    else:
        ans = None
    return ans


# 2直線のなす角度を求める
def cal_angle(x):
    """
    OandaClass内のadd_ema_data　から呼び出される。ゴールデンやデッドクロスの角度を算出する。あんまり使う数字ではない
    """
    sample1 = x.ema_l_tilt
    sample2 = x.ema_s_tilt
    u = np.array([sample1, 1])  # ベクトルの設定
    v = np.array([sample2, 1])
    i = np.inner(u, v)  # 内積
    n = LA.norm(u) * LA.norm(v)  # 長さ算出して掛け算
    c = i / n
    a = np.rad2deg(np.arccos(np.clip(c, -1.0, 1.0)))
    a_res = round(a, 1)  # 小数点以下１桁を表示（小数点２桁を切り上げ）
    if x.ema_l > x.ema_s:  # 角度に正負を持たせたい時
        a_res = a_res * -1
    return a_res


def func_make_dic(res_json):
    res = [
        {  # []でくくると、dataframeに変換しやすい
            "instrument": func_d(res_json, ["orderCreateTransaction", "instrument"]),
            "order_id": int(func_d(res_json, ["orderCreateTransaction", "id"])),
            "order_time": str(func_d(res_json, ["orderCreateTransaction", "time"])),
            "order_price": func_d(
                res_json, ["orderCreateTransaction", "price"]
            ),  # 指値の場合のみ？
            "order_units": float(func_d(res_json, ["orderCreateTransaction", "units"])),
            "order_type": func_d(res_json, ["orderCreateTransaction", "type"]),
            "order_reason": func_d(res_json, ["orderCreateTransaction", "reason"]),
            "order_price_sl": float(
                func_d(res_json, ["orderCreateTransaction", "stopLossOnFill", "price"])
            ),
            "order_price_tp": float(
                func_d(
                    res_json, ["orderCreateTransaction", "takeProfitOnFill", "price"]
                )
            ),
            "position_instrument": func_d(
                res_json, ["orderFillTransaction", "instrument"]
            ),
            "position_id": float(func_d(res_json, ["orderFillTransaction", "id"])),
            "position_time": str(func_d(res_json, ["orderFillTransaction", "time"])),
            "position_price": float(
                func_d(res_json, ["orderFillTransaction", "price"])
            ),
            "position_unit": float(func_d(res_json, ["orderFillTransaction", "units"])),
            "position_type": func_d(res_json, ["orderFillTransaction", "type"]),
            "position_reason": func_d(res_json, ["orderFillTransaction", "reason"]),
            "close_targetorder_id": func_d(
                res_json, ["orderFillTransaction", "tradeClose", "tradeID"]
            ),
            "cancel_id": func_d(res_json, ["orderCancelTransaction", "id"]),
            "cancel_time": func_d(res_json, ["orderCancelTransaction", "time"]),
            "cancel_targetorder_id": func_d(
                res_json, ["orderCancelTransaction", "orderID"]
            ),
            "cancel_reason": func_d(res_json, ["orderCancelTransaction", "reason"]),
            "cancel_type": func_d(res_json, ["orderCancelTransaction", "type"]),
            "remark": "remark",  # 過去の遺産
        }
    ]
    res_df = pd.DataFrame(res)  # DFに変換
    res_df["order_time_jp"] = res_df.apply(
        lambda x: oanda_support.iso_to_jstdt(x, "order_time"), axis=1
    )  # 日本時刻の表示
    res_df["position_time_jp"] = res_df.apply(
        lambda x: oanda_support.iso_to_jstdt(x, "position_time"), axis=1
    )  # 日本時刻の表示

    res_df = res_df.drop(["order_time", "position_time"], axis=1)  # unixtime?を削除
    return res_df


def str_to_time(str_time):
    """
    時刻（文字列：2023/5/24  21:55:00　形式）をDateTimeに変換する。
    何故かDFないの日付を扱う時、isoformat関数系が使えない。。なぜだろう。
    :param str_time:
    :return:
    """
    time_dt = datetime.datetime(
        int(str_time[0:4]),
        int(str_time[5:7]),
        int(str_time[8:10]),
        int(str_time[11:13]),
        int(str_time[14:16]),
        int(str_time[17:19]),
    )
    return time_dt


def str_to_time_hms(str_time):
    """
    時刻（文字列：2023/5/24  21:55:00　形式）をDateTimeに変換する。
    基本的には表示用。時刻だけにする。
    :param str_time:
    :return:
    """
    time_str = str_time[11:13] + ":" + str_time[14:16] + ":" + str_time[17:19]

    return time_str


# 注文系や確認系で利用する関数
def cal_past_time(x):
    """
    OpenTrades_exe等、いくつかの関数から呼び出され、ポジション取得やオーダー時間からの経過秒数を計算する関数
    order_time_jpと比較した秒数。（order_time_jpという列名でとりあえず固定する）
    order_time_jpはAPIでの返却は存在しないため、この関数を呼ぶ以前で、作成されている必要がある。
    """
    target_col = x["order_time_jp"]  # 関数内の変数変えるのめんどいので、強引に。
    time_dt = datetime.datetime(
        int(target_col[0:4]),
        int(target_col[5:7]),
        int(target_col[8:10]),
        int(target_col[11:13]),
        int(target_col[14:16]),
        int(target_col[17:19]),
    )
    time_past = (datetime.datetime.now() - time_dt).seconds  # 差分を秒で求める
    return time_past


# 注文系や確認系で利用する関数(single版）
def cal_past_time_single(x):
    """
    OpenTrades_exe等、いくつかの関数から呼び出され、ポジション取得やオーダー時間からの経過秒数を計算する関数
    引数の形式は、分割できる文字列であること(APIで取得したままの時刻）
    order_time_jpと比較した秒数。（order_time_jpという列名でとりあえず固定する）
    order_time_jpはAPIでの返却は存在しないため、この関数を呼ぶ以前で、作成されている必要がある。
    """
    try:
        target_col = x
        time_dt = datetime.datetime(
            int(target_col[0:4]),
            int(target_col[5:7]),
            int(target_col[8:10]),
            int(target_col[11:13]),
            int(target_col[14:16]),
            int(target_col[17:19]),
        )
        # 差分を秒で求める（タイミングで-値になるので、現在時刻-2秒)
        time_past = (
            datetime.datetime.now() + datetime.timedelta(seconds=2) - time_dt
        ).seconds
        return time_past
    except Exception:
        # print("  時刻形式が異なります", e)
        return 0


# 【ローソクへの情報追加】 MACD情報を追加する
def add_macd(data_df):
    """
    InstrumentsCandles_exeで取得したデータ（最新時刻が下にある降順データ）に情報を付与する。
    引数はInstrumentsCandles_exeで取得したデータフレーム。返却値は、それに下記列を付与した情報
    データが時間降順(最維が上）だとおかしくなるので、最初に必ず時間の昇順（直近が下＝取得時まま）に直す
    よって、返り値は昇順（最新が下）のデータ
    """
    data_df = data_df.copy()  # 謎のスライスウォーニング対策
    data_df = data_df.sort_index(ascending=True)  # 一回正順に（下が新規に）
    data_df["macd_ema_s"] = data_df["close"].ewm(span=12).mean()  # 初期値３
    data_df["macd_ema_l"] = data_df["close"].ewm(span=26).mean()  # 初期値６
    data_df["macd"] = data_df["macd_ema_s"] - data_df["macd_ema_l"]
    data_df["macd_signal"] = data_df["macd"].ewm(span=9).mean()  # 初期値 2
    data_df["macd_gap"] = data_df["macd"] - data_df["macd_signal"]
    data_df["macd_bool"] = data_df["macd"] > data_df["macd_signal"]
    dead = (data_df["macd_bool"] != data_df["macd_bool"].shift(1)) & (
        not data_df["macd_bool"]
    )  # ==はisで代用不可
    gold = (data_df["macd_bool"] != data_df["macd_bool"].shift(1)) & (
        data_df["macd_bool"]
    )
    data_df["macd_cross"] = [x + y * -1 for x, y in zip(gold, dead)]
    return data_df


# 【ローソクへの情報追加】 EMA情報を追加する
def add_ema_data(data_df):
    """
    InstrumentsCandles_exeで取得したデータ（最新時刻が下にある降順データ）に情報を付与する。（EMA＝移動平均線加重平均）
    引数はInstrumentsCandles_exeで取得したデータフレーム。返却値は、それに下記列を付与した情報
    """
    data_df = data_df.copy()  # 謎のスライスウォーニング対策
    longspan = 23  # ema算出時の長期線のスパン
    shortspan = 2  # ema算出時の短期線のスパン
    t_num = 3  # 各emaの傾きを求める（n点間の平均傾き）
    # gap = 3  # n足前を正解とするか（機械学習前提値）
    # emaクロス判定
    data_df["ema_l"] = data_df["close"].ewm(span=longspan).mean()
    data_df["ema_s"] = data_df["close"].ewm(span=shortspan).mean()
    data_df["ema_gap"] = data_df["ema_s"] - data_df["ema_l"]
    data_df["ema_bool"] = data_df["ema_s"] > data_df["ema_l"]
    dead = (data_df["ema_bool"] != data_df["ema_bool"].shift(1)) & (
        not data_df["ema_bool"]
    )  # ==はisで代用不可
    gold = (data_df["ema_bool"] != data_df["ema_bool"].shift(1)) & (data_df["ema_bool"])
    data_df["cross"] = [x + y * -1 for x, y in zip(gold, dead)]
    data_df["cross_price"] = data_df.apply(lambda x: cal_cross_price(x), axis=1)
    data_df["close_tilt"] = (
        data_df["close"] - data_df["close"].shift(t_num - 1)
    ) / t_num
    data_df["ema_l_tilt"] = (
        data_df["ema_l"] - data_df["ema_l"].shift(t_num - 1)
    ) / t_num
    data_df["ema_s_tilt"] = (
        data_df["ema_s"] - data_df["ema_s"].shift(t_num - 1)
    ) / t_num
    data_df["cross_tilt"] = data_df.apply(lambda x: cal_angle(x), axis=1)

    # data_df.drop(['ema_l', 'ema_s', 'ema_bool'], axis=1, inplace=True)
    # data_df.drop(['ema_bool'], axis=1, inplace=True)
    return data_df


