# domain コード参照

[コード参照の入口](README.md) / [構成](../structure.md)

## `domain/__init__.py`

[ソース](../../src/ogami_oanda/domain/__init__.py)

パッケージの入口。初期化時に業務処理を開始しない。

## `domain/analysis/__init__.py`

[ソース](../../src/ogami_oanda/domain/analysis/__init__.py)

パッケージの入口。初期化時に業務処理を開始しない。

## `domain/analysis/candle_meta.py`

[ソース](../../src/ogami_oanda/domain/analysis/candle_meta.py)

ローソク足の代表情報・値幅・平均変動を計算する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`CandleMeta`](../../src/ogami_oanda/domain/analysis/candle_meta.py#L4) | class | ローソク足の代表情報・値幅・平均変動を計算する。 この責任を提供するクラス。 |
| [`CandleMeta.__init__`](../../src/ogami_oanda/domain/analysis/candle_meta.py#L5) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`CandleMeta.cal_move_size`](../../src/ogami_oanda/domain/analysis/candle_meta.py#L19) | method | 足の値幅を計算する。 |
| [`CandleMeta.cal_move_ave`](../../src/ogami_oanda/domain/analysis/candle_meta.py#L35) | method | 足の平均変動幅を計算する。 |

## `domain/analysis/indicators.py`

[ソース](../../src/ogami_oanda/domain/analysis/indicators.py)

OHLCの派生列、RSI、MACD、EMA、ボリンジャーバンドを計算する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`add_basic_data`](../../src/ogami_oanda/domain/analysis/indicators.py#L9) | function | Add derived candle values to canonical OHLC market data. |
| [`add_rsi`](../../src/ogami_oanda/domain/analysis/indicators.py#L37) | function | 足へRSI列を追加する。 |
| [`add_macd`](../../src/ogami_oanda/domain/analysis/indicators.py#L53) | function | 足へMACD列を追加する。 |
| [`add_ema_data`](../../src/ogami_oanda/domain/analysis/indicators.py#L67) | function | 足へEMAと関連列を追加する。 |
| [`_cross_angle`](../../src/ogami_oanda/domain/analysis/indicators.py#L84) | function / internal | 移動平均等の交差角度を計算する。 |
| [`add_bb_data`](../../src/ogami_oanda/domain/analysis/indicators.py#L92) | function | 足へボリンジャーバンド列を追加する。 |

## `domain/analysis/lines.py`

[ソース](../../src/ogami_oanda/domain/analysis/lines.py)

価格帯でピークをまとめ、ライン強度・役割・反転履歴を計算する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`LineStrengthResult`](../../src/ogami_oanda/domain/analysis/lines.py#L14) | class | 価格帯別ライン計算をまとめた結果。 |
| [`LineGrouper`](../../src/ogami_oanda/domain/analysis/lines.py#L27) | class | Pure price-band grouping for Peak dictionaries. |
| [`LineGrouper.__init__`](../../src/ogami_oanda/domain/analysis/lines.py#L30) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`LineGrouper.make_same_price_group`](../../src/ogami_oanda/domain/analysis/lines.py#L34) | method | 同じ価格帯のピークをグループ化する。 |
| [`LineGrouper.make_same_price_group_core_first`](../../src/ogami_oanda/domain/analysis/lines.py#L74) | method | 中核ピークを先に決めて同価格帯をまとめる。 |
| [`LineGrouper.can_add_peak_to_line`](../../src/ogami_oanda/domain/analysis/lines.py#L110) | method | ピークを既存ラインへ追加できるか判定する。 |
| [`LineGrouper.refresh_line_group`](../../src/ogami_oanda/domain/analysis/lines.py#L117) | method | グループの代表値と関連情報を更新する。 |
| [`LineGrouper._nearest_group`](../../src/ogami_oanda/domain/analysis/lines.py#L128) | method / internal | 価格に最も近いピークグループを探す。 |
| [`LineGrouper._group_record`](../../src/ogami_oanda/domain/analysis/lines.py#L137) | method / internal | グループの代表情報をレコード化する。 |
| [`LineStrengthCalculator`](../../src/ogami_oanda/domain/analysis/lines.py#L177) | class | Construct legacy-compatible line classes from pure peak and candle inputs. |
| [`LineStrengthCalculator.__init__`](../../src/ogami_oanda/domain/analysis/lines.py#L182) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`LineStrengthCalculator.calculate`](../../src/ogami_oanda/domain/analysis/lines.py#L186) | method | ピークと足からライン強度の計算結果を作る。 |
| [`LineStrengthCalculator._same_peak`](../../src/ogami_oanda/domain/analysis/lines.py#L267) | method / internal | 同一ピークか比較する。 |
| [`LineStrengthCalculator._combine_all_lines`](../../src/ogami_oanda/domain/analysis/lines.py#L275) | method / internal | 時間足・種類別のラインをまとめる。 |
| [`LineStrengthCalculator._add_line_flip_marker`](../../src/ogami_oanda/domain/analysis/lines.py#L281) | method / internal | ラインの役割反転マーカーを付ける。 |
| [`LineStrengthCalculator._add_line_role_history`](../../src/ogami_oanda/domain/analysis/lines.py#L292) | method / internal | ラインの支持/抵抗の履歴を付ける。 |

## `domain/analysis/peaks.py`

[ソース](../../src/ogami_oanda/domain/analysis/peaks.py)

新しい順の足から方向別ピークを抽出し、強度補正・間引きを行う。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`_time_hms`](../../src/ogami_oanda/domain/analysis/peaks.py#L11) | function / internal | ピーク用時刻を時分秒表示へ整形する。 |
| [`PeaksClass`](../../src/ogami_oanda/domain/analysis/peaks.py#L15) | class | Extract directional candle peaks from a newest-first candle frame. |
| [`PeaksClass.__init__`](../../src/ogami_oanda/domain/analysis/peaks.py#L18) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`PeaksClass._set_granularity_parameters`](../../src/ogami_oanda/domain/analysis/peaks.py#L70) | method / internal | 時間足に応じたピーク抽出条件を設定する。 |
| [`PeaksClass.make_peak`](../../src/ogami_oanda/domain/analysis/peaks.py#L92) | method | 1つの方向連続区間からピーク情報を作る。 |
| [`PeaksClass.make_peaks`](../../src/ogami_oanda/domain/analysis/peaks.py#L155) | method | 足全体から順にピークを抽出する。 |
| [`PeaksClass.recalculation_peak_strength_for_peaks`](../../src/ogami_oanda/domain/analysis/peaks.py#L198) | method | ピーク同士の関係で強度を補正する。 |
| [`PeaksClass.skip_peaks`](../../src/ogami_oanda/domain/analysis/peaks.py#L208) | method | 小さなピークを間引く。 |
| [`PeaksClass.skip_peaks_hard`](../../src/ogami_oanda/domain/analysis/peaks.py#L211) | method | 強い間引き条件でピークを整理する。 |
| [`PeaksClass._skip`](../../src/ogami_oanda/domain/analysis/peaks.py#L214) | method / internal | 条件に応じてピークを間引く共通処理。 |
| [`PeaksClass.cal_target_times_skip_num`](../../src/ogami_oanda/domain/analysis/peaks.py#L245) | method | 指定時間に相当する間引き数を計算する。 |
| [`PeaksClass.pips_to_price`](../../src/ogami_oanda/domain/analysis/peaks.py#L251) | method | pipsをペアの価格差へ変換する。 |
| [`PeaksClass.round_price`](../../src/ogami_oanda/domain/analysis/peaks.py#L254) | method | ペアの価格精度に丸める。 |
| [`PeaksClass.check_large_body_in_peak`](../../src/ogami_oanda/domain/analysis/peaks.py#L257) | method | ピーク内に大きな実体の足があるか確認する。 |
| [`judge_peak_is_belong_peak_group`](../../src/ogami_oanda/domain/analysis/peaks.py#L270) | function | ピークが価格帯グループに属するか判定する。 |

## `domain/market/__init__.py`

[ソース](../../src/ogami_oanda/domain/market/__init__.py)

パッケージの入口。関連型を再公開する。

## `domain/market/candle_frame.py`

[ソース](../../src/ogami_oanda/domain/market/candle_frame.py)

足DataFrameの必須列・非空・時刻順を検証する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`CandleFrameSchema`](../../src/ogami_oanda/domain/market/candle_frame.py#L9) | class | 足DataFrameの必須列・非空・時刻順を検証する。 この責任を提供するクラス。 |
| [`CandleFrameSchema.validate`](../../src/ogami_oanda/domain/market/candle_frame.py#L14) | method | DataFrameの必須列・非空・新しい順の時刻を検証する。 |

## `domain/market/currency_pair.py`

[ソース](../../src/ogami_oanda/domain/market/currency_pair.py)

ペア別の価格精度・文字列化・pips換算を提供する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`CurrencyPair`](../../src/ogami_oanda/domain/market/currency_pair.py#L7) | class | ペア別の価格精度・文字列化・pips換算を提供する。 この責任を提供するクラス。 |
| [`CurrencyPair.round_price`](../../src/ogami_oanda/domain/market/currency_pair.py#L15) | method | ペアの価格精度に丸める。 |
| [`CurrencyPair.price_to_str`](../../src/ogami_oanda/domain/market/currency_pair.py#L18) | method | ペアの精度に合わせて価格を文字列化する。 |
| [`CurrencyPair.pips_to_price`](../../src/ogami_oanda/domain/market/currency_pair.py#L21) | method | pipsをペアの価格差へ変換する。 |
| [`CurrencyPair.price_to_pips`](../../src/ogami_oanda/domain/market/currency_pair.py#L24) | method | 価格差をpipsへ変換する。 |
| [`CurrencyPair.is_price`](../../src/ogami_oanda/domain/market/currency_pair.py#L27) | method | 値を価格指定として扱うか判断する。 |
| [`currency_pair`](../../src/ogami_oanda/domain/market/currency_pair.py#L38) | function | 通貨ペア名に対応する計算設定を返す。 |

## `domain/orders/__init__.py`

[ソース](../../src/ogami_oanda/domain/orders/__init__.py)

パッケージの入口。関連型を再公開する。

## `domain/orders/models.py`

[ソース](../../src/ogami_oanda/domain/orders/models.py)

売買方向・注文種別・intent・context・確定計画・発注識別子を定義する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`Direction`](../../src/ogami_oanda/domain/orders/models.py#L10) | class | BUY=1、SELL=-1の売買方向。 |
| [`OrderType`](../../src/ogami_oanda/domain/orders/models.py#L15) | class | MARKET・LIMIT・STOPの注文種別。 |
| [`_frozen_metadata`](../../src/ogami_oanda/domain/orders/models.py#L21) | function / internal | メタデータをコピーし、読み取り専用mappingにする。 |
| [`OrderIntent`](../../src/ogami_oanda/domain/orders/models.py#L26) | class | 戦略が判断した目標・TP/SL・数量・期限・メタデータ。 |
| [`OrderIntent.__post_init__`](../../src/ogami_oanda/domain/orders/models.py#L44) | method | 生成直後に入力の整合性確認や不変形式への変換を行う。 |
| [`OrderContext`](../../src/ogami_oanda/domain/orders/models.py#L50) | class | 計画確定に必要な現在価格・判断時刻等の文脈。 |
| [`BrokerOrderRequest`](../../src/ogami_oanda/domain/orders/models.py#L58) | class | SDKに依存しない確定発注要求。 |
| [`submission_fingerprint`](../../src/ogami_oanda/domain/orders/models.py#L68) | function | 注文判断の主要値から安定した送信識別子を計算する。 |
| [`OrderPlan`](../../src/ogami_oanda/domain/orders/models.py#L93) | class | intent/contextと確定価格・レンジ・発注要求を保持する計画。 |

## `domain/positions/__init__.py`

[ソース](../../src/ogami_oanda/domain/positions/__init__.py)

パッケージの入口。関連型を再公開する。

## `domain/positions/managed_position.py`

[ソース](../../src/ogami_oanda/domain/positions/managed_position.py)

注文計画・スナップショット・runtimeを持つポジションの値更新を提供する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`ManagedPosition`](../../src/ogami_oanda/domain/positions/managed_position.py#L18) | class | 注文計画・ブローカー状態・runtimeをまとめた不変の管理単位。 |
| [`ManagedPosition.registered`](../../src/ogami_oanda/domain/positions/managed_position.py#L23) | method | 登録済みの管理ポジションを作る。 |
| [`ManagedPosition.restored`](../../src/ogami_oanda/domain/positions/managed_position.py#L27) | method | 保存/取得した状態から管理ポジションを復元する。 |
| [`ManagedPosition.with_order_plan`](../../src/ogami_oanda/domain/positions/managed_position.py#L40) | method | 注文計画を差し替えた管理ポジションを返す。 |
| [`ManagedPosition.with_runtime`](../../src/ogami_oanda/domain/positions/managed_position.py#L58) | method | runtime状態を差し替えた管理ポジションを返す。 |
| [`ManagedPosition.watching`](../../src/ogami_oanda/domain/positions/managed_position.py#L61) | method | 発注前監視状態へ遷移した値を返す。 |
| [`ManagedPosition.pending`](../../src/ogami_oanda/domain/positions/managed_position.py#L66) | method | 未約定状態を表す値を作る。 |
| [`ManagedPosition.filled`](../../src/ogami_oanda/domain/positions/managed_position.py#L71) | method | 約定済み状態を表す値を作る。 |
| [`ManagedPosition.rejected`](../../src/ogami_oanda/domain/positions/managed_position.py#L97) | method | 拒否された状態を表す値を作る。 |
| [`ManagedPosition.submission_uncertain`](../../src/ogami_oanda/domain/positions/managed_position.py#L112) | method | 送信結果が不明な状態へ遷移した値を返す。 |
| [`ManagedPosition.cancelled`](../../src/ogami_oanda/domain/positions/managed_position.py#L127) | method | 取り消された状態を表す値を作る。 |
| [`ManagedPosition.closed`](../../src/ogami_oanda/domain/positions/managed_position.py#L132) | method | 終了済み状態へ遷移した値を返す。 |
| [`ManagedPosition._replace`](../../src/ogami_oanda/domain/positions/managed_position.py#L135) | method / internal | 指定フィールドを置換した管理ポジションを返す。 |

## `domain/positions/models.py`

[ソース](../../src/ogami_oanda/domain/positions/models.py)

注文/取引/送信状態、スナップショット、runtime、command、eventを定義する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`OrderState`](../../src/ogami_oanda/domain/positions/models.py#L11) | class | ブローカー上の注文状態区分。 |
| [`TradeState`](../../src/ogami_oanda/domain/positions/models.py#L22) | class | ブローカー上の取引状態区分。 |
| [`SubmissionPhase`](../../src/ogami_oanda/domain/positions/models.py#L29) | class | 発注準備・送信結果等の管理段階。 |
| [`PositionSnapshot`](../../src/ogami_oanda/domain/positions/models.py#L43) | class | 注文/取引のある時点の観測状態。 |
| [`PositionRuntimeState`](../../src/ogami_oanda/domain/positions/models.py#L72) | class | 監視・期限・SL変更・重複抑止等の管理状態。 |
| [`PositionCommand`](../../src/ogami_oanda/domain/positions/models.py#L99) | class | ポジションへ適用する変更指示。 |
| [`PositionEvent`](../../src/ogami_oanda/domain/positions/models.py#L108) | class | 管理状態の変化を通知・表示へ渡すイベント。 |
