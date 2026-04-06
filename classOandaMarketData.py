import datetime
import json

import oandapyV20.endpoints.instruments as instruments
import pandas as pd
from oandapyV20.endpoints.pricing import PricingInfo

import classOandaSupport as oanda_support


class OandaMarketDataService:
    def __init__(self, api, account_id, error_handler):
        self.api = api
        self.account_id = account_id
        self.error_handler = error_handler

    def now_price(self, instrument):
        start_time = datetime.datetime.now().replace(microsecond=0)
        params = {"instruments": instrument}
        ep = PricingInfo(accountID=self.account_id, params=params)

        try:
            res_json = json.dumps(self.api.request(ep), indent=2)
            res_json = json.loads(res_json)
            res_dic = {
                "bid": round(float(res_json["prices"][0]["bids"][0]["price"]), 3),
                "ask": round(float(res_json["prices"][0]["asks"][0]["price"]), 3),
                "mid": round(
                    (
                        float(res_json["prices"][0]["asks"][0]["price"])
                        + float(res_json["prices"][0]["bids"][0]["price"])
                    )
                    / 2,
                    3,
                ),
                "spread": round(
                    float(res_json["prices"][0]["asks"][0]["price"])
                    - float(res_json["prices"][0]["bids"][0]["price"]),
                    3,
                ),
            }
            return {"data": res_dic, "error": 0}
        except Exception as e:
            return self.error_handler("価格情報取得", start_time, e)

    def instruments_candles(self, instrument, params):
        start_time = datetime.datetime.now().replace(microsecond=0)
        try:
            ep = instruments.InstrumentsCandles(instrument=instrument, params=params)
            res_json = self.api.request(ep)
            data_df = pd.DataFrame(res_json["candles"])
            data_df["time_jp"] = data_df.apply(
                lambda x: oanda_support.iso_to_jstdt(x, "time"), axis=1
            )
            data_df = oanda_support.add_basic_data(data_df)
            data_df = oanda_support.add_bb_data(data_df)
            return {"data": data_df, "error": 0}
        except Exception as e:
            return self.error_handler("価格情報取得[単]", start_time, e)

    def instruments_candles_multi(self, pair, params, roop):
        candles = None
        params_local = dict(params)

        for _ in range(roop):
            df_dic = self.instruments_candles_multi_support(pair, params_local)
            if df_dic["error"] == 0:
                df = df_dic["data"]
                params_local["to"] = df["time"].iloc[0]
                candles = pd.concat([df, candles])
            else:
                return df_dic

        candles.sort_values("time_jp", inplace=True)
        temp_df = candles.reset_index()
        temp_df.drop(["index"], axis=1, inplace=True)
        data_df = oanda_support.add_basic_data(temp_df)
        data_df = oanda_support.add_bb_data(data_df)
        return {"data": data_df, "error": 0}

    def instruments_candles_multi_support(self, instrument, params):
        start_time = datetime.datetime.now().replace(microsecond=0)
        try:
            ep = instruments.InstrumentsCandles(instrument=instrument, params=params)
            res_json = self.api.request(ep)
            data_df = pd.DataFrame(res_json["candles"])
            data_df.insert(
                0,
                "time_jp",
                data_df.apply(
                    lambda x: oanda_support.iso_to_jstdt(x, "time"),
                    axis=1,
                ),
            )
            return {"error": 0, "data": data_df}
        except Exception as e:
            return self.error_handler("ローソク取得", start_time, e)
