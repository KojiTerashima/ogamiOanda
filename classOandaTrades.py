import datetime
import json

import pandas as pd
from oandapyV20.endpoints.trades import OpenTrades, TradeClose, TradeCRCDO, TradeDetails

import classOandaSupport as oanda_support


class OandaTradesService:
    def __init__(self, api, account_id, error_handler, make_dic_func):
        self.api = api
        self.account_id = account_id
        self.error_handler = error_handler
        self.make_dic_func = make_dic_func

    def open_trades_exe(self):
        start_time = datetime.datetime.now().replace(microsecond=0)
        try:
            ep = OpenTrades(accountID=self.account_id)
            res_json = eval(json.dumps(self.api.request(ep), indent=2))
            res_df = pd.DataFrame(res_json["trades"])
            if len(res_df) == 0:
                return {"data": res_df, "error": 0}

            res_df["order_time_jp"] = res_df.apply(
                lambda x: oanda_support.iso_to_jstdt(x, "openTime"), axis=1
            )
            res_df["past_time_sec"] = res_df.apply(lambda x: _cal_past_time(x), axis=1)
            res_df["unrealizedPL_pips"] = round(
                res_df["unrealizedPL"].astype("float")
                / abs(res_df["currentUnits"].astype("float")),
                3,
            )
            return {"data": res_df, "error": 0, "json": res_json}
        except Exception as e:
            return self.error_handler("OpenTrades", start_time, e)

    def trade_details_exe(self, trade_id):
        start_time = datetime.datetime.now().replace(microsecond=0)
        try:
            ep = TradeDetails(accountID=self.account_id, tradeID=trade_id)
            res_json = eval(json.dumps(self.api.request(ep), indent=2))
            res_json["trade"]["time_past"] = _cal_past_time_single(
                oanda_support.iso_to_jstdt_single(res_json["trade"]["openTime"])
            )
            temp = res_json["trade"]
            if temp["state"] == "OPEN":
                res_json["trade"]["PLu"] = round(
                    float(temp["unrealizedPL"]) / abs(float(temp["initialUnits"])), 3
                )
            elif temp["state"] == "CLOSED":
                res_json["trade"]["PLu"] = round(
                    float(temp["realizedPL"]) / abs(float(temp["initialUnits"])), 3
                )
            else:
                print("    Tradeの状態を確認＠oandaClass TradeDetails_exe")
                res_json["trade"]["PLu"] == 0
            res_json["trade"]["openTime"] = oanda_support.iso_to_jstdt_single(
                res_json["trade"]["openTime"]
            )
            return {"data": res_json, "error": 0}
        except Exception as e:
            print(trade_id, "でエラー　@oandaClass630")
            e_info = self.error_handler("TradeDetails" + str(trade_id), start_time, e)
            return {"data": e_info, "error": 1}

    def trade_crcdo_exe(self, trade_id, data):
        start_time = datetime.datetime.now().replace(microsecond=0)

        if "stopLoss" in data:
            data["stopLoss"]["price"] = str(round(float(data["stopLoss"]["price"]), 3))
        if "takeProfit" in data:
            data["takeProfit"]["price"] = str(
                round(float(data["takeProfit"]["price"]), 3)
            )
        if "trailingStopLoss" in data:
            data["trailingStopLoss"]["distance"] = str(
                round(float(data["trailingStopLoss"]["distance"]), 3)
            )

        try:
            ep = TradeCRCDO(accountID=self.account_id, tradeID=trade_id, data=data)
            res_json = eval(json.dumps(self.api.request(ep), indent=2))
            return {"data": res_json, "error": 0}
        except Exception as e:
            return self.error_handler("TradeCRCDO", start_time, e)

    def trade_close_exe(self, trade_id, data):
        start_time = datetime.datetime.now().replace(microsecond=0)
        try:
            ep = TradeClose(accountID=self.account_id, tradeID=trade_id, data=data)
            res_json = eval(json.dumps(self.api.request(ep), indent=2))
            res_df = self.make_dic_func(res_json)
            return {"data_json": res_json, "data": res_df, "error": 0}
        except Exception as e:
            return self.error_handler("TradeClose", start_time, e)

    def trade_all_close_exe(self):
        open_df_dic = self.open_trades_exe()
        if open_df_dic["error"] == -1:
            return open_df_dic

        open_df = open_df_dic["data"]
        if len(open_df) == 0:
            return {"data": None, "error": 0}

        count = 0
        close_df = None
        for _, row in open_df.iterrows():
            res_df = self.trade_close_exe(row["id"], None)
            if res_df["error"] == -1:
                pass
            else:
                res_df = res_df["data"]
                close_df = pd.concat([close_df, res_df])
                count = count + 1
        print("   @PositionClear:", count, "個(@all close func)")
        return {"data": close_df, "error": 0}

    def trade_all_count_exe(self):
        open_df_dic = self.open_trades_exe()
        if open_df_dic["error"] == -1:
            return open_df_dic

        open_df = open_df_dic["data"]
        if len(open_df) == 0:
            print("  @tradeCountFunction(0)")
            return {"data": 0, "error": 0}
        return {"data": len(open_df), "error": 0}


def _cal_past_time(x):
    target_col = x["order_time_jp"]
    time_dt = datetime.datetime(
        int(target_col[0:4]),
        int(target_col[5:7]),
        int(target_col[8:10]),
        int(target_col[11:13]),
        int(target_col[14:16]),
        int(target_col[17:19]),
    )
    return (datetime.datetime.now() - time_dt).seconds


def _cal_past_time_single(x):
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
        return (datetime.datetime.now() + datetime.timedelta(seconds=2) - time_dt).seconds
    except Exception:
        return 0
