# adapters コード参照

[コード参照の入口](README.md) / [構成](../structure.md)

## `adapters/__init__.py`

[ソース](../../src/ogami_oanda/adapters/__init__.py)

パッケージの入口。初期化時に業務処理を開始しない。

## `adapters/legacy/__init__.py`

[ソース](../../src/ogami_oanda/adapters/legacy/__init__.py)

パッケージの入口。関連型を再公開する。

## `adapters/legacy/candle_analysis.py`

[ソース](../../src/ogami_oanda/adapters/legacy/candle_analysis.py)

旧ローソク足分析オブジェクトをMarketDataPortへ適合させる。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`LegacyCandleAnalysisMarketData`](../../src/ogami_oanda/adapters/legacy/candle_analysis.py#L8) | class | Expose a legacy candle-analysis instance through MarketDataPort. |
| [`LegacyCandleAnalysisMarketData.__init__`](../../src/ogami_oanda/adapters/legacy/candle_analysis.py#L11) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`LegacyCandleAnalysisMarketData.candles`](../../src/ogami_oanda/adapters/legacy/candle_analysis.py#L22) | method | 指定ペア・時間足・本数のローソク足を取得する。 |
| [`LegacyCandleAnalysisMarketData.current_price`](../../src/ogami_oanda/adapters/legacy/candle_analysis.py#L27) | method | 現在の代表価格を取得する。 |

## `adapters/legacy/order_dict.py`

[ソース](../../src/ogami_oanda/adapters/legacy/order_dict.py)

旧注文dict・注文オブジェクトとOrderPlanを相互変換し、連動関係も保持する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`LegacyOrderView`](../../src/ogami_oanda/adapters/legacy/order_dict.py#L18) | class | Compatibility view consumed by the root Position registration API. |
| [`LegacyOrderView.__init__`](../../src/ogami_oanda/adapters/legacy/order_dict.py#L21) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`_legacy_bool`](../../src/ogami_oanda/adapters/legacy/order_dict.py#L31) | function / internal | 旧データのbool表現を正規化する。 |
| [`_order_name`](../../src/ogami_oanda/adapters/legacy/order_dict.py#L43) | function / internal | 旧注文から識別名を取り出す。 |
| [`_order_names`](../../src/ogami_oanda/adapters/legacy/order_dict.py#L58) | function / internal | 旧注文群から識別名を取り出す。 |
| [`_legacy_linkage`](../../src/ogami_oanda/adapters/legacy/order_dict.py#L74) | function / internal | 旧注文の連動情報を取り出す。 |
| [`_derived_linkage_id`](../../src/ogami_oanda/adapters/legacy/order_dict.py#L96) | function / internal | 関連注文を結ぶ連動識別子を導く。 |
| [`legacy_orders_to_order_plans`](../../src/ogami_oanda/adapters/legacy/order_dict.py#L102) | function | Convert a legacy order batch without losing object linkage relationships. |
| [`legacy_dict_to_order_plan`](../../src/ogami_oanda/adapters/legacy/order_dict.py#L172) | function | 旧注文dictから型付き注文計画を作る。 |
| [`order_plan_to_legacy_dict`](../../src/ogami_oanda/adapters/legacy/order_dict.py#L260) | function | 型付き注文計画を旧注文dictへ投影する。 |

## `adapters/legacy/position_dict.py`

[ソース](../../src/ogami_oanda/adapters/legacy/position_dict.py)

旧ポジションdictと型付きPositionSnapshotを相互変換する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`_order_state`](../../src/ogami_oanda/adapters/legacy/position_dict.py#L6) | function / internal | 旧注文状態をOrderStateへ変換する。 |
| [`_trade_state`](../../src/ogami_oanda/adapters/legacy/position_dict.py#L18) | function / internal | 旧取引状態をTradeStateへ変換する。 |
| [`legacy_position_to_snapshot`](../../src/ogami_oanda/adapters/legacy/position_dict.py#L25) | function | 旧ポジションdictからスナップショットを作る。 |
| [`snapshot_to_legacy_position`](../../src/ogami_oanda/adapters/legacy/position_dict.py#L39) | function | スナップショットを旧ポジションdictへ投影する。 |

## `adapters/notifications/__init__.py`

[ソース](../../src/ogami_oanda/adapters/notifications/__init__.py)

パッケージの入口。関連型を再公開する。

## `adapters/notifications/discord.py`

[ソース](../../src/ogami_oanda/adapters/notifications/discord.py)

通知先設定を受け、ペア別Discord通知の配送と重複抑止を行う。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`NotificationConfiguration`](../../src/ogami_oanda/adapters/notifications/discord.py#L8) | class | 通知先情報を受け取る設定契約。 |
| [`create_http_session`](../../src/ogami_oanda/adapters/notifications/discord.py#L13) | function | Keep the requests dependency at the notification adapter boundary. |
| [`DiscordNotifier`](../../src/ogami_oanda/adapters/notifications/discord.py#L20) | class | 通知先設定を受け、ペア別Discord通知の配送と重複抑止を行う。 この責任を提供するクラス。 |
| [`DiscordNotifier.__init__`](../../src/ogami_oanda/adapters/notifications/discord.py#L21) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`DiscordNotifier.send`](../../src/ogami_oanda/adapters/notifications/discord.py#L28) | method | 通知を配送する。 |
| [`DiscordNotifier._webhook`](../../src/ogami_oanda/adapters/notifications/discord.py#L59) | method / internal | 通知種別とペアに対応する配送先を選ぶ。 |
| [`DiscordNotifier._pair_from_message`](../../src/ogami_oanda/adapters/notifications/discord.py#L68) | method / internal | 通知メッセージから通貨ペアを判定する。 |

## `adapters/oanda/__init__.py`

[ソース](../../src/ogami_oanda/adapters/oanda/__init__.py)

パッケージの入口。関連型を再公開する。

## `adapters/oanda/client.py`

[ソース](../../src/ogami_oanda/adapters/oanda/client.py)

口座ごとのOANDAクライアントを所有し、要求の実行と例外の分類を行う。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`AccountConfiguration`](../../src/ogami_oanda/adapters/oanda/client.py#L13) | class | OANDA接続に必要な口座設定の契約。 |
| [`OandaClient`](../../src/ogami_oanda/adapters/oanda/client.py#L19) | class | 口座ごとのOANDAクライアントを所有し、要求の実行と例外の分類を行う。 この責任を提供するクラス。 |
| [`OandaClient.__init__`](../../src/ogami_oanda/adapters/oanda/client.py#L20) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`OandaClient.account_id`](../../src/ogami_oanda/adapters/oanda/client.py#L25) | method | クライアントが使う口座識別子を返す（実値は文書化しない）。 |
| [`OandaClient.request`](../../src/ogami_oanda/adapters/oanda/client.py#L28) | method | SDK要求を実行し、既知の外部サービス障害を分類する。 |
| [`_status_code`](../../src/ogami_oanda/adapters/oanda/client.py#L53) | function / internal | 例外からHTTP状態コードを取り出す。 |
| [`_is_transient`](../../src/ogami_oanda/adapters/oanda/client.py#L61) | function / internal | 再試行対象の一時障害か分類する。 |
| [`_retry_after`](../../src/ogami_oanda/adapters/oanda/client.py#L71) | function / internal | サーバー指定の再試行待機時間を取り出す。 |

## `adapters/oanda/execution.py`

[ソース](../../src/ogami_oanda/adapters/oanda/execution.py)

ブローカー中立の発注・取消・決済・保護変更をOANDA操作へ変換する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`OandaExecutionAdapter`](../../src/ogami_oanda/adapters/oanda/execution.py#L27) | class | ブローカー中立の発注・取消・決済・保護変更をOANDA操作へ変換する。 この責任を提供するクラス。 |
| [`OandaExecutionAdapter.__init__`](../../src/ogami_oanda/adapters/oanda/execution.py#L28) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`OandaExecutionAdapter.submit`](../../src/ogami_oanda/adapters/oanda/execution.py#L37) | method | 注文要求をブローカーへ送り、状態別の発注結果を返す。 |
| [`OandaExecutionAdapter.cancel_order`](../../src/ogami_oanda/adapters/oanda/execution.py#L61) | method | 指定注文を取り消し、結果を返す。 |
| [`OandaExecutionAdapter.close_trade`](../../src/ogami_oanda/adapters/oanda/execution.py#L69) | method | 指定取引を決済し、結果を返す。 |
| [`OandaExecutionAdapter.amend_protection`](../../src/ogami_oanda/adapters/oanda/execution.py#L78) | method | 取引のTP/SL保護を変更し、結果を返す。 |
| [`_submission_exception_result`](../../src/ogami_oanda/adapters/oanda/execution.py#L92) | function / internal | 発注例外を拒否/不明等の型付き結果へ変換する。 |
| [`_mutation_exception_result`](../../src/ogami_oanda/adapters/oanda/execution.py#L101) | function / internal | 変更操作例外を型付き変更結果へ変換する。 |
| [`_exception_reason`](../../src/ogami_oanda/adapters/oanda/execution.py#L110) | function / internal | 例外の理由を操作結果向けに取り出す。 |
| [`_status_code`](../../src/ogami_oanda/adapters/oanda/execution.py#L117) | function / internal | 例外からHTTP状態コードを取り出す。 |
| [`_is_transient`](../../src/ogami_oanda/adapters/oanda/execution.py#L125) | function / internal | 再試行対象の一時障害か分類する。 |
| [`_is_broker_rejection`](../../src/ogami_oanda/adapters/oanda/execution.py#L137) | function / internal | ブローカー側の明示的拒否か判定する。 |
| [`_exception_text`](../../src/ogami_oanda/adapters/oanda/execution.py#L142) | function / internal | 例外から分類に用いるテキストを取り出す。 |

## `adapters/oanda/mappers.py`

[ソース](../../src/ogami_oanda/adapters/oanda/mappers.py)

価格・足・注文・取引のOANDA JSONとアプリケーション型を変換する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`map_price_response`](../../src/ogami_oanda/adapters/oanda/mappers.py#L14) | function | OANDA価格応答からbid/ask等を取り出す。 |
| [`_parse_source_time`](../../src/ogami_oanda/adapters/oanda/mappers.py#L33) | function / internal | 市場応答の時刻文字列を日時型へ変換する。 |
| [`map_candle_response`](../../src/ogami_oanda/adapters/oanda/mappers.py#L45) | function | Translate OANDA candle JSON into the canonical market-data contract. |
| [`broker_request_to_oanda`](../../src/ogami_oanda/adapters/oanda/mappers.py#L79) | function | 注文要求を注文種別別のOANDA wire payloadへ変換する。 |
| [`map_order_create_response`](../../src/ogami_oanda/adapters/oanda/mappers.py#L106) | function | 注文作成応答をpending/filled等の発注結果へ分類する。 |
| [`_transaction_reason`](../../src/ogami_oanda/adapters/oanda/mappers.py#L155) | function / internal | トランザクションから結果理由を取り出す。 |
| [`_affected_trade_ids`](../../src/ogami_oanda/adapters/oanda/mappers.py#L166) | function / internal | 応答内で変更された取引IDを集める。 |
| [`map_order_cancel_response`](../../src/ogami_oanda/adapters/oanda/mappers.py#L181) | function | 注文取消応答を変更結果へ変換する。 |
| [`map_trade_close_response`](../../src/ogami_oanda/adapters/oanda/mappers.py#L196) | function | 決済応答を変更結果へ変換する。 |
| [`map_trade_protection_response`](../../src/ogami_oanda/adapters/oanda/mappers.py#L210) | function | TP/SL変更応答を変更結果へ変換する。 |
| [`oanda_error_reason`](../../src/ogami_oanda/adapters/oanda/mappers.py#L245) | function | OANDAエラー応答から理由を抽出する。 |
| [`_execution_rejection_reason`](../../src/ogami_oanda/adapters/oanda/mappers.py#L257) | function / internal | 発注拒否理由を応答から取り出す。 |
| [`_closed_trade_id`](../../src/ogami_oanda/adapters/oanda/mappers.py#L272) | function / internal | 決済応答から終了した取引IDを取り出す。 |
| [`map_order_snapshot`](../../src/ogami_oanda/adapters/oanda/mappers.py#L284) | function | OANDA注文JSONを型付き状態へ変換する。 |
| [`map_trade_snapshot`](../../src/ogami_oanda/adapters/oanda/mappers.py#L316) | function | OANDA取引JSONを型付き状態へ変換する。 |

## `adapters/oanda/market_data.py`

[ソース](../../src/ogami_oanda/adapters/oanda/market_data.py)

価格・価格詳細・共通quote・ローソク足をOANDAから取得する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`OandaMarketDataAdapter`](../../src/ogami_oanda/adapters/oanda/market_data.py#L11) | class | 価格・価格詳細・共通quote・ローソク足をOANDAから取得する。 この責任を提供するクラス。 |
| [`OandaMarketDataAdapter.__init__`](../../src/ogami_oanda/adapters/oanda/market_data.py#L12) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`OandaMarketDataAdapter.current_price`](../../src/ogami_oanda/adapters/oanda/market_data.py#L15) | method | 現在の代表価格を取得する。 |
| [`OandaMarketDataAdapter.current_price_details`](../../src/ogami_oanda/adapters/oanda/market_data.py#L19) | method | bid/askを含む価格詳細を取得する。 |
| [`OandaMarketDataAdapter.current_quote`](../../src/ogami_oanda/adapters/oanda/market_data.py#L23) | method | 同一tickで共有するquoteを取得する。 |
| [`OandaMarketDataAdapter.candles`](../../src/ogami_oanda/adapters/oanda/market_data.py#L34) | method | 指定ペア・時間足・本数のローソク足を取得する。 |

## `adapters/oanda/query.py`

[ソース](../../src/ogami_oanda/adapters/oanda/query.py)

口座能力・取引履歴・取引ルール・注文・ポジションを照会する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`OandaQueryAdapter`](../../src/ogami_oanda/adapters/oanda/query.py#L26) | class | 口座能力・取引履歴・取引ルール・注文・ポジションを照会する。 この責任を提供するクラス。 |
| [`OandaQueryAdapter.__init__`](../../src/ogami_oanda/adapters/oanda/query.py#L27) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`OandaQueryAdapter.account_capabilities`](../../src/ogami_oanda/adapters/oanda/query.py#L30) | method | 口座の識別とヘッジ能力を照会する。 |
| [`OandaQueryAdapter.transactions_since`](../../src/ogami_oanda/adapters/oanda/query.py#L45) | method | 保存カーソル以降の取引トランザクションを取得する。 |
| [`OandaQueryAdapter.instrument_rules`](../../src/ogami_oanda/adapters/oanda/query.py#L64) | method | ペアの最小数量・精度等の取引ルールを取得する。 |
| [`OandaQueryAdapter.position`](../../src/ogami_oanda/adapters/oanda/query.py#L86) | method | 注文ID・取引IDに対応するポジション状態を取得する。 |
| [`OandaQueryAdapter.order`](../../src/ogami_oanda/adapters/oanda/query.py#L92) | method | 指定注文の状態を取得する。 |
| [`OandaQueryAdapter.trade`](../../src/ogami_oanda/adapters/oanda/query.py#L103) | method | 指定取引の状態を取得する。 |
| [`OandaQueryAdapter.pending_orders`](../../src/ogami_oanda/adapters/oanda/query.py#L146) | method | 未約定注文の一覧を取得する。 |
| [`OandaQueryAdapter.open_positions`](../../src/ogami_oanda/adapters/oanda/query.py#L150) | method | 保有中ポジションの一覧を取得する。 |
| [`OandaQueryAdapter.legacy_open_position`](../../src/ogami_oanda/adapters/oanda/query.py#L158) | method | 現在の取引を旧ポジション形式へ投影する。 |
| [`_is_missing_resource`](../../src/ogami_oanda/adapters/oanda/query.py#L165) | function / internal | 対象注文/取引が存在しない応答か判定する。 |
| [`_map_transaction`](../../src/ogami_oanda/adapters/oanda/query.py#L186) | function / internal | OANDAトランザクションを中立型へ変換する。 |
| [`_map_closed_trades`](../../src/ogami_oanda/adapters/oanda/query.py#L229) | function / internal | 終了した取引情報を中立型へ変換する。 |

## `adapters/repositories/__init__.py`

[ソース](../../src/ogami_oanda/adapters/repositories/__init__.py)

パッケージの入口。関連型を再公開する。

## `adapters/repositories/csv_trade_history.py`

[ソース](../../src/ogami_oanda/adapters/repositories/csv_trade_history.py)

決済履歴CSVの追記・trade IDによる重複抑止・再読込を行う。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`CsvTradeHistoryRepository`](../../src/ogami_oanda/adapters/repositories/csv_trade_history.py#L8) | class | 決済履歴CSVの追記・trade IDによる重複抑止・再読込を行う。 この責任を提供するクラス。 |
| [`CsvTradeHistoryRepository.__init__`](../../src/ogami_oanda/adapters/repositories/csv_trade_history.py#L9) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`CsvTradeHistoryRepository.append`](../../src/ogami_oanda/adapters/repositories/csv_trade_history.py#L12) | method | 決済履歴を追加する。 |
| [`CsvTradeHistoryRepository.append_once`](../../src/ogami_oanda/adapters/repositories/csv_trade_history.py#L21) | method | 同じtrade IDを重複登録しないよう履歴を追加する。 |
| [`CsvTradeHistoryRepository.read_all`](../../src/ogami_oanda/adapters/repositories/csv_trade_history.py#L36) | method | 保存済み決済履歴を読み取る。 |

## `adapters/repositories/json_position_state.py`

[ソース](../../src/ogami_oanda/adapters/repositories/json_position_state.py)

口座/ペア別チェックポイントをJSON化し、原子的保存・バックアップ・読込を行う。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`PositionStateWriteError`](../../src/ogami_oanda/adapters/repositories/json_position_state.py#L60) | class | 口座/ペア別チェックポイントをJSON化し、原子的保存・バックアップ・読込を行う。 この境界の失敗を呼び出し側へ伝える例外。 |
| [`_CheckpointDecodeError`](../../src/ogami_oanda/adapters/repositories/json_position_state.py#L64) | class / internal | 口座/ペア別チェックポイントをJSON化し、原子的保存・バックアップ・読込を行う。 この境界の失敗を呼び出し側へ伝える例外。 |
| [`_SchemaMismatch`](../../src/ogami_oanda/adapters/repositories/json_position_state.py#L68) | class / internal | 口座/ペア別チェックポイントをJSON化し、原子的保存・バックアップ・読込を行う。 この境界の失敗を呼び出し側へ伝える例外。 |
| [`JsonPositionStateRepository`](../../src/ogami_oanda/adapters/repositories/json_position_state.py#L72) | class | 口座/ペア別チェックポイントをJSON化し、原子的保存・バックアップ・読込を行う。 この責任を提供するクラス。 |
| [`JsonPositionStateRepository.__init__`](../../src/ogami_oanda/adapters/repositories/json_position_state.py#L73) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`JsonPositionStateRepository.save`](../../src/ogami_oanda/adapters/repositories/json_position_state.py#L78) | method | チェックポイントを保存する。 |
| [`JsonPositionStateRepository.load`](../../src/ogami_oanda/adapters/repositories/json_position_state.py#L115) | method | チェックポイントを読み取り、読込状態とともに返す。 |
| [`JsonPositionStateRepository._load_path`](../../src/ogami_oanda/adapters/repositories/json_position_state.py#L154) | method / internal | 指定ファイルからチェックポイントを検証付きで読む。 |
| [`JsonPositionStateRepository._fsync_file`](../../src/ogami_oanda/adapters/repositories/json_position_state.py#L187) | method / internal | 保存ファイルをストレージへ同期する。 |
| [`JsonPositionStateRepository._fsync_directory`](../../src/ogami_oanda/adapters/repositories/json_position_state.py#L191) | method / internal | ファイル置換を含むディレクトリ更新を同期する。 |
| [`_encode_checkpoint`](../../src/ogami_oanda/adapters/repositories/json_position_state.py#L199) | function / internal | チェックポイントを保存用dictへ変換する。 |
| [`_decode_checkpoint`](../../src/ogami_oanda/adapters/repositories/json_position_state.py#L224) | function / internal | 保存dictの版と構造を検証してチェックポイントを復元する。 |
| [`_encode_position`](../../src/ogami_oanda/adapters/repositories/json_position_state.py#L304) | function / internal | 管理ポジションを保存形式へ変換する。 |
| [`_decode_position`](../../src/ogami_oanda/adapters/repositories/json_position_state.py#L339) | function / internal | 保存形式から管理ポジションを復元する。 |
| [`_encode_order_plan`](../../src/ogami_oanda/adapters/repositories/json_position_state.py#L401) | function / internal | 注文計画を保存形式へ変換する。 |
| [`_decode_order_plan`](../../src/ogami_oanda/adapters/repositories/json_position_state.py#L438) | function / internal | 保存形式から注文計画を復元する。 |
| [`_encode_analytics`](../../src/ogami_oanda/adapters/repositories/json_position_state.py#L503) | function / internal | 損益集計を保存形式へ変換する。 |
| [`_decode_analytics`](../../src/ogami_oanda/adapters/repositories/json_position_state.py#L520) | function / internal | 保存形式から損益集計を復元する。 |
| [`_plain_json_value`](../../src/ogami_oanda/adapters/repositories/json_position_state.py#L552) | function / internal | 値をJSON互換の保存表現へ変換する。 |
| [`_restore_json_value`](../../src/ogami_oanda/adapters/repositories/json_position_state.py#L566) | function / internal | JSON保存表現から値を復元する。 |
| [`_encode_float`](../../src/ogami_oanda/adapters/repositories/json_position_state.py#L579) | function / internal | 非有限値も考慮して浮動小数を保存表現へ変換する。 |
| [`_decode_float`](../../src/ogami_oanda/adapters/repositories/json_position_state.py#L587) | function / internal | 保存表現から浮動小数を復元する。 |
| [`_encode_datetime`](../../src/ogami_oanda/adapters/repositories/json_position_state.py#L595) | function / internal | 日時を保存可能な表現へ変換する。 |
| [`_decode_datetime`](../../src/ogami_oanda/adapters/repositories/json_position_state.py#L599) | function / internal | 保存された日時表現を復元する。 |
| [`_optional_string`](../../src/ogami_oanda/adapters/repositories/json_position_state.py#L603) | function / internal | 省略可能な文字列を検証・復元する。 |
| [`_optional_float`](../../src/ogami_oanda/adapters/repositories/json_position_state.py#L607) | function / internal | 省略可能な浮動小数を検証・復元する。 |
| [`_optional_int`](../../src/ogami_oanda/adapters/repositories/json_position_state.py#L611) | function / internal | 省略可能な整数を検証・復元する。 |
