# 現行仕様

[索引](README.md) / [操作ガイド](usage.md) / [コード参照](reference/README.md)

この説明は現行実装とオフライン契約の仕様です。旧版との一致は外部APIの正しさや
実口座の運用受入完了を意味しません。詳細は [アーキテクチャ](architecture-migration.md) と
[差分検証](differential-verification.md) を参照してください。

## 市場データと計算

- 組込みライン戦略の対象はUSD/JPY、EUR/USD、AUD/USD。
- ローソク足は `time_jp/open/close/high/low` を必須列とするDataFrame。
  `time_jp` は `YYYY/MM/DD HH:MM:SS`、新しい足から古い足への順序、空データ不可。
- 指標・ピーク・ライン計算はdomainに配置。分析サービスが複数時間足を準備する。
- 価格精度・pips/価格差の換算は `CurrencyPair` が担当する。
- `MarketQuote` はbid/ask/midを保持し、同じtickのスプレッド・分析・状態同期で共有する。

根拠: [CandleFrameSchema](../src/ogami_oanda/domain/market/candle_frame.py)、
[CurrencyPair](../src/ogami_oanda/domain/market/currency_pair.py)、
[市場解析の契約テスト](../tests/test_contract_market_analysis_service.py)。

## 注文の契約

| 型・処理 | 意味 |
| --- | --- |
| `OrderIntent` | 方向、注文種別、目標、TP/SL、数量、優先度、期限、戦略メタデータという判断 |
| `OrderContext` | 判断時の価格・時刻等の入力文脈 |
| `OrderPlanner` | 価格/距離指定を解決してペア精度へ丸め、注文計画を作る |
| `OrderPlan` | 確定した価格とレンジ、元のintent/context、ブローカー中立要求 |
| `BrokerOrderRequest` | 外部業者のSDK型を含まない発注要求 |
| `submission_fingerprint` | 同じ判断を識別する注文参照値 |

OANDA adapterはMARKETをFOKかつトップレベルpriceなし、LIMIT/STOPをGTCかつpriceありに変換します。
発注応答はpending、filled、rejected、cancelled、terminal、unknownを区別します。
unknownを成功や未実行と決めつけて再発注しません。旧dictへの互換投影は別の契約です。

根拠: [注文型](../src/ogami_oanda/domain/orders/models.py)、
[OANDA変換](../src/ogami_oanda/adapters/oanda/mappers.py)、
[発注受入行列](../tests/test_contract_live_order_acceptance_matrix.py)。

## ポジションと復旧

`ManagedPosition` は計画・スナップショット・実行時状態を保持し、更新時に新しい値へ置換します。
`PositionService` はwatching、発注、約定、期限、SL変更、決済を扱います。
`PositionPortfolioService` は重複、優先度枠、連動/ヘッジ、複数ポジション、起動照合を担当します。
既定15枠は通常6・中優先度8・高優先度1です。

外部変更前に未確定操作を永続化し、確定遷移後にも状態を保存します。
JSONには注文計画、管理状態、取引カーソル、未確定操作、処理済み決済ID、集計、戦略状態を含みます。
保存は一時ファイル・fsync・置換・バックアップを使います。
起動時はトランザクションとpending/open状態を照合し、曖昧な対応、未解決操作、
ブローカーにポジションがあるのに保存状態がない/壊れている場合は隔離して新規解析と発注を止めます。

決済履歴はtrade IDで重複を抑え、CSVから累積集計を再構築します。
累積確定損益と現在の含み損益を区別します。

根拠: [復旧テスト](../tests/test_contract_position_recovery.py)、
[状態リポジトリテスト](../tests/test_contract_position_state_repository.py)、
[ポートフォリオサービス](../src/ogami_oanda/application/services/position_portfolio_service.py)。

## 組込みライン戦略の時刻規則

時計はJST。ループ間隔は1秒です。

| 条件 | 動作 |
| --- | --- |
| 日曜日 | 価格取得前に終了 |
| 土曜04:00以降、月曜07:59まで | 初回後は状態更新のみ |
| ペア別許容値を超えるスプレッド | 初回後は状態更新のみ |
| 初回 | 1回価格を取得して直ちに分析。更新専用時間/広スプレッドでも旧挙動を保持 |
| 2回目以降の分析 | 分が5の倍数、秒が6以上30未満、前回解析から60秒超 |
| 通常の偶数秒 | 状態同期。解析tickでは解析前の同期に加えて後段同期も行う |
| 更新専用tick | 毎tick状態同期 |

初回例外を一般的な売買ルールと読み替えないでください。これは保持している互換仕様です。
Matchaのプラグイン経路は別の評価経路で、開場tickごとに戦略を呼び出します。

根拠: [TradingSchedule](../src/ogami_oanda/application/scheduling.py)、
[時刻行列テスト](../tests/test_contract_live_schedule_matrix.py)。

## 戦略プラグインとMatcha

`TradingStrategy` は市場・保有状態を `StrategyInput` で受け、`StrategyDecision` を返します。
判断には注文intentと、戦略sourceに限定された `CANCEL_PENDING`、`REDUCE_EXPOSURE`、
`CLOSE_ALL` commandを含められます。JSON互換状態をdump/loadして再起動をまたぎます。

同梱MatchaはUSD/JPY専用です。設定ローダーが許可する固定ルートは
`AutoLot=false`, `Cancel=false`, `MaxPos=1`, `tp_sl_amount_mode=true`,
`tp_sl_close_intent_suppress=true`, `close_position=false`, `timescale=60`,
`minutes_to_expire=7` です。それ以外は起動時に拒否します。

| 設定群 | 意味 |
| --- | --- |
| `LotSize`, `MaxLotSize`, `MaxPos` | 注文数量と保有上限の計算 |
| `siguma_1`〜`siguma_4`, `pastPrice_len`, `std_len`, `dp`, `CTP`, `BreakOut` | 過去価格・標準偏差からの価格帯/シグナル判断 |
| `stop_latency`, `max_latency` | 価格情報の遅延しきい値（ミリ秒）。新規抑止や解消commandの判断 |
| `take_profit_amount`, `stop_loss_amount` | 金額モードのTP/SL計算入力 |
| `take_profit_distance`, `stop_loss_distance` | TP/SL距離の設定値 |
| `timescale`, `minutes_to_expire` | 対応時間尺度と注文の期限 |

YAMLにある全キーが汎用機能を有効化するわけではありません。
対応範囲は [MatchaConfig.from_mapping](../src/ogami_oanda/strategy/matcha_oanda.py) を正本とします。
戦略は新しい足の重複判定、価格鮮度、保有量、クールダウン等を考慮し、注文がない判断も正常です。
同梱設定は [matcha_param2019_oanda.yaml](../src/ogami_oanda/strategy/matcha_param2019_oanda.yaml)、
契約は [戦略テスト](../tests/test_matcha_strategy.py) を参照してください。

## 障害・副作用

既知の一時障害は上限付きバックオフを行います。401/403は認証停止に入り、
認証再検証・口座能力確認・保存状態との照合後、READYの復旧tickを経て次tickから再開します。
設定不整合や未知の例外は停止します。通知失敗は取引状態を巻き戻しません。

通常dry-runは発注系変更を抑止しますが、外部の読み取りやログ出力を伴います。
完全オフラインのCLI確認は `--offline-smoke --dry-run --once` です。
認証・注文・復旧の詳細は [アーキテクチャ](architecture-migration.md) を参照してください。

## バックテストの範囲

現行 `BacktestSimulator.evaluate_exit()` は1本の高値/安値からTP/SL到達を評価し、
両方に到達した足ではSLを優先します。旧 `classInspection.py` の実験環境全体を
置き換える汎用バックテストCLIは現行 `backtest/` には実装されていません。
根拠: [バックテスト契約](../tests/test_contract_backtest_simulator.py)。
