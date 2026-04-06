import datetime
import json

import pandas as pd
from oandapyV20.endpoints.orders import (
    OrderCancel,
    OrderCreate,
    OrderDetails,
    OrdersPending,
)

import classOandaSupport as oanda_support


class OandaOrdersService:
    def __init__(self, api, account_id, notifier, error_handler):
        self.api = api
        self.account_id = account_id
        self.notifier = notifier
        self.error_handler = error_handler

    def order_create_dic_exe(self, for_api_json):
        start_time = datetime.datetime.now().replace(microsecond=0)
        try:
            ep = OrderCreate(accountID=self.account_id, data=for_api_json)
            res_json = eval(json.dumps(self.api.request(ep), indent=2))
            if "orderCancelTransaction" in res_json:
                print("   ■■■OrderCANCELあり(エラーによるorderReject)")
                print(res_json)
                self.notifier.notify("オーダーエラー", res_json)
                canceled = True
                order_id = 0
                order_time = 0
                execution_price = 0
            else:
                canceled = False
                order_id = res_json["orderCreateTransaction"]["id"]
                order_time = oanda_support.iso_to_jstdt_single(
                    res_json["orderCreateTransaction"]["time"]
                )
                if "orderFillTransaction" in res_json:
                    execution_price = float(res_json["orderFillTransaction"]["price"])
                else:
                    execution_price = 0

            order_info = {
                "price": for_api_json["order"]["price"],
                "execution_price": str(execution_price),
                "type": for_api_json["order"]["type"],
                "cancel": canceled,
                "order_id": order_id,
                "order_time": order_time,
                "json": res_json,
            }
            return {"error": 0, "data": order_info}
        except Exception as e:
            print("★★★OrderCreateAPIエラー")
            return self.error_handler("オーダー", start_time, e)

    def order_cancel_exe(self, order_id):
        start_time = datetime.datetime.now().replace(microsecond=0)
        try:
            ep = OrderCancel(accountID=self.account_id, orderID=order_id)
            res_json = eval(json.dumps(self.api.request(ep), indent=2))
            return {"data": res_json, "error": 0}
        except Exception as e:
            print("OrderCansel_APIerror", order_id)
            return self.error_handler("OrderCancel_APIerror" + str(order_id), start_time, e)

    def order_cancel_all_exe(self):
        open_df_dic = self.orders_pending_exe()
        close_df = None
        if open_df_dic["error"] == -1:
            print("Error")
            return open_df_dic

        open_df = open_df_dic["data"]
        for _, row in open_df.iterrows():
            if row["type"] == "STOP_LOSS" or row["type"] == "TAKE_PROFIT":
                pass
            else:
                self.order_cancel_exe(row["id"])
        return close_df

    def order_count_all_exe(self):
        open_df_dic = self.orders_pending_exe()
        count = 0
        if open_df_dic["error"] == -1:
            print("Error")
            return open_df_dic

        open_df = open_df_dic["data"]
        for _, row in open_df.iterrows():
            if (
                row["type"] == "MARKET_IF_TOUCHED"
                or row["type"] == "STOP"
                or row["type"] == "LIMIT"
            ):
                count = count + 1
        return count

    def order_details_exe(self, order_id):
        start_time = datetime.datetime.now().replace(microsecond=0)
        try:
            ep = OrderDetails(accountID=self.account_id, orderID=order_id)
            res_json = eval(json.dumps(self.api.request(ep), indent=2))
            res_json["order"]["time_past"] = _cal_past_time_single(
                oanda_support.iso_to_jstdt_single(res_json["order"]["createTime"])
            )
            return {"data": res_json, "error": 0}
        except Exception as e:
            e_info = self.error_handler("OrderDetail" + str(order_id), start_time, e)
            e_info["o_id"] = order_id
            return {"data": e_info, "error": 1}

    def orders_pending_exe(self):
        start_time = datetime.datetime.now().replace(microsecond=0)
        try:
            ep = OrdersPending(accountID=self.account_id)
            res_json = eval(json.dumps(self.api.request(ep), indent=2))
            res_df = pd.DataFrame(res_json["orders"])
            if len(res_df) == 0:
                return {"data": res_df, "error": 0}

            res_df["order_time_jp"] = res_df.apply(
                lambda x: oanda_support.iso_to_jstdt(x, "createTime"), axis=1
            )
            res_df["past_time_sec"] = res_df.apply(lambda x: _cal_past_time(x), axis=1)
            return {"data": res_df, "error": 0}
        except Exception as e:
            return self.error_handler("OrdersPending", start_time, e)

    def orders_wait_pending_exe(self):
        start_time = datetime.datetime.now().replace(microsecond=0)
        try:
            ep = OrdersPending(accountID=self.account_id)
            res_json = eval(json.dumps(self.api.request(ep), indent=2))
            res_df = pd.DataFrame(res_json["orders"])
            if len(res_df) == 0:
                return {"data": res_df, "error": 0}

            res_df["order_time_jp"] = res_df.apply(
                lambda x: oanda_support.iso_to_jstdt(x, "createTime"), axis=1
            )
            res_df["past_time_sec"] = res_df.apply(lambda x: _cal_past_time(x), axis=1)

            del_target = []
            for index, row in res_df.iterrows():
                if (
                    row["type"] == "MARKET_IF_TOUCHED"
                    or row["type"] == "STOP"
                    or row["type"] == "LIMIT"
                ):
                    pass
                else:
                    del_target.append(index)
            res_df.drop(index=del_target, inplace=True)
            return {"data": res_df, "error": 0}
        except Exception as e:
            return self.error_handler("OrdersPending", start_time, e)


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
