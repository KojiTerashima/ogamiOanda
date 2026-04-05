import datetime

import pytz


def o_func(x):
    return float(x["mid"]["o"])


def c_func(x):
    return float(x["mid"]["c"])


def h_func(x):
    return float(x["mid"]["h"])


def l_func(x):
    return float(x["mid"]["l"])


def ih_func(x):
    if float(x["mid"]["o"]) > float(x["mid"]["c"]):
        return float(x["mid"]["o"])
    return float(x["mid"]["c"])


def il_func(x):
    if float(x["mid"]["o"]) < float(x["mid"]["c"]):
        return float(x["mid"]["o"])
    return float(x["mid"]["c"])


def for_upper(x):
    return x["high"] - x["inner_high"]


def for_lower(x):
    return x["inner_low"] - x["low"]


def iso_to_jstdt(x, colname):
    iso_str = x[colname]
    dt = None
    split_timedate = iso_str.rsplit(".", 8)
    iso_str = split_timedate[0]
    try:
        dt = datetime.datetime.strptime(iso_str, "%Y-%m-%dT%H:%M:%S")
        dt = pytz.utc.localize(dt).astimezone(pytz.timezone("Asia/Tokyo"))
    except ValueError:
        try:
            dt = datetime.datetime.strptime(iso_str, "%Y-%m-%dT%H:%M:%S")
            dt = dt.astimezone(pytz.timezone("Asia/Tokyo"))
        except ValueError:
            pass
    if dt is None:
        return ""
    return dt.strftime("%Y/%m/%d %H:%M:%S")


def iso_to_jstdt_single(iso_str):
    dt = None
    split_timedate = iso_str.rsplit(".", 8)
    iso_str = split_timedate[0]
    try:
        dt = datetime.datetime.strptime(iso_str, "%Y-%m-%dT%H:%M:%S")
        dt = pytz.utc.localize(dt).astimezone(pytz.timezone("Asia/Tokyo"))
    except ValueError:
        try:
            dt = datetime.datetime.strptime(iso_str, "%Y-%m-%dT%H:%M:%S")
            dt = dt.astimezone(pytz.timezone("Asia/Tokyo"))
        except ValueError:
            pass
    if dt is None:
        return ""
    return dt.strftime("%Y/%m/%d %H:%M:%S")


def add_basic_data(data_df):
    data_df = data_df.copy()
    data_df["open"] = data_df.apply(lambda x: o_func(x), axis=1)
    data_df["close"] = data_df.apply(lambda x: c_func(x), axis=1)
    data_df["high"] = data_df.apply(lambda x: h_func(x), axis=1)
    data_df["low"] = data_df.apply(lambda x: l_func(x), axis=1)
    data_df["mid_outer"] = round((data_df["high"] + data_df["low"]) / 2, 3)
    data_df["inner_high"] = data_df.apply(lambda x: ih_func(x), axis=1)
    data_df["inner_low"] = data_df.apply(lambda x: il_func(x), axis=1)
    data_df["body"] = data_df["close"] - data_df["open"]
    data_df["body_abs"] = abs(data_df["close"] - data_df["open"])
    data_df["moves"] = data_df["high"] - data_df["low"]
    data_df["up_rod"] = data_df.apply(lambda x: for_upper(x), axis=1)
    data_df["low_rod"] = data_df.apply(lambda x: for_lower(x), axis=1)
    data_df["highlow"] = data_df["high"] - data_df["low"]
    data_df["middle_price"] = round(
        (data_df["inner_low"] + data_df["inner_high"]) / 2,
        3,
    )
    data_df["middle_price_wick"] = round(
        (data_df["high"] + data_df["low"]) / 2,
        3,
    )
    data_df = data_df[[col for col in data_df.columns if col != "time"] + ["time"]]
    data_df.drop(["complete"], axis=1, inplace=True)
    data_df.drop(["mid"], axis=1, inplace=True)
    return data_df


def add_bb_data(data_df):
    data_df = data_df.copy()
    bb_range = 30
    data_df["mean"] = data_df["close"].rolling(window=bb_range).mean()
    data_df["std"] = data_df["close"].rolling(window=bb_range).std()
    data_df["bb_upper"] = data_df["mean"] + (data_df["std"] * 2)
    data_df["bb_lower"] = data_df["mean"] - (data_df["std"] * 2)
    data_df["bb_middle"] = round((data_df["bb_lower"] + data_df["bb_upper"]) / 2, 3)
    data_df["bb_range"] = data_df["bb_upper"] - data_df["bb_lower"]
    data_df.drop(["mean", "std"], axis=1, inplace=True)
    return data_df
