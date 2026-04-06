import datetime

import classCandleAnalysis as ca
import classOanda as oanda_class
import fAnalysis_order_Main as am
from config.app_config import load_app_config

_APP_CONFIG = load_app_config()
_RUNTIME_ACCOUNTS = _APP_CONFIG.runtime_accounts

# グローバルでの宣言
oa = oanda_class.Oanda(
    _RUNTIME_ACCOUNTS.live_sub_account_id,
    _RUNTIME_ACCOUNTS.live_access_token,
    _RUNTIME_ACCOUNTS.live_environment,
)  # クラスの定義
print(oa.NowPrice_exe("USD_JPY"))
gl_start_time = datetime.datetime.now()
gl_now = datetime.datetime.now().replace(microsecond=0)  # 現在の時刻を取得
gl_now_str = (
    str(gl_now.month).zfill(2)
    + str(gl_now.day).zfill(2)
    + "_"
    + str(gl_now.hour).zfill(2)
    + str(gl_now.minute).zfill(2)
    + "_"
    + str(gl_now.second).zfill(2)
)


# 解析パート
def analysis_part():
    am.wrap_all_analysis(gl_candleAnalysisClass, None, "inspection")


def main():
    """
    メイン関数　全てここからスタートする。ここではデータを取得する
    通常の解析と、ループの解析で利用する。
    通常の解析の場合、*argsは０個。
    ループ解析(別ファイルの関数)の場合、*argsはargs[0]はparams(パラメータ集)、dic_args[1]はパメータ番号(表示用）
    :return:
    """

    # （０）環境の準備
    global gl_candleAnalysisClass

    # ■■調査用のDFの行数の指定
    res_part_low = gl_res_part_low  # 解析には50行必要(逆順DFでの直近R行が対象の為、[0:R]。check_mainと同値であること。
    analysis_part_low = gl_analysis_part_low  # 解析には200行必要(逆順DFで直近N行を結果パートに取られた後の為、[R:R+A])。check_mainと同値であること。
    (
        res_part_low + analysis_part_low
    )  # 検証パートと結果参照パートの合計。count<=need_analysis_num。
    # ■■取得する足数
    # ■■取得時間の指定
    now_time = gl_use_now  # False  # 現在時刻実行するかどうか False True　　Trueの場合は現在時刻で実行。target_timeを指定したいときはFalseにする。

    # (１)情報の取得
    print("###")
    if now_time:
        # 直近の時間で検証
        gl_candleAnalysisClass = ca.candleAnalysis(oa, 0)
    else:
        # jp_timeは解析のみは指定時刻のまま、解析＋検証の場合は指定時間を解析時刻となるようにする（検証分を考慮）。
        gl_candleAnalysisClass = ca.candleAnalysis(oa, gl_target_time)
    # データの成型と表示
    df = gl_candleAnalysisClass.d5_df_r  # data部のみを取得
    df.to_csv(
        _APP_CONFIG.folder_path + "main_analysis_original_data.csv",
        index=False,
        encoding="utf-8",
    )  # 直近保存用
    df.sort_index(ascending=False)  # 逆順に並び替え（直近が上側に来るように）

    # （2）【解析パートを一回のみ実施する場合】　直近N行で検証パートのテストのみを行う場合はここでTrue
    analysis_part()  # 取得したデータ（直近上位順）をそのまま渡す。検証に必要なのは現在200行


gl_gr = "M5"  # 取得する足の単位
gl_inspection_start_time = 0
gl_inspection_end_time = 0

# 解析と検証に必要な行数
gl_res_part_low = 25  # 解析には50行必要(逆順DFでの直近R行が対象の為、[0:R]。check_mainと同値であること。
gl_analysis_part_low = 85  # 解析には200行必要(逆順DFで直近N行を結果パートに取られた後の為、[R:R+A])。check_mainと同値であること。
# 取得する行数(1回のテストをしたい場合、指定でもres_part_low + analysis_part_lowが必要）
gl_count = gl_res_part_low + gl_analysis_part_low + 1
gl_times = 1  # Count(最大5000件）を何セット取るか  大体2225×３で１
gl_candleAnalysisClass = None


# ■■取得時間の指定
gl_use_now = False  # 現在時刻実行するかどうか False True　　Trueの場合は現在時刻で実行。target_timeを指定したいときはFalseにする。
gl_target_time = datetime.datetime(2026, 3, 10, 22, 30, 6)

# Mainスタート
main()  # 本番環境
