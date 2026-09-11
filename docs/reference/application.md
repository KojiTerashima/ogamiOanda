# application コード参照

[コード参照の入口](README.md) / [構成](../structure.md)

## `application/__init__.py`

[ソース](../../src/ogami_oanda/application/__init__.py)

パッケージの入口。初期化時に業務処理を開始しない。

## `application/errors.py`

[ソース](../../src/ogami_oanda/application/errors.py)

認証失敗と一時外部障害を、サービス層で扱える例外として定義する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`ExternalServiceAuthorizationError`](../../src/ogami_oanda/application/errors.py#L4) | class | Sanitized authorization failure from an external service. |
| [`ExternalServiceAuthorizationError.__init__`](../../src/ogami_oanda/application/errors.py#L7) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`TransientExternalServiceError`](../../src/ogami_oanda/application/errors.py#L20) | class | 認証失敗と一時外部障害を、サービス層で扱える例外として定義する。 この境界の失敗を呼び出し側へ伝える例外。 |
| [`TransientExternalServiceError.__init__`](../../src/ogami_oanda/application/errors.py#L21) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |

## `application/ports/__init__.py`

[ソース](../../src/ogami_oanda/application/ports/__init__.py)

パッケージの入口。関連型を再公開する。

## `application/ports/active_orders.py`

[ソース](../../src/ogami_oanda/application/ports/active_orders.py)

類似する有効注文の有無を照会する契約。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`ActiveOrderQuery`](../../src/ogami_oanda/application/ports/active_orders.py#L7) | class | 類似する有効注文の有無を照会する契約。 この責任を提供するクラス。 |
| [`ActiveOrderQuery.has_similar_active_order`](../../src/ogami_oanda/application/ports/active_orders.py#L8) | method | 比較条件に合う類似有効注文が存在するか判定する。 |

## `application/ports/broker.py`

[ソース](../../src/ogami_oanda/application/ports/broker.py)

発注・変更結果、口座能力、取引履歴、ブローカー操作/照会の契約。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`MutationState`](../../src/ogami_oanda/application/ports/broker.py#L12) | class | 外部変更操作の成功・拒否・不明などの状態区分。 |
| [`ExecutionResult`](../../src/ogami_oanda/application/ports/broker.py#L19) | class | 外部変更操作の状態・識別子・理由を保持する結果。 |
| [`ExecutionResult.__post_init__`](../../src/ogami_oanda/application/ports/broker.py#L25) | method | 生成直後に入力の整合性確認や不変形式への変換を行う。 |
| [`OrderSubmissionState`](../../src/ogami_oanda/application/ports/broker.py#L31) | class | 注文作成応答のpending/fill/拒否/取消/不明/終了の区分。 |
| [`OrderSubmissionResult`](../../src/ogami_oanda/application/ports/broker.py#L41) | class | 注文作成の確定度と注文/取引の対応を保持する結果。 |
| [`OrderSubmissionResult.accepted`](../../src/ogami_oanda/application/ports/broker.py#L51) | method | 発注結果が受理済み状態かを返す。 |
| [`OrderSubmissionResult.reference_id`](../../src/ogami_oanda/application/ports/broker.py#L55) | method | 結果を追跡する注文/取引識別子を返す。 |
| [`OrderSubmissionResult.message`](../../src/ogami_oanda/application/ports/broker.py#L59) | method | 発注結果の説明を返す。 |
| [`OrderSubmissionResult.pending`](../../src/ogami_oanda/application/ports/broker.py#L63) | method | 未約定状態を表す値を作る。 |
| [`OrderSubmissionResult.filled`](../../src/ogami_oanda/application/ports/broker.py#L67) | method | 約定済み状態を表す値を作る。 |
| [`OrderSubmissionResult.rejected`](../../src/ogami_oanda/application/ports/broker.py#L82) | method | 拒否された状態を表す値を作る。 |
| [`OrderSubmissionResult.cancelled`](../../src/ogami_oanda/application/ports/broker.py#L86) | method | 取り消された状態を表す値を作る。 |
| [`OrderSubmissionResult.unknown`](../../src/ogami_oanda/application/ports/broker.py#L95) | method | 実行結果が未確定の発注結果を作る。 |
| [`OrderSubmissionResult.terminal`](../../src/ogami_oanda/application/ports/broker.py#L108) | method | 新しい管理対象取引を残さず終了した発注結果を作る。 |
| [`BrokerExecutionPort`](../../src/ogami_oanda/application/ports/broker.py#L124) | class | 発注・取消・決済・保護変更を提供する契約。 |
| [`BrokerExecutionPort.submit`](../../src/ogami_oanda/application/ports/broker.py#L125) | method | 注文要求をブローカーへ送り、状態別の発注結果を返す。 |
| [`BrokerExecutionPort.cancel_order`](../../src/ogami_oanda/application/ports/broker.py#L127) | method | 指定注文を取り消し、結果を返す。 |
| [`BrokerExecutionPort.close_trade`](../../src/ogami_oanda/application/ports/broker.py#L129) | method | 指定取引を決済し、結果を返す。 |
| [`BrokerExecutionPort.amend_protection`](../../src/ogami_oanda/application/ports/broker.py#L131) | method | 取引のTP/SL保護を変更し、結果を返す。 |
| [`AccountCapabilities`](../../src/ogami_oanda/application/ports/broker.py#L135) | class | 口座識別と必要能力の照合結果。 |
| [`BrokerTradeClosure`](../../src/ogami_oanda/application/ports/broker.py#L142) | class | 終了取引の価格・数量・損益等を表す値。 |
| [`BrokerTransaction`](../../src/ogami_oanda/application/ports/broker.py#L152) | class | 1つのブローカートランザクションの値。 |
| [`BrokerTransactionBatch`](../../src/ogami_oanda/application/ports/broker.py#L167) | class | カーソル付きの取引履歴取得結果。 |
| [`InstrumentTradingRules`](../../src/ogami_oanda/application/ports/broker.py#L173) | class | ペアごとの最小注文数量・価格精度等の制約。 |
| [`BrokerQueryPort`](../../src/ogami_oanda/application/ports/broker.py#L181) | class | 口座・履歴・取引条件・注文/保有照会を提供する契約。 |
| [`BrokerQueryPort.account_capabilities`](../../src/ogami_oanda/application/ports/broker.py#L182) | method | 口座の識別とヘッジ能力を照会する。 |
| [`BrokerQueryPort.transactions_since`](../../src/ogami_oanda/application/ports/broker.py#L184) | method | 保存カーソル以降の取引トランザクションを取得する。 |
| [`BrokerQueryPort.instrument_rules`](../../src/ogami_oanda/application/ports/broker.py#L186) | method | ペアの最小数量・精度等の取引ルールを取得する。 |
| [`BrokerQueryPort.position`](../../src/ogami_oanda/application/ports/broker.py#L188) | method | 注文ID・取引IDに対応するポジション状態を取得する。 |
| [`BrokerQueryPort.order`](../../src/ogami_oanda/application/ports/broker.py#L190) | method | 指定注文の状態を取得する。 |
| [`BrokerQueryPort.trade`](../../src/ogami_oanda/application/ports/broker.py#L192) | method | 指定取引の状態を取得する。 |
| [`BrokerQueryPort.pending_orders`](../../src/ogami_oanda/application/ports/broker.py#L194) | method | 未約定注文の一覧を取得する。 |
| [`BrokerQueryPort.open_positions`](../../src/ogami_oanda/application/ports/broker.py#L196) | method | 保有中ポジションの一覧を取得する。 |

## `application/ports/clock.py`

[ソース](../../src/ogami_oanda/application/ports/clock.py)

業務処理に現在時刻を供給する契約。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`Clock`](../../src/ogami_oanda/application/ports/clock.py#L8) | class | 業務処理に現在時刻を供給する契約。 この責任を提供するクラス。 |
| [`Clock.now`](../../src/ogami_oanda/application/ports/clock.py#L9) | method | 現在時刻を返す。 |

## `application/ports/market_data.py`

[ソース](../../src/ogami_oanda/application/ports/market_data.py)

共有quoteとローソク足・価格取得の契約。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`MarketQuote`](../../src/ogami_oanda/application/ports/market_data.py#L11) | class | One pricing tick shared by analysis and position management. |
| [`MarketQuote.spread`](../../src/ogami_oanda/application/ports/market_data.py#L22) | method | askとbidの差を返す。 |
| [`MarketDataPort`](../../src/ogami_oanda/application/ports/market_data.py#L27) | class | 共有quoteとローソク足・価格取得の契約。 この責任を提供するクラス。 |
| [`MarketDataPort.candles`](../../src/ogami_oanda/application/ports/market_data.py#L28) | method | 指定ペア・時間足・本数のローソク足を取得する。 |
| [`MarketDataPort.current_price`](../../src/ogami_oanda/application/ports/market_data.py#L30) | method | 現在の代表価格を取得する。 |
| [`MarketDataPort.current_quote`](../../src/ogami_oanda/application/ports/market_data.py#L32) | method | 同一tickで共有するquoteを取得する。 |

## `application/ports/notifications.py`

[ソース](../../src/ogami_oanda/application/ports/notifications.py)

通知配送の契約。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`Notifier`](../../src/ogami_oanda/application/ports/notifications.py#L7) | class | 通知配送の契約。 この責任を提供するクラス。 |
| [`Notifier.send`](../../src/ogami_oanda/application/ports/notifications.py#L8) | method | 通知を配送する。 |

## `application/ports/position_state.py`

[ソース](../../src/ogami_oanda/application/ports/position_state.py)

永続状態・未確定操作・集計・戦略状態の型と保存時の検証/無害化。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`CheckpointLoadStatus`](../../src/ogami_oanda/application/ports/position_state.py#L17) | class | チェックポイントの読込成功・欠落・破損等の区分。 |
| [`PendingBrokerMutation`](../../src/ogami_oanda/application/ports/position_state.py#L28) | class | 結果が確定するまで保存する外部操作の記録。 |
| [`PendingBrokerMutation.requested_units`](../../src/ogami_oanda/application/ports/position_state.py#L45) | method | 操作で要求した数量を返す。 |
| [`PendingBrokerMutation.original_units`](../../src/ogami_oanda/application/ports/position_state.py#L51) | method | 操作前の数量を返す。 |
| [`PortfolioAnalyticsState`](../../src/ogami_oanda/application/ports/position_state.py#L56) | class | 永続化する累積損益・集計の状態。 |
| [`PositionStateCheckpoint`](../../src/ogami_oanda/application/ports/position_state.py#L81) | class | 口座/ペアに対応するポジション・未確定操作・戦略状態の保存単位。 |
| [`PositionStateCheckpoint.__post_init__`](../../src/ogami_oanda/application/ports/position_state.py#L93) | method | 生成直後に入力の整合性確認や不変形式への変換を行う。 |
| [`CheckpointLoadResult`](../../src/ogami_oanda/application/ports/position_state.py#L112) | class | 保存状態と読込状態を組み合わせた結果。 |
| [`PositionStateRepository`](../../src/ogami_oanda/application/ports/position_state.py#L119) | class | チェックポイント保存・復元の契約。 |
| [`PositionStateRepository.save`](../../src/ogami_oanda/application/ports/position_state.py#L120) | method | チェックポイントを保存する。 |
| [`PositionStateRepository.load`](../../src/ogami_oanda/application/ports/position_state.py#L122) | method | チェックポイントを読み取り、読込状態とともに返す。 |
| [`account_identity_hash`](../../src/ogami_oanda/application/ports/position_state.py#L130) | function | 口座の生の識別子を状態キーへ直接残さないためのハッシュを作る。 |
| [`validated_strategy_state`](../../src/ogami_oanda/application/ports/position_state.py#L134) | function | Copy and validate a strategy state mapping as recursively JSON values. |
| [`_validated_strategy_value`](../../src/ogami_oanda/application/ports/position_state.py#L145) | function / internal | 戦略状態の入れ子値をJSON互換性に沿って検証する。 |
| [`persisted_metadata`](../../src/ogami_oanda/application/ports/position_state.py#L197) | function | 永続化対象のメタデータをJSON互換の安全な項目へ絞る。 |
| [`_sanitized_position`](../../src/ogami_oanda/application/ports/position_state.py#L206) | function / internal | 永続化するポジション情報を安全な項目へ正規化する。 |
| [`_Unsupported`](../../src/ogami_oanda/application/ports/position_state.py#L236) | class / internal | JSONへ保存できない値を示す内部センチネル。 |
| [`_json_compatible_value`](../../src/ogami_oanda/application/ports/position_state.py#L243) | function / internal | 保存可能なJSON互換値へ変換する。 |

## `application/ports/trade_history.py`

[ソース](../../src/ogami_oanda/application/ports/trade_history.py)

決済履歴の保存・重複抑止・読込の契約。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`TradeHistoryRepository`](../../src/ogami_oanda/application/ports/trade_history.py#L7) | class | 決済履歴の保存・重複抑止・読込の契約。 この責任を提供するクラス。 |
| [`TradeHistoryRepository.append`](../../src/ogami_oanda/application/ports/trade_history.py#L8) | method | 決済履歴を追加する。 |
| [`TradeHistoryRepository.append_once`](../../src/ogami_oanda/application/ports/trade_history.py#L10) | method | 同じtrade IDを重複登録しないよう履歴を追加する。 |
| [`TradeHistoryRepository.read_all`](../../src/ogami_oanda/application/ports/trade_history.py#L17) | method | 保存済み決済履歴を読み取る。 |

## `application/scheduling.py`

[ソース](../../src/ogami_oanda/application/scheduling.py)

JSTの曜日・時間窓・解析間隔・状態同期間隔を判定する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`TradingSchedule`](../../src/ogami_oanda/application/scheduling.py#L8) | class | JSTの曜日・時間窓・解析間隔・状態同期間隔を判定する。 この責任を提供するクラス。 |
| [`TradingSchedule.is_market_closed`](../../src/ogami_oanda/application/scheduling.py#L15) | method | 日曜の市場休止を判定する。 |
| [`TradingSchedule.is_update_only_window`](../../src/ogami_oanda/application/scheduling.py#L19) | method | 週末移行時間帯の更新専用条件を判定する。 |
| [`TradingSchedule.should_run_analysis`](../../src/ogami_oanda/application/scheduling.py#L29) | method | 解析時刻窓・経過時間・更新専用フラグから解析可否を判定する。 |
| [`TradingSchedule.should_run_position_update`](../../src/ogami_oanda/application/scheduling.py#L37) | method | ポジション同期を行う秒か判定する。 |

## `application/services/__init__.py`

[ソース](../../src/ogami_oanda/application/services/__init__.py)

パッケージの入口。関連型を再公開する。

## `application/services/backtest_simulator.py`

[ソース](../../src/ogami_oanda/application/services/backtest_simulator.py)

1本の足に対するTP/SL到達を判定する。両方到達時はSL優先。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`ExitReason`](../../src/ogami_oanda/application/services/backtest_simulator.py#L9) | class | バックテストのTP/SL終了理由。 |
| [`PriceCandle`](../../src/ogami_oanda/application/services/backtest_simulator.py#L15) | class | 決済判定に必要な高値・安値・終値。 |
| [`SimulatedExit`](../../src/ogami_oanda/application/services/backtest_simulator.py#L22) | class | 足内で成立した決済理由と価格。 |
| [`BacktestSimulator`](../../src/ogami_oanda/application/services/backtest_simulator.py#L27) | class | 1本の足に対するTP/SL到達を判定する。両方到達時はSL優先。 この責任を提供するクラス。 |
| [`BacktestSimulator.evaluate_exit`](../../src/ogami_oanda/application/services/backtest_simulator.py#L28) | method | 1本の足でTP/SL到達を判定し、同時到達時はSLを優先する。 |

## `application/services/closure_reporting_service.py`

[ソース](../../src/ogami_oanda/application/services/closure_reporting_service.py)

決済イベントを一度だけ履歴・集計・通知へ反映する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`ClosureReportingService`](../../src/ogami_oanda/application/services/closure_reporting_service.py#L49) | class | 決済イベントを一度だけ履歴・集計・通知へ反映する。 この責任を提供するクラス。 |
| [`ClosureReportingService.__init__`](../../src/ogami_oanda/application/services/closure_reporting_service.py#L50) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`ClosureReportingService.report`](../../src/ogami_oanda/application/services/closure_reporting_service.py#L63) | method | 決済を履歴・集計・通知へ反映する。 |
| [`ClosureReportingService._restore_from_history`](../../src/ogami_oanda/application/services/closure_reporting_service.py#L90) | method / internal | 既存の決済履歴から集計・処理済み状態を復元する。 |
| [`ClosureReportingService._lc_change_count`](../../src/ogami_oanda/application/services/closure_reporting_service.py#L115) | method / internal | SL変更回数を取得する。 |
| [`ClosureReportingService._legacy_record`](../../src/ogami_oanda/application/services/closure_reporting_service.py#L122) | method / internal | 決済イベントを旧互換の履歴レコードへ変換する。 |
| [`ClosureReportingService._excursion_pips`](../../src/ogami_oanda/application/services/closure_reporting_service.py#L216) | method / internal | 保有中の最大順行/逆行をpipsへ換算する。 |

## `application/services/line_candidate_context_builder.py`

[ソース](../../src/ogami_oanda/application/services/line_candidate_context_builder.py)

足・ピーク・ラインから、純粋なライン戦略に渡す解析文脈を構築する。

定義の正本は[originalの解析文脈](../../src/ogami_oanda/strategy/original/context.py)です。

## `application/services/market_analysis_service.py`

[ソース](../../src/ogami_oanda/application/services/market_analysis_service.py)

市場データと指標を準備し、選択候補をOrderIntentへ変換する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`MarketAnalysisService`](../../src/ogami_oanda/application/services/market_analysis_service.py#L17) | class | 市場データと指標を準備し、選択候補をOrderIntentへ変換する。 この責任を提供するクラス。 |
| [`MarketAnalysisService.__init__`](../../src/ogami_oanda/application/services/market_analysis_service.py#L18) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`MarketAnalysisService.analyze`](../../src/ogami_oanda/application/services/market_analysis_service.py#L42) | method | 足を準備して戦略候補を解析し、注文intentと診断結果を返す。 |
| [`MarketAnalysisService._prepared_frame`](../../src/ogami_oanda/application/services/market_analysis_service.py#L57) | method / internal | 市場足を検証し、指標を付けて解析へ渡す。 |

## `application/services/order_planner.py`

[ソース](../../src/ogami_oanda/application/services/order_planner.py)

intentの価格/距離を確定価格へ変換し、OrderPlanを構築する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`OrderPlanner`](../../src/ogami_oanda/application/services/order_planner.py#L14) | class | intentの価格/距離を確定価格へ変換し、OrderPlanを構築する。 この責任を提供するクラス。 |
| [`OrderPlanner.plan`](../../src/ogami_oanda/application/services/order_planner.py#L15) | method | 注文intentとcontextから価格が確定した計画を作る。 |
| [`OrderPlanner._target_price`](../../src/ogami_oanda/application/services/order_planner.py#L50) | method / internal | 目標の価格/距離指定を絶対価格へ解決する。 |
| [`OrderPlanner._protection_price`](../../src/ogami_oanda/application/services/order_planner.py#L60) | method / internal | TP/SLの価格/距離指定を絶対価格へ解決する。 |

## `application/services/portfolio.py`

[ソース](../../src/ogami_oanda/application/services/portfolio.py)

有効注文を保持し、source・価格等による類似注文を判定する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`ActiveOrder`](../../src/ogami_oanda/application/services/portfolio.py#L9) | class | 類似注文判定に使う有効注文の情報。 |
| [`Portfolio`](../../src/ogami_oanda/application/services/portfolio.py#L17) | class | 有効注文を保持し、source・価格等による類似注文を判定する。 この責任を提供するクラス。 |
| [`Portfolio.__init__`](../../src/ogami_oanda/application/services/portfolio.py#L18) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`Portfolio.has_similar_active_order`](../../src/ogami_oanda/application/services/portfolio.py#L22) | method | 比較条件に合う類似有効注文が存在するか判定する。 |

## `application/services/portfolio_analytics.py`

[ソース](../../src/ogami_oanda/application/services/portfolio_analytics.py)

決済損益を累積し、従来互換の最新・pivot・合計表示を作る。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`PortfolioAnalytics`](../../src/ogami_oanda/application/services/portfolio_analytics.py#L10) | class | Legacy-compatible, process-lifetime close-result aggregation. The initial values and the asymmetric minimum updates intentionally mirror ``classPosition.order_information``. In particular, the cumulative-yen and cumulative-price minima remain infinity after an initial winning trade; that is observable legacy behaviour, not a normalization target. |
| [`PortfolioAnalytics.apply`](../../src/ogami_oanda/application/services/portfolio_analytics.py#L41) | method | 決済結果を累積集計へ反映する。 |
| [`PortfolioAnalytics.result_summary`](../../src/ogami_oanda/application/services/portfolio_analytics.py#L95) | method | 累積の決済結果を従来互換の表示形式にする。 |
| [`PortfolioAnalytics.latest_summary`](../../src/ogami_oanda/application/services/portfolio_analytics.py#L113) | method | 最新の決済結果を表示形式にする。 |
| [`PortfolioAnalytics.pivot_summary`](../../src/ogami_oanda/application/services/portfolio_analytics.py#L123) | method | pivot別の決済結果を表示形式にする。 |
| [`publish_portfolio_analytics`](../../src/ogami_oanda/application/services/portfolio_analytics.py#L160) | function | Expose the src-owned aggregate to the root compatibility projection. |
| [`latest_portfolio_analytics`](../../src/ogami_oanda/application/services/portfolio_analytics.py#L166) | function | 共有された最新の集計を取得する。 |

## `application/services/position_portfolio_service.py`

[ソース](../../src/ogami_oanda/application/services/position_portfolio_service.py)

複数ポジションの枠・重複・連動・戦略command・永続化・再起動照合を統括する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`RegistrationResult`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L50) | class | 注文計画の採用・不採用・イベントをまとめた結果。 |
| [`StrategyCommandResult`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L56) | class | Application-level report for one source-scoped command batch. |
| [`StrategyCommandResult.allows_intents`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L64) | method | command処理結果に基づき後続intentの処理可否を返す。 |
| [`StrategyCommandResult.commands`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L68) | method | 処理した戦略commandを返す。 |
| [`PortfolioSummary`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L75) | class | 有効枠・注文/取引・確定/含み損益の表示用集約。 |
| [`PortfolioSummary.realized_total`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L88) | method | 累積確定損益を返す。 |
| [`PortfolioSummary.pips_total`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L94) | method | 累積確定pipsを返す。 |
| [`PortfolioSummary.current_unrealized_pl`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L98) | method | 現在の含み損益を返す。 |
| [`PositionStatePersistenceError`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L102) | class | 複数ポジションの枠・重複・連動・戦略command・永続化・再起動照合を統括する。 この境界の失敗を呼び出し側へ伝える例外。 |
| [`PortfolioStartupState`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L106) | class | 起動時照合のREADY・RECONCILING・QUARANTINED区分。 |
| [`_checkpoint_position_is_active`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L113) | function / internal | 保存ポジションが復旧対象の有効状態か判定する。 |
| [`PortfolioStartupResult`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L128) | class | 起動時照合の状態と停止理由を返す結果。 |
| [`PositionPortfolioService`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L134) | class | 複数ポジションの枠・重複・連動・戦略command・永続化・再起動照合を統括する。 この責任を提供するクラス。 |
| [`PositionPortfolioService.__init__`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L135) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`PositionPortfolioService.strategy_state`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L179) | method | 保持している戦略チェックポイント状態を返す。 |
| [`PositionPortfolioService.set_strategy_checkpoint_state`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L184) | method | 検証済みの戦略ID・状態をチェックポイントへ反映する。 |
| [`PositionPortfolioService.register_plans`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L194) | method | 計画を重複・枠・優先度に照らして登録し、採用/不採用を返す。 |
| [`PositionPortfolioService._registration_result`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L319) | method / internal | 採用/不採用とイベントを登録結果へまとめる。 |
| [`PositionPortfolioService.restore_and_reconcile`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L354) | method | 保存状態とブローカー履歴/現状を照合し、復旧可否を決める。 |
| [`PositionPortfolioService._resolve_stopped_terminal_position`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L600) | method / internal | 停止中に終了した取引を照合して管理状態を解決する。 |
| [`PositionPortfolioService._apply_closed_snapshot`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L650) | method / internal | 終了スナップショットを管理状態へ反映する。 |
| [`PositionPortfolioService._closed_snapshot_from_transactions`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L683) | method / internal | トランザクションから終了状態を再構成する。 |
| [`PositionPortfolioService._runtime_quarantine`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L724) | method / internal | 実行中の不確定状態を隔離状態にする。 |
| [`PositionPortfolioService._apply_runtime_closed_snapshot`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L734) | method / internal | 実行中の管理状態へ照合済み決済を反映する。 |
| [`PositionPortfolioService.reconcile_pending_mutations`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L769) | method | 未確定操作の実際の結果を照合する。 |
| [`PositionPortfolioService._promote_filled_pending_positions`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L809) | method / internal | 約定が確認できた未約定管理状態を保有状態へ進める。 |
| [`PositionPortfolioService._resolve_pending_mutations`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L844) | method / internal | 保存された未確定操作の結果を照合する。 |
| [`PositionPortfolioService._submit_prepared_positions`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L1024) | method / internal | 送信可能な準備済み注文を処理する。 |
| [`PositionPortfolioService._within_submission_window`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L1068) | method / internal | 準備済み注文が送信期限内か判定する。 |
| [`PositionPortfolioService._resolve_non_submit_mutation`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L1078) | method / internal | 取消・決済・保護変更の未確定結果を照合する。 |
| [`PositionPortfolioService._resolve_reduced_trade_mutation`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L1222) | method / internal | 数量削減操作の未確定結果を照合する。 |
| [`PositionPortfolioService._restore_analytics`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L1277) | method / internal | チェックポイントから累積集計を復元する。 |
| [`PositionPortfolioService._quarantine`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L1306) | method / internal | 起動時の曖昧な状態を隔離し、理由を返す。 |
| [`PositionPortfolioService._strategy_source`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L1311) | method / internal | 管理ポジションの戦略sourceを取り出す。 |
| [`PositionPortfolioService._position_direction`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L1315) | method / internal | 管理ポジションの売買方向を取り出す。 |
| [`PositionPortfolioService._filled_order_key`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L1322) | method / internal | 約定済み注文を対応づけるキーを作る。 |
| [`PositionPortfolioService._command_client_reference`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L1336) | method / internal | 戦略commandの外部操作識別子を作る。 |
| [`PositionPortfolioService.execute_strategy_commands`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L1340) | method | 指定sourceに属するポジションへ戦略commandを適用する。 |
| [`PositionPortfolioService._run_strategy_command`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L1372) | method / internal | 1つの戦略commandを対象ポジションへ適用する。 |
| [`PositionPortfolioService._run_strategy_action`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L1383) | method / internal | 戦略commandに対応する具体的な操作を実行する。 |
| [`PositionPortfolioService._begin_mutation`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L1563) | method / internal | 外部操作前の未確定ジャーナルを保存する。 |
| [`PositionPortfolioService._complete_mutation`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L1587) | method / internal | 確定した外部操作を状態へ反映・保存する。 |
| [`PositionPortfolioService._persist_state`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L1591) | method / internal | 現在のポートフォリオをチェックポイントとして保存する。 |
| [`PositionPortfolioService._checkpoint`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L1599) | method / internal | 管理状態からチェックポイント値を構築する。 |
| [`PositionPortfolioService.sync_all`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L1638) | method | 全管理ポジションを同期し、連動/ヘッジ判断も反映する。 |
| [`PositionPortfolioService.restore_open_positions`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L1770) | method | ブローカーの保有状態を用いた復元経路を提供する。 |
| [`PositionPortfolioService.cancel_pending_on_start`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L1782) | method | 起動時の未約定取消要求を処理する。 |
| [`PositionPortfolioService.summary`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L1825) | method | 現在の枠と損益の要約を返す。 |
| [`PositionPortfolioService._active_orders`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L1862) | method / internal | 重複比較に用いる有効注文を列挙する。 |
| [`PositionPortfolioService._is_duplicate`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L1877) | method / internal | 新しい計画が既存注文と重複するか判定する。 |
| [`PositionPortfolioService._first_empty_slot`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L1888) | method / internal | 指定優先度枠で最初の空き枠を探す。 |
| [`PositionPortfolioService._first_empty_global_slot`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L1903) | method / internal | 全体から最初の空き枠を探す。 |
| [`PositionPortfolioService._priority_tier`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L1917) | method / internal | 注文優先度を枠の区分へ対応づける。 |
| [`PositionPortfolioService._slot_range`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L1924) | method / internal | 優先度区分が使用する枠範囲を返す。 |
| [`PositionPortfolioService._available_slot_count`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L1931) | method / internal | 対象区分の空き枠数を返す。 |
| [`PositionPortfolioService._apply_linkage`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L1941) | method / internal | 主注文と連動ポジションの関係を評価・適用する。 |
| [`PositionPortfolioService._linked_positions`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L1993) | method / internal | 指定位置に連動するポジションを取り出す。 |
| [`PositionPortfolioService._execute_linkage_decision`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L2022) | method / internal | 連動判断を外部操作へ反映する。 |
| [`PositionPortfolioService._apply_hedge`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L2106) | method / internal | 反対方向のヘッジ管理判断を適用する。 |
| [`PositionPortfolioService._execute_mutation`](../../src/ogami_oanda/application/services/position_portfolio_service.py#L2154) | method / internal | 永続化フックを伴う外部変更操作を実行する。 |

## `application/services/position_service.py`

[ソース](../../src/ogami_oanda/application/services/position_service.py)

単一の管理ポジションの登録・発注・監視・同期・保護変更・決済を実行する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`PositionSyncResult`](../../src/ogami_oanda/application/services/position_service.py#L38) | class | 単一ポジションの同期後状態とイベント。 |
| [`CandleStopLossInput`](../../src/ogami_oanda/application/services/position_service.py#L46) | class | Completed-candle data used by the legacy candle stop-loss rule. |
| [`PositionService`](../../src/ogami_oanda/application/services/position_service.py#L53) | class | 単一の管理ポジションの登録・発注・監視・同期・保護変更・決済を実行する。 この責任を提供するクラス。 |
| [`PositionService.__init__`](../../src/ogami_oanda/application/services/position_service.py#L54) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`PositionService.set_mutation_hooks`](../../src/ogami_oanda/application/services/position_service.py#L81) | method | 外部操作前後の永続化フックを接続する。 |
| [`PositionService.set_event_sink`](../../src/ogami_oanda/application/services/position_service.py#L89) | method | 発生イベントを受け取る出力先を接続する。 |
| [`PositionService.register`](../../src/ogami_oanda/application/services/position_service.py#L94) | method | 計画を管理ポジションへ登録する。 |
| [`PositionService.prepare`](../../src/ogami_oanda/application/services/position_service.py#L100) | method | 外部送信前の管理状態を作る。 |
| [`PositionService.submit_prepared`](../../src/ogami_oanda/application/services/position_service.py#L107) | method | 準備済み注文を送信し、応答を管理状態へ反映する。 |
| [`PositionService.sync`](../../src/ogami_oanda/application/services/position_service.py#L142) | method | ブローカー状態と管理ポジションを同期する。 |
| [`PositionService.sync_result`](../../src/ogami_oanda/application/services/position_service.py#L145) | method | 同期後の状態とイベントをまとめて返す。 |
| [`PositionService.close`](../../src/ogami_oanda/application/services/position_service.py#L232) | method | 管理ポジションの終了操作を行う。 |
| [`PositionService._sync_watching`](../../src/ogami_oanda/application/services/position_service.py#L253) | method / internal | 発注前の価格監視状態を更新する。 |
| [`PositionService._apply_submission_result`](../../src/ogami_oanda/application/services/position_service.py#L331) | method / internal | 発注応答を管理ポジションの状態へ反映する。 |
| [`PositionService._pending_timeout`](../../src/ogami_oanda/application/services/position_service.py#L373) | method / internal | 未約定注文の期限を評価する。 |
| [`PositionService._trade_timeout`](../../src/ogami_oanda/application/services/position_service.py#L404) | method / internal | 保有取引の期限を評価する。 |
| [`PositionService._stop_loss_amendment`](../../src/ogami_oanda/application/services/position_service.py#L434) | method / internal | 現在状態と足から必要なSL変更を計算する。 |
| [`PositionService._start_mutation`](../../src/ogami_oanda/application/services/position_service.py#L540) | method / internal | 単一ポジションの外部操作開始をフックへ通知する。 |
| [`PositionService._event`](../../src/ogami_oanda/application/services/position_service.py#L569) | method / internal | 管理状態の変化をイベントとして構築する。 |
| [`PositionService._events_once`](../../src/ogami_oanda/application/services/position_service.py#L614) | method / internal | 処理済みイベントの再発行を抑える。 |
| [`PositionService._with_broker_runtime`](../../src/ogami_oanda/application/services/position_service.py#L624) | method / internal | ブローカー応答のruntime情報を管理状態へ反映する。 |

## `application/services/practice_order_acceptance_service.py`

[ソース](../../src/ogami_oanda/application/services/practice_order_acceptance_service.py)

明示許可されたpractice口座で最小注文の受入と所有資源の後処理を行う。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`PracticeAcceptanceError`](../../src/ogami_oanda/application/services/practice_order_acceptance_service.py#L26) | class | 明示許可されたpractice口座で最小注文の受入と所有資源の後処理を行う。 この境界の失敗を呼び出し側へ伝える例外。 |
| [`PracticeAcceptanceError.__init__`](../../src/ogami_oanda/application/services/practice_order_acceptance_service.py#L27) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`PracticeAcceptanceOperation`](../../src/ogami_oanda/application/services/practice_order_acceptance_service.py#L38) | class | practice受入の1操作と後処理状況の記録。 |
| [`PracticeAcceptanceReport`](../../src/ogami_oanda/application/services/practice_order_acceptance_service.py#L48) | class | practice受入の全操作と残存資源確認の結果。 |
| [`PracticeOrderAcceptanceService`](../../src/ogami_oanda/application/services/practice_order_acceptance_service.py#L53) | class | 明示許可されたpractice口座で最小注文の受入と所有資源の後処理を行う。 この責任を提供するクラス。 |
| [`PracticeOrderAcceptanceService.__init__`](../../src/ogami_oanda/application/services/practice_order_acceptance_service.py#L54) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`PracticeOrderAcceptanceService.run`](../../src/ogami_oanda/application/services/practice_order_acceptance_service.py#L85) | method | 3ペアの最小LIMIT/STOP作成取消・MARKET開閉を実施し、所有資源の残存を確認する。 |
| [`PracticeOrderAcceptanceService.run_strategy`](../../src/ogami_oanda/application/services/practice_order_acceptance_service.py#L313) | method | 戦略を評価してpractice受入を行う。 |
| [`PracticeOrderAcceptanceService.run_strategy_intents`](../../src/ogami_oanda/application/services/practice_order_acceptance_service.py#L391) | method | 受入可能な戦略intentを最小数量で検証し後処理する。 |
| [`PracticeOrderAcceptanceService._validate_account_and_clean_baseline`](../../src/ogami_oanda/application/services/practice_order_acceptance_service.py#L475) | method / internal | practice口座の条件と実行前の注文/保有状態を確認する。 |
| [`PracticeOrderAcceptanceService._preflight_pairs`](../../src/ogami_oanda/application/services/practice_order_acceptance_service.py#L499) | method / internal | 受入対象ペアの取引条件を先に確認する。 |
| [`PracticeOrderAcceptanceService._request`](../../src/ogami_oanda/application/services/practice_order_acceptance_service.py#L526) | method / internal | 受入用の最小数量注文要求を作る。 |
| [`PracticeOrderAcceptanceService._cancel_order`](../../src/ogami_oanda/application/services/practice_order_acceptance_service.py#L565) | method / internal | 受入で所有する注文を取り消す。 |
| [`PracticeOrderAcceptanceService._cancel_or_find_trade`](../../src/ogami_oanda/application/services/practice_order_acceptance_service.py#L579) | method / internal | 注文を取り消すか、既に約定した取引を追跡する。 |
| [`PracticeOrderAcceptanceService._close_trade`](../../src/ogami_oanda/application/services/practice_order_acceptance_service.py#L587) | method / internal | 受入で所有する取引を決済する。 |
| [`PracticeOrderAcceptanceService._cleanup_owned`](../../src/ogami_oanda/application/services/practice_order_acceptance_service.py#L602) | method / internal | 受入が作った注文/取引を後処理する。 |
| [`PracticeOrderAcceptanceService._pending_ids`](../../src/ogami_oanda/application/services/practice_order_acceptance_service.py#L644) | method / internal | 現在の未約定注文IDを取得する。 |
| [`PracticeOrderAcceptanceService._open_trade_ids`](../../src/ogami_oanda/application/services/practice_order_acceptance_service.py#L651) | method / internal | 現在の保有取引IDを取得する。 |
| [`PracticeOrderAcceptanceService._owned_resources`](../../src/ogami_oanda/application/services/practice_order_acceptance_service.py#L658) | method / internal | 受入が所有する注文/取引を特定する。 |
| [`PracticeOrderAcceptanceService._reconcile_attempted_resources`](../../src/ogami_oanda/application/services/practice_order_acceptance_service.py#L689) | method / internal | 試行した操作の結果と所有資源を照合する。 |
| [`PracticeOrderAcceptanceService._refresh_operation_cleanup`](../../src/ogami_oanda/application/services/practice_order_acceptance_service.py#L735) | method / internal | 各操作の後処理完了状態を更新する。 |
| [`PracticeOrderAcceptanceService._poll_owned_resources`](../../src/ogami_oanda/application/services/practice_order_acceptance_service.py#L755) | method / internal | 所有資源の状態が確認できるまで照会する。 |
| [`PracticeOrderAcceptanceService._poll_order_cleanup`](../../src/ogami_oanda/application/services/practice_order_acceptance_service.py#L773) | method / internal | 注文の後処理完了を照会する。 |
| [`PracticeOrderAcceptanceService._order_cleanup_state`](../../src/ogami_oanda/application/services/practice_order_acceptance_service.py#L785) | method / internal | 注文の終了/残存状態を判定する。 |
| [`PracticeOrderAcceptanceService._trade_cleanup_confirmed`](../../src/ogami_oanda/application/services/practice_order_acceptance_service.py#L798) | method / internal | 取引の終了が確認済みか判定する。 |
| [`PracticeOrderAcceptanceService._poll`](../../src/ogami_oanda/application/services/practice_order_acceptance_service.py#L805) | method / internal | 制限回数内で確認処理を繰り返す。 |

## `application/services/runtime_event_buffer.py`

[ソース](../../src/ogami_oanda/application/services/runtime_event_buffer.py)

サービスで発生したイベントを次のtick表示へ渡す一時バッファ。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`RuntimeEventBuffer`](../../src/ogami_oanda/application/services/runtime_event_buffer.py#L8) | class | Small in-process bridge from domain services to a live observer. The buffer is intentionally transient: event IDs are persisted by the position service, while this queue only carries events produced since the previous completed polling tick. |
| [`RuntimeEventBuffer.__init__`](../../src/ogami_oanda/application/services/runtime_event_buffer.py#L16) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`RuntimeEventBuffer.publish`](../../src/ogami_oanda/application/services/runtime_event_buffer.py#L19) | method | tick表示へ渡すイベントをバッファに追加する。 |
| [`RuntimeEventBuffer.drain`](../../src/ogami_oanda/application/services/runtime_event_buffer.py#L22) | method | 蓄積イベントを取り出してバッファを空にする。 |

## `application/settings.py`

[ソース](../../src/ogami_oanda/application/settings.py)

戦略・注文枠が参照する業務設定の既定値を定義する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`TradingSettings`](../../src/ogami_oanda/application/settings.py#L7) | class | Business limits consumed by trading application services. |

## `application/ports/historical_data.py`

[ソース](../../src/ogami_oanda/application/ports/historical_data.py)

履歴の期間取得と保存・検証を切り離すポート契約。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`HistoricalSource`](../../src/ogami_oanda/application/ports/historical_data.py#L9) | class | 履歴の期間取得と保存・検証を切り離すポート契約。 |
| [`HistoricalSource.fetch`](../../src/ogami_oanda/application/ports/historical_data.py#L10) | method | 履歴の期間取得と保存・検証を切り離すポート契約。 |
| [`HistoricalRepository`](../../src/ogami_oanda/application/ports/historical_data.py#L13) | class | 履歴の期間取得と保存・検証を切り離すポート契約。 |
| [`HistoricalRepository.missing_intervals`](../../src/ogami_oanda/application/ports/historical_data.py#L16) | method | 履歴の期間取得と保存・検証を切り離すポート契約。 |
| [`HistoricalRepository.covers`](../../src/ogami_oanda/application/ports/historical_data.py#L18) | method | 履歴の期間取得と保存・検証を切り離すポート契約。 |
| [`HistoricalRepository.validate`](../../src/ogami_oanda/application/ports/historical_data.py#L20) | method | 履歴の期間取得と保存・検証を切り離すポート契約。 |
| [`HistoricalRepository.write_interval`](../../src/ogami_oanda/application/ports/historical_data.py#L22) | method | 履歴の期間取得と保存・検証を切り離すポート契約。 |
| [`HistoricalRepository.read`](../../src/ogami_oanda/application/ports/historical_data.py#L24) | method | 履歴の期間取得と保存・検証を切り離すポート契約。 |

## `application/services/historical_market.py`

[ソース](../../src/ogami_oanda/application/services/historical_market.py)

UTCのS5から観測済み価格だけでローリング足を生成し、JST再生時計を提供する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`ReplayClock`](../../src/ogami_oanda/application/services/historical_market.py#L19) | class | UTCのS5から観測済み価格だけでローリング足を生成し、JST再生時計を提供する。 |
| [`ReplayClock.__init__`](../../src/ogami_oanda/application/services/historical_market.py#L20) | method | 依存・設定を受け取り初期状態を構築する。 |
| [`ReplayClock.set`](../../src/ogami_oanda/application/services/historical_market.py#L23) | method | UTCのS5から観測済み価格だけでローリング足を生成し、JST再生時計を提供する。 |
| [`ReplayClock.now`](../../src/ogami_oanda/application/services/historical_market.py#L28) | method | UTCのS5から観測済み価格だけでローリング足を生成し、JST再生時計を提供する。 |
| [`HistoricalMarket`](../../src/ogami_oanda/application/services/historical_market.py#L32) | class | UTCのS5から観測済み価格だけでローリング足を生成し、JST再生時計を提供する。 |
| [`HistoricalMarket.__init__`](../../src/ogami_oanda/application/services/historical_market.py#L33) | method | 依存・設定を受け取り初期状態を構築する。 |
| [`HistoricalMarket.advance`](../../src/ogami_oanda/application/services/historical_market.py#L49) | method | 次の観測済みS5を適用する。 |
| [`HistoricalMarket.record_gap`](../../src/ogami_oanda/application/services/historical_market.py#L83) | method | 観測のない区間を集計し、設定された出力先へ渡す。 |
| [`HistoricalMarket._record`](../../src/ogami_oanda/application/services/historical_market.py#L90) | method | UTCのS5から観測済み価格だけでローリング足を生成し、JST再生時計を提供する。 |
| [`HistoricalMarket.ready`](../../src/ogami_oanda/application/services/historical_market.py#L98) | method | 必要な足窓と価格の観測状態を確認する。 |
| [`HistoricalMarket.buffered_candles`](../../src/ogami_oanda/application/services/historical_market.py#L102) | method | UTCのS5から観測済み価格だけでローリング足を生成し、JST再生時計を提供する。 |
| [`HistoricalMarket.candles`](../../src/ogami_oanda/application/services/historical_market.py#L105) | method | UTCのS5から観測済み価格だけでローリング足を生成し、JST再生時計を提供する。 |
| [`HistoricalMarket.current_quote`](../../src/ogami_oanda/application/services/historical_market.py#L142) | method | UTCのS5から観測済み価格だけでローリング足を生成し、JST再生時計を提供する。 |
| [`HistoricalMarket.current_price`](../../src/ogami_oanda/application/services/historical_market.py#L148) | method | UTCのS5から観測済み価格だけでローリング足を生成し、JST再生時計を提供する。 |

## `application/services/history_download.py`

[ソース](../../src/ogami_oanda/application/services/history_download.py)

未取得区間を6時間・UTC日境界で分割し、上限付き再試行で保存する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`download_history`](../../src/ogami_oanda/application/services/history_download.py#L11) | function | 未取得区間を6時間・UTC日境界で分割し、上限付き再試行で保存する。 |
