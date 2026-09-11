# mainの原文を使う解析

[索引](README.md) / [original戦略](../src/ogami_oanda/strategy/original/README.md)

mainディレクトリのPythonファイルを直接読み込み、その関数へogamiOandaの足・時刻・価格を渡します。
mainの原文は変更せず、ogamiOandaへコピーしません。同期スクリプトやコードのハッシュ照合はありません。
mainの認証設定・保存済み市場データは読み込みません。

## 配置と起動

標準の配置は次のとおりです。コマンドはogamiOandaのルートから実行します。

```text
workspace/
  main/         ← 解析プログラムと必要な依存コード
  ogamiOanda/    ← 起動するプログラム
```

参照先の既定値は作業ディレクトリからの`../main`です。別の配置ではliveとbacktestの`run`に
`--main-analysis-dir PATH`を指定します。相対パスは作業ディレクトリを基準にし、絶対パスも使えます。
インストールしたパッケージから使う場合も、外部のmainディレクトリをこの引数で指定します。

Pythonでは`MainSourceAnalysis(source_directory="../main")`、組立関数の
`build_live_application`・`build_strategy_live_application`・`run_backtest`では
`main_analysis_dir="../main"`を指定できます。指定を省略した場合も同じ既定値です。
明示的に注入した解析器はそのまま使用します。

履歴取得だけの`fetch`、Matcha、ヘルプ、offline smoke、別の解析器を注入した経路にはmainは不要です。
originalを使う実行器は初期化時に必要な25ファイルを読み込みます。
ディレクトリや必須ファイルがなければ、そのパスを示してエラーにします。旧計算への自動切替はありません。

## 呼び出し方

次は外部通信・注文発注を行わない呼び出し例です。`frames` は呼び出し側で取得したDataFrameの辞書です。

```python
from ogami_oanda.adapters.legacy.main_analysis import (
    MainSourceAnalysis, analyze, build_order_candidates,
)
from ogami_oanda.domain.analysis.main_contracts import AnalysisRequest
from ogami_oanda.domain.analysis.main_orders import to_order_intents

backend = MainSourceAnalysis(source_directory="../main")
request = AnalysisRequest(
    pair="EUR_USD",
    decision_time="2026-09-11 12:00:00",   # 解析する確定足の判断境界
    evaluation_time="2026-09-11 12:00:09", # この評価を実行した時刻
    current_price=1.10,
    candle_frames=frames,                 # M5/H1/M30/S5
    mode="inspection",                   # 本番取得済み足は "live"
    usd_jpy_rate=150.0,                   # 任意の換算レート
    risk_yen=500,
)
with backend.evaluation(request) as session:
    result = analyze(session, "line")
    candidates = build_order_candidates(session, result)
intents = to_order_intents(candidates)
```

`analyze` と `build_order_candidates` は別モジュール・別関数です。
原文の戦略インスタンス等はセッションに保持し、外へ返すのはコピーした解析値と注文候補だけです。
候補作成には同じセッションで得た結果が必要です。別セッション・終了済みセッションの結果は拒否します。
同じ結果から同じ注文設定で候補を再取得しても注文計算を重複実行しません。

| 解析名 | 解析処理 | 候補作成 |
| --- | --- | --- |
| `candles` | 原文の指標・確定足・ピーク。各時間足の`completed_frame`を含む | 空 |
| `line` | M5/H1ラインと原文の通貨別プロファイル | RSI条件・選択・価格・数量を原文で計算 |
| `shape` | 足本数と形状 | 空 |
| `stair` | M5/H1階段トレンド | 空 |
| `double_top` | ダブルトップ検出 | 原文のtrial注文 |
| `resistance_breakout` | 抵抗線選択とブレイク検出 | 原文の注文 |
| `flip` | 検証済みアーティファクトによるシグナル | 専用監視が必要な待機候補 |

ラインの注文設定は`risk_yen`を受け付けます。ダブルトップの検出設定は原文のpolicyフィールド、
注文設定は`target_height_multiplier/stop_buffer_pips/min_order_distance_pips/risk_yen/priority/trade_timeout_min`です。
ブレイクアウトは解析時のpolicyを候補作成にも使います。flipは原文の承認済みpolicyを使います。

## 足・時刻・価格の契約

- 必須はM5/H1。通常のoriginal経路はM30/S5も渡します。原文の必要履歴は確定済みM5 180本、H1 240本です。
- OHLCと`time_jp_dt`、`time_jp`、UTCの`time`のいずれかを受け付けます。
  naive時刻はJSTです。未来足を除き、指標計算後に新しい順へ揃えます。入力DataFrameは変更しません。
- liveでは`complete`または`is_complete`が必要です。確定フラグと判断境界から原文が足を選びます。
  inspectionではフラグなしの履歴も時刻で選びます。全足確定済みの入力から最新足を二重除外しません。
- `source_granularities={"M30": "H1"}`はH1を代用したM30を示します。M30省略時も原文のH1代用になります。
  native M30必須の解析へ代用足を偽装しません。
- 通貨処理・丸め・数量は原文に委譲します。注文候補には解決済み価格と数量を保存します。
  Intentのtarget/TP/SLはすべて価格指定です。Plannerも価格指定のMARKETを再計算しません。
- inspectionのライン換算には`conversion_candles`（`time_jp/close`）を優先します。
  それがなければ明示した`usd_jpy_rate`、指定なしなら原文の既定換算を使います。
  他の解析のinspection時の換算方針も原文どおりです。互換実行器は換算価格を取りに行きません。

正常な未検出は`AnalysisResult.status="no_signal"`と空候補で表します。
足・承認済みアーティファクトの不足は`AnalysisNotReady`、履歴不整合は`AnalysisIntegrityError`、
未対応の解析・import・注文形式は`UnsupportedAnalysisDependency`です。
original用`evaluate`は確定待ちを`status="not_ready"`の空結果に変換し、理由を診断へ返します。
liveの履歴警告を継続可能とする原文の判断も維持します。

## 発注・管理との境界

live、backtest、組込みoriginalのプラグイン組立で、同じ`MainSourceAnalysis`を注入します。
strategyはdomainの`MainAnalysisBackend`だけを参照し、adapterを直接importしません。
`decide(StrategyInput) → StrategyDecision`、`MarketAnalysisResult`、ポジション保護・注文管理・時刻規則は維持します。
注入した経路では旧ピーク・旧ライン候補を再計算しません。
明示的なテスト用candidate builder、未注入の公開互換窓口、ルートの互換モジュールは残します。

通常Intentへ変換するのは`execution="ready"`の候補だけです。
trial、待機、profit-lock/followup制約、predictionの失効制御、専用owner tagが必要な候補は自動発注しません。
原文が返す`line_control`イベントも`unsupported_controls`診断に保持します。
TP/SL、数量、期限、`lc_change`、監視設定等のmetadataを保持し、対応していない管理条件を落として発注しません。

有効化する戦略登録をmainからコピーすることはありません。
ダブルトップ、抵抗線ブレイク、flipの窓口が利用可能になっても、originalの取引には自動追加しません。
`fAnalysis_order_Main`、`fFlipWatch`は実行対象外です。
`fFlagInspection`、`fPredictTurn`は依存が欠落しており、復元・実行の対象外です。

## 同一プロセス内の分離

評価ごとに固有の完全修飾モジュール名を登録し、評価終了・例外終了時に解除します。
原文を変換せずcompile/execし、各モジュール専用のimport関数で原文同士を接続します。
ホストの短いimport名、`sys.path`、共通builtins、標準出力を置き換えません。
キャッシュ対象はコンパイル済みコードです。通貨・policy・計算キャッシュ・一時的な関数束縛は評価単位です。

価格取得は入力済みの値を返す互換部品、通知はセッション診断、print/redirect_stdoutは専用出力先へ接続します。
外部HTTP/OANDAクライアント作成は拒否します。これはレビュー済み原文を動かす互換境界です。
任意のPythonコードを隔離するための実行環境ではありません。

flipを呼ぶ場合は`MainSourceAnalysis(artifact_directory=...)`でディレクトリを指定します。
ファイル名と承認済みSHA-256は原文の`fFlipPredictPolicy`が検証します。
実運用アーティファクトは同梱しません。テストは専用名前空間内だけで合成policyを設定し、改変拒否を確認します。

## mainの更新を反映する

実行器を作るときに、対応するPythonファイルの原文をメモリに読み込みます。
実行中はその内容を使い続け、mainの編集は新しい実行器の作成時、通常はogamiOandaの再起動時に反映します。
コピー・同期・更新コマンドは不要です。読み込み途中で異なる版が混ざらないよう、mainの編集完了後に起動します。

読み込み対象は[source.py](../src/ogami_oanda/adapters/legacy/main_analysis/source.py)の対応モジュール一覧です。
main内の全ファイルを無差別にimportせず、`tokens`・通知等には互換部品を使います。
mainに`__pycache__`等を生成せず、Git管理されていないディレクトリからも読み込めます。

コードのバージョン固定やAPIハッシュによる更新判定は行いません。
未対応の依存・引数・返り値は実行時にエラーにし、必要な互換処理はogamiOanda側で対応します。
診断の`source_directory`とbacktestの`main_source_directory`には実際の参照先を記録します。
参照パスだけでは過去のコードの版を再現できないため、同じ結果の再現には同じmainの内容を用意します。
既存のbacktestデータ検証と、flipの原文によるアーティファクト検証は維持します。

## 検証

```sh
.venv/bin/python -m pytest -q tests/test_main_analysis_source.py tests/test_main_analysis_bridge.py --main-analysis-dir ../main
.venv/bin/python -m pytest -q -m "not integration"
.venv/bin/python -m ruff check src tests
.venv/bin/python -m ruff check src/ogami_oanda/adapters/legacy/main_analysis/*.py
python3 scripts/check_documentation.py
```

原文の直接呼び出しとのライン・ブレイクアウト・ダブルトップ比較、flipの検出窓口と待機注文作成、
3通貨の価格・数量・換算、境界時刻、入力不変、同時評価、例外後の再評価を検証します。
旧goldenは残した互換経路の比較です。新経路を旧goldenへ合わせるための期待値変更は行いません。

`test_main_analysis_source.py`は合成した小さなコードで、mainなしでも配置・不足ファイル・変更反映・
import分離・API不一致・CLIを検証します。実際の原文を使うテストは`--main-analysis-dir`で参照先を指定でき、
ディレクトリがない環境では理由を表示してそのテストだけをスキップします。

直接参照への変更時には、3通貨・21ケースの解析結果・候補・注文文脈が、同じ原文を使うコピー版と一致しました。
実API・実発注・実運用flipアーティファクトを用いた検証は実施していません。
