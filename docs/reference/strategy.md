# strategy コード参照

[コード参照の入口](README.md) / [構成](../structure.md) / [戦略一覧](../../src/ogami_oanda/strategy/README.md)

## `strategy/__init__.py`

[ソース](../../src/ogami_oanda/strategy/__init__.py)

パッケージの入口。関連型を再公開する。 旧import名と子モジュールを新配置の同一オブジェクトへ登録する互換窓口。

## `strategy/original/__init__.py`

[ソース](../../src/ogami_oanda/strategy/original/__init__.py)

originalの専用パッケージ入口。役割は [戦略一覧](../../src/ogami_oanda/strategy/README.md) を参照。

## `strategy/original/line/__init__.py`

[ソース](../../src/ogami_oanda/strategy/original/line/__init__.py)

パッケージの入口。関連型を再公開する。

## `strategy/original/line/aud_usd.py`

[ソース](../../src/ogami_oanda/strategy/original/line/aud_usd.py)

AUD/USD用のライン戦略プロファイルを定義する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`LineStrategyProfileAudUsd`](../../src/ogami_oanda/strategy/original/line/aud_usd.py#L8) | class | AUD_USD line strategy. |

## `strategy/original/line/builder.py`

[ソース](../../src/ogami_oanda/strategy/original/line/builder.py)

ペア別候補の生成・選択・補足・診断をまとめ、注文判断用候補を返す。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`CandidateDiagnostics`](../../src/ogami_oanda/strategy/original/line/builder.py#L25) | class | 候補生成/採用段階の件数と不採用理由。 |
| [`CandidateDiagnostics.reject_selected`](../../src/ogami_oanda/strategy/original/line/builder.py#L30) | method | 採用候補の後段不採用理由を診断へ追加する。 |
| [`CandidateBuildResult`](../../src/ogami_oanda/strategy/original/line/builder.py#L49) | class | 選択候補と診断をまとめた結果。 |
| [`_AnalysisView`](../../src/ogami_oanda/strategy/original/line/builder.py#L55) | class / internal | 戦略へ渡す解析文脈の属性ビュー。 |
| [`line_strategy_profile_for_pair`](../../src/ogami_oanda/strategy/original/line/builder.py#L61) | function | 通貨ペアに対応するライン戦略プロファイルを選ぶ。 |
| [`LineCandidateBuilder`](../../src/ogami_oanda/strategy/original/line/builder.py#L69) | class | Build selected line candidate dicts without legacy order creation. |
| [`LineCandidateBuilder.__init__`](../../src/ogami_oanda/strategy/original/line/builder.py#L72) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`LineCandidateBuilder.__call__`](../../src/ogami_oanda/strategy/original/line/builder.py#L77) | method | 解析文脈から選択・補足済みライン候補を返す。 |
| [`LineCandidateBuilder.build_with_diagnostics`](../../src/ogami_oanda/strategy/original/line/builder.py#L80) | method | 候補と段階別の件数・不採用理由を構築する。 |
| [`LineCandidateBuilder._counts_by_mode`](../../src/ogami_oanda/strategy/original/line/builder.py#L118) | method / internal | 戦術モード別の候補数を集計する。 |
| [`LineCandidateBuilder._condition_rejection_reason`](../../src/ogami_oanda/strategy/original/line/builder.py#L126) | method / internal | 候補が条件で不採用となった理由を作る。 |
| [`LineCandidateBuilder.build_raw_candidates`](../../src/ogami_oanda/strategy/original/line/builder.py#L133) | method | 選別前のライン候補を作る。 |
| [`LineCandidateBuilder.select_candidates`](../../src/ogami_oanda/strategy/original/line/builder.py#L155) | method | 戦略条件で候補を選ぶ。 |
| [`LineCandidateBuilder.enrich_candidates`](../../src/ogami_oanda/strategy/original/line/builder.py#L179) | method | 選択候補へ数量・保護値・期限等を追加する。 |
| [`LineCandidateBuilder._apply_session_policy`](../../src/ogami_oanda/strategy/original/line/builder.py#L236) | method / internal | 取引sessionに応じた候補条件を適用する。 |
| [`LineCandidateBuilder._apply_path_short_protection`](../../src/ogami_oanda/strategy/original/line/builder.py#L282) | method / internal | 次ラインまでの短い経路に対する保護値を調整する。 |
| [`LineCandidateBuilder._path_short_pips`](../../src/ogami_oanda/strategy/original/line/builder.py#L319) | method / internal | 次ラインまでの短い距離をpipsで計算する。 |
| [`LineCandidateBuilder._strategy_lines_for_mode`](../../src/ogami_oanda/strategy/original/line/builder.py#L342) | method / internal | 戦術モードで使用するライン群を選ぶ。 |
| [`LineCandidateBuilder._reason_func_for_mode`](../../src/ogami_oanda/strategy/original/line/builder.py#L347) | method / internal | モードに対応する推薦理由判定を選ぶ。 |

## `strategy/original/line/coordinator.py`

[ソース](../../src/ogami_oanda/strategy/original/line/coordinator.py)

ラインから候補を生成し、近接候補を除き、推薦条件とsession情報を付ける。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`LineCandidateCoordinator`](../../src/ogami_oanda/strategy/original/line/coordinator.py#L8) | class | Build and select line candidate dictionaries without broker dependencies. |
| [`LineCandidateCoordinator.__init__`](../../src/ogami_oanda/strategy/original/line/coordinator.py#L11) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`LineCandidateCoordinator.build_line_candidates`](../../src/ogami_oanda/strategy/original/line/coordinator.py#L18) | method | ラインの種類と方向から注文候補を作る。 |
| [`LineCandidateCoordinator.attach_candidate_decision_context`](../../src/ogami_oanda/strategy/original/line/coordinator.py#L36) | method | 候補へRSI・近傍ライン等の判断文脈を付ける。 |
| [`LineCandidateCoordinator.remove_near_candidates`](../../src/ogami_oanda/strategy/original/line/coordinator.py#L49) | method | 近い候補の重複を除く。 |
| [`LineCandidateCoordinator.select_line_candidates`](../../src/ogami_oanda/strategy/original/line/coordinator.py#L62) | method | ライン候補を優先度・条件で選ぶ。 |
| [`LineCandidateCoordinator.filter_recommended_candidates`](../../src/ogami_oanda/strategy/original/line/coordinator.py#L75) | method | 推薦理由を満たす候補に絞る。 |
| [`LineCandidateCoordinator.get_session_info`](../../src/ogami_oanda/strategy/original/line/coordinator.py#L80) | method | 判断時刻から取引session情報を作る。 |
| [`LineCandidateCoordinator._build_condition_memo`](../../src/ogami_oanda/strategy/original/line/coordinator.py#L87) | method / internal | 候補の条件説明をまとめる。 |
| [`LineCandidateCoordinator._latest_peak_info`](../../src/ogami_oanda/strategy/original/line/coordinator.py#L116) | method / internal | 最新ピークの判断情報を取り出す。 |
| [`LineCandidateCoordinator._add_h1_context`](../../src/ogami_oanda/strategy/original/line/coordinator.py#L129) | method / internal | 候補へH1ラインの文脈を追加する。 |
| [`LineCandidateCoordinator._add_previous_peak_line_context`](../../src/ogami_oanda/strategy/original/line/coordinator.py#L213) | method / internal | 候補へ直前ピークとラインの関係を追加する。 |
| [`LineCandidateCoordinator._line_items`](../../src/ogami_oanda/strategy/original/line/coordinator.py#L232) | method / internal | ライン群を列挙可能な形式にそろえる。 |
| [`LineCandidateCoordinator._nearest`](../../src/ogami_oanda/strategy/original/line/coordinator.py#L240) | method / internal | 基準に最も近いラインを選ぶ。 |
| [`LineCandidateCoordinator._sorted_ahead_lines`](../../src/ogami_oanda/strategy/original/line/coordinator.py#L244) | method / internal | 進行方向のラインを距離順に並べる。 |
| [`LineCandidateCoordinator._line_fields`](../../src/ogami_oanda/strategy/original/line/coordinator.py#L254) | method / internal | 候補へ転記するライン情報を選ぶ。 |
| [`LineCandidateCoordinator._previous_peak_line_fields`](../../src/ogami_oanda/strategy/original/line/coordinator.py#L265) | method / internal | 直前ピークに関連するライン項目を作る。 |
| [`LineCandidateCoordinator._line_contains_peak`](../../src/ogami_oanda/strategy/original/line/coordinator.py#L308) | method / internal | ラインに対象ピークが含まれるか判定する。 |

## `strategy/original/line/eur_usd.py`

[ソース](../../src/ogami_oanda/strategy/original/line/eur_usd.py)

EUR/USD固有の推薦条件とbreakout条件を定義する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`LineStrategyProfileEurUsd`](../../src/ogami_oanda/strategy/original/line/eur_usd.py#L6) | class | EUR_USD line strategy. |
| [`LineStrategyProfileEurUsd.recommended_reasons`](../../src/ogami_oanda/strategy/original/line/eur_usd.py#L82) | method | 候補を推薦する条件と理由を返す。 |
| [`LineStrategyProfileEurUsd._eurusd_breakout_reasons`](../../src/ogami_oanda/strategy/original/line/eur_usd.py#L96) | method / internal | EUR/USDの突破候補の推薦理由を返す。 |

## `strategy/original/line/order_timeout.py`

[ソース](../../src/ogami_oanda/strategy/original/line/order_timeout.py)

目標価格までの距離から注文待機期限を決める。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`order_timeout_min_for_distance`](../../src/ogami_oanda/strategy/original/line/order_timeout.py#L4) | function | 目標距離に応じた未約定期限を分単位で返す。 |

## `strategy/original/line/usd_jpy.py`

[ソース](../../src/ogami_oanda/strategy/original/line/usd_jpy.py)

USD/JPYのH1/M5反転・突破候補と推薦理由を計算する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`LineStrategyProfileUsdJpy`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L6) | class | USD_JPY用のライン戦術。 LineStrengthCalで作った4つのライン結果を受け取り、 ドル円ではどの線を注文候補にするか、どの候補を採用するかを決める。 |
| [`LineStrategyProfileUsdJpy.is_h1_reversal_target`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L297) | method | H1反転ラインを候補とする条件を判定する。 |
| [`LineStrategyProfileUsdJpy.is_m5_reversal_target`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L308) | method | M5反転ラインを候補とする条件を判定する。 |
| [`LineStrategyProfileUsdJpy.limit_recommended_reasons`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L321) | method | LIMIT候補の推薦理由を返す。 |
| [`LineStrategyProfileUsdJpy.recommended_reasons`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L324) | method | 候補を推薦する条件と理由を返す。 |
| [`LineStrategyProfileUsdJpy._configured_top10_reasons`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L358) | method / internal | 設定された上位条件群の推薦理由を集める。 |
| [`LineStrategyProfileUsdJpy.immediate_recommended_reasons`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L367) | method | 即時候補の推薦理由を返す。 |
| [`LineStrategyProfileUsdJpy._immediate_breakout_context`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L413) | method / internal | 即時突破判断に用いる周辺条件を作る。 |
| [`LineStrategyProfileUsdJpy._current_rsi_matches_direction`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L448) | method / internal | 現在RSIが売買方向の条件に一致するか判定する。 |
| [`LineStrategyProfileUsdJpy._immediate_previous_peak_supports`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L480) | method / internal | 直前ピークが即時候補を支持するか判定する。 |
| [`LineStrategyProfileUsdJpy._immediate_line_history_supports`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L489) | method / internal | ライン履歴が即時候補を支持するか判定する。 |
| [`LineStrategyProfileUsdJpy._immediate_peak_rsi_supports_direction`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L513) | method / internal | ピークRSIが即時候補の方向を支持するか判定する。 |
| [`LineStrategyProfileUsdJpy._immediate_path_is_blocked`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L529) | method / internal | 即時候補の進行先が別ラインで妨げられるか判定する。 |
| [`LineStrategyProfileUsdJpy._line_peak_rsi_supports_direction`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L542) | method / internal | ラインに属するピークRSIが方向を支持するか判定する。 |
| [`LineStrategyProfileUsdJpy._peak_rsi_supports_direction`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L562) | method / internal | ピークRSIが売買方向を支持するか判定する。 |
| [`LineStrategyProfileUsdJpy._breakout_peak_rsi_supports_direction`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L581) | method / internal | 突破用ピークRSI条件を判定する。 |
| [`LineStrategyProfileUsdJpy._breakout_line_peak_rsi_supports_direction`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L595) | method / internal | 突破ラインのピークRSI条件を判定する。 |
| [`LineStrategyProfileUsdJpy._float_or_none`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L610) | method / internal | 変換可能な値をfloatへ変換し、省略値を扱う。 |
| [`LineStrategyProfileUsdJpy._reversal_peak_rsi_matches_direction`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L620) | method / internal | 反転用のピークRSI条件を判定する。 |
| [`LineStrategyProfileUsdJpy._peak_rsi_matches_direction`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L627) | method / internal | ピークRSIの方向条件への一致を判定する。 |
| [`LineStrategyProfileUsdJpy._is_top10_condition`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L645) | method / internal | 候補が設定済み上位条件群に一致するか判定する。 |
| [`LineStrategyProfileUsdJpy._condition_value`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L652) | method / internal | 候補文脈から指定した条件値を取り出す。 |
| [`LineStrategyProfileUsdJpy._bin_value`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L705) | method / internal | 値を条件比較用の区分に変換する。 |
| [`LineStrategyProfileUsdJpy._pips_bin`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L718) | method / internal | pips値を条件区分に変換する。 |
| [`LineStrategyProfileUsdJpy._path_distance_bin`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L731) | method / internal | 進行先ライン距離を条件区分に変換する。 |
| [`LineStrategyProfileUsdJpy._strength_bin`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L744) | method / internal | ライン強度を条件区分に変換する。 |
| [`LineStrategyProfileUsdJpy._rsi_bin`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L755) | method / internal | RSIを条件区分に変換する。 |
| [`LineStrategyProfileUsdJpy._session_bucket`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L766) | method / internal | 時刻をsession区分へ対応づける。 |
| [`LineStrategyProfileUsdJpy._configured_top7_reasons`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L785) | method / internal | 設定された別の上位条件群の推薦理由を集める。 |
| [`LineStrategyProfileUsdJpy._is_top7_condition`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L826) | method / internal | 候補が該当の上位条件群に一致するか判定する。 |
| [`LineStrategyProfileUsdJpy._in_range`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L873) | method / internal | 値が条件範囲内か判定する。 |
| [`LineStrategyProfileUsdJpy.create_orders_from_lines`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L881) | method | ラインから戦略の注文候補を作る。 |
| [`LineStrategyProfileUsdJpy.calculate_line_strength`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L911) | method | ライン候補の強度を計算する。 |
| [`LineStrategyProfileUsdJpy.group_lines`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L934) | method | ラインを価格帯等でまとめる。 |
| [`LineStrategyProfileUsdJpy.immediate_order`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L970) | method | 即時発注向けの候補を構築する。 |
| [`LineStrategyProfileUsdJpy.future_line_order`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L987) | method | 将来の価格到達を待つライン候補を構築する。 |
| [`LineStrategyProfileUsdJpy.future_resist_order`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L992) | method | 反転待ちの候補を構築する。 |
| [`LineStrategyProfileUsdJpy.future_break_order`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L1009) | method | 突破待ちの候補を構築する。 |
| [`LineStrategyProfileUsdJpy.future_resist_recommended_reasons`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L1026) | method | 反転待ち候補の推薦理由を返す。 |
| [`LineStrategyProfileUsdJpy.future_break_recommended_reasons`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L1032) | method | 突破待ち候補の推薦理由を返す。 |
| [`LineStrategyProfileUsdJpy._future_break_direction_is_valid`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L1041) | method / internal | 将来突破候補の方向が有効か判定する。 |
| [`UsdJpyLineOrderStrategy`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L1052) | class | USD/JPYのライン候補構築の共通戦術。 |
| [`UsdJpyLineOrderStrategy.__init__`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L1064) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`UsdJpyLineOrderStrategy.pair_info`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L1067) | method | 戦略が使う通貨ペア情報を返す。 |
| [`UsdJpyLineOrderStrategy.is_target`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L1070) | method | ラインが当該戦術の候補対象か判定する。 |
| [`UsdJpyLineOrderStrategy.get_tp_pips`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L1073) | method | 候補に設定するTP幅をpipsで返す。 |
| [`UsdJpyLineOrderStrategy.get_direction`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L1076) | method | 候補の売買方向を返す。 |
| [`UsdJpyLineOrderStrategy.get_target_price`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L1079) | method | 候補の目標価格を返す。 |
| [`UsdJpyLineOrderStrategy.build_candidates`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L1082) | method | 戦術に合うラインから候補を作る。 |
| [`UsdJpyH1LineOrderStrategy`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L1119) | class | H1ライン反転の候補条件とTP幅。 |
| [`UsdJpyH1LineOrderStrategy.__init__`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L1129) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`UsdJpyH1LineOrderStrategy.get_tp_pips`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L1135) | method | 候補に設定するTP幅をpipsで返す。 |
| [`UsdJpyH1LineOrderStrategy.is_target`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L1140) | method | ラインが当該戦術の候補対象か判定する。 |
| [`UsdJpyM5LineOrderStrategy`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L1144) | class | M5ライン反転の候補条件。 |
| [`UsdJpyM5LineOrderStrategy.__init__`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L1155) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`UsdJpyM5LineOrderStrategy.is_target`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L1162) | method | ラインが当該戦術の候補対象か判定する。 |
| [`UsdJpyM5BreakoutLineOrderStrategy`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L1166) | class | M5突破の方向・目標価格判断。 |
| [`UsdJpyM5BreakoutLineOrderStrategy.__init__`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L1173) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`UsdJpyM5BreakoutLineOrderStrategy.get_direction`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L1177) | method | 候補の売買方向を返す。 |
| [`UsdJpyM5BreakoutLineOrderStrategy.get_target_price`](../../src/ogami_oanda/strategy/original/line/usd_jpy.py#L1180) | method | 候補の目標価格を返す。 |

## `strategy/original/position_sizing.py`

[ソース](../../src/ogami_oanda/strategy/original/position_sizing.py)

許容損失とSL幅から旧仕様互換の注文数量を計算する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`PositionSizingPolicy`](../../src/ogami_oanda/strategy/original/position_sizing.py#L9) | class | Legacy-compatible risk sizing with no configuration or broker dependency. |
| [`PositionSizingPolicy.units_for`](../../src/ogami_oanda/strategy/original/position_sizing.py#L16) | method | 許容損失とSL幅から注文数量を計算する。 |

## `strategy/matcha/__init__.py`

[ソース](../../src/ogami_oanda/strategy/matcha/__init__.py)

matchaの専用パッケージ入口。役割は [戦略一覧](../../src/ogami_oanda/strategy/README.md) を参照。

## `strategy/matcha/parameters.yaml`

[ソース](../../src/ogami_oanda/strategy/matcha/parameters.yaml)

Matchaの同梱パラメータ。キーの対応範囲は [仕様](../specification.md) と同じディレクトリの `MatchaConfig.from_mapping` を参照。

## `strategy/matcha/strategy.py`

[ソース](../../src/ogami_oanda/strategy/matcha/strategy.py)

USD/JPYのMatcha判断・価格帯・ロット・鮮度/保有制限・再起動状態を提供する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`MatchaConfig`](../../src/ogami_oanda/strategy/matcha/strategy.py#L28) | class | 対応ルートを検証済みのMatcha戦略設定。 |
| [`MatchaConfig.from_mapping`](../../src/ogami_oanda/strategy/matcha/strategy.py#L60) | method | 設定mappingを検証し、対応するMatcha設定型を作る。 |
| [`MatchaStrategy`](../../src/ogami_oanda/strategy/matcha/strategy.py#L110) | class | 市場入力と保有状態からMatchaの判断と再起動状態を作る。 |
| [`MatchaStrategy.__init__`](../../src/ogami_oanda/strategy/matcha/strategy.py#L111) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`MatchaStrategy.decide`](../../src/ogami_oanda/strategy/matcha/strategy.py#L119) | method | 現在入力と内部状態から注文/管理commandと診断を決める。 |
| [`MatchaStrategy._breakout_decision`](../../src/ogami_oanda/strategy/matcha/strategy.py#L234) | method / internal | Matchaの突破シグナルと保有状態から判断を作る。 |
| [`MatchaStrategy._intent`](../../src/ogami_oanda/strategy/matcha/strategy.py#L273) | method / internal | Matchaの方向・数量・TP/SL等を注文intentにする。 |
| [`MatchaStrategy._finish`](../../src/ogami_oanda/strategy/matcha/strategy.py#L299) | method / internal | 戦略の内部状態と診断を更新して判断を返す。 |
| [`MatchaStrategy._net_units`](../../src/ogami_oanda/strategy/matcha/strategy.py#L310) | method / internal | 対象sourceの保有を符号付き数量へ集計する。 |
| [`MatchaStrategy._touch_cooldown`](../../src/ogami_oanda/strategy/matcha/strategy.py#L320) | method / internal | 評価時刻に応じてクールダウン状態を更新する。 |
| [`MatchaStrategy.entry_lot`](../../src/ogami_oanda/strategy/matcha/strategy.py#L327) | method | 基本エントリー数量を計算する。 |
| [`MatchaStrategy.entry_lot_2`](../../src/ogami_oanda/strategy/matcha/strategy.py#L330) | method | 追加経路のエントリー数量を計算する。 |
| [`MatchaStrategy.close_lot`](../../src/ogami_oanda/strategy/matcha/strategy.py#L337) | method | 決済に用いる数量を計算する。 |
| [`MatchaStrategy.max_pos_size`](../../src/ogami_oanda/strategy/matcha/strategy.py#L340) | method | 許容する最大保有数量を計算する。 |
| [`MatchaStrategy.correction_units`](../../src/ogami_oanda/strategy/matcha/strategy.py#L345) | method | 保有上限を超えた分の解消数量を計算する。 |
| [`MatchaStrategy.dump_state`](../../src/ogami_oanda/strategy/matcha/strategy.py#L348) | method | 再起動へ引き継ぐ戦略状態をJSON互換形式で返す。 |
| [`MatchaStrategy.load_state`](../../src/ogami_oanda/strategy/matcha/strategy.py#L358) | method | 保存された戦略状態を検証して読み戻す。 |
| [`create_strategy`](../../src/ogami_oanda/strategy/matcha/strategy.py#L425) | function | Validate the supported route before constructing Matcha. |
| [`_required`](../../src/ogami_oanda/strategy/matcha/strategy.py#L431) | function / internal | 必須設定を取り出し、欠落を拒否する。 |
| [`_boolean`](../../src/ogami_oanda/strategy/matcha/strategy.py#L437) | function / internal | 設定がboolであることを検証する。 |
| [`_integer`](../../src/ogami_oanda/strategy/matcha/strategy.py#L444) | function / internal | 設定が整数であることを検証する。 |
| [`_positive_int`](../../src/ogami_oanda/strategy/matcha/strategy.py#L451) | function / internal | 設定が正の整数であることを検証する。 |
| [`_nonnegative_int`](../../src/ogami_oanda/strategy/matcha/strategy.py#L458) | function / internal | 設定が0以上の整数であることを検証する。 |
| [`_finite_float`](../../src/ogami_oanda/strategy/matcha/strategy.py#L465) | function / internal | 設定が有限数であることを検証する。 |
| [`_nonnegative_float`](../../src/ogami_oanda/strategy/matcha/strategy.py#L475) | function / internal | 設定が0以上の有限数であることを検証する。 |
| [`_positive_float`](../../src/ogami_oanda/strategy/matcha/strategy.py#L482) | function / internal | 設定が正の有限数であることを検証する。 |
| [`_price_levels`](../../src/ogami_oanda/strategy/matcha/strategy.py#L489) | function / internal | Matchaの過去価格と標準偏差から注文価格帯とシグナルを計算する。 |
| [`_candle_records`](../../src/ogami_oanda/strategy/matcha/strategy.py#L552) | function / internal | 戦略入力の足を計算用レコードへそろえる。 |
| [`_newest_candle_id`](../../src/ogami_oanda/strategy/matcha/strategy.py#L573) | function / internal | 最新足の重複判定用識別子を取り出す。 |
| [`_canonical_m1_timestamp`](../../src/ogami_oanda/strategy/matcha/strategy.py#L581) | function / internal | M1足の時刻表現を正規化する。 |
| [`_population_std`](../../src/ogami_oanda/strategy/matcha/strategy.py#L603) | function / internal | 価格列の母標準偏差を計算する。 |
| [`_normalize_price`](../../src/ogami_oanda/strategy/matcha/strategy.py#L608) | function / internal | Matcha価格を所定精度に丸める。 |
| [`_quote_age_ms`](../../src/ogami_oanda/strategy/matcha/strategy.py#L612) | function / internal | 評価時刻とquote元時刻の差をミリ秒で計算する。 |

## `strategy/shared/__init__.py`

[ソース](../../src/ogami_oanda/strategy/shared/__init__.py)

sharedの専用パッケージ入口。役割は [戦略一覧](../../src/ogami_oanda/strategy/README.md) を参照。

## `strategy/shared/contracts.py`

[ソース](../../src/ogami_oanda/strategy/shared/contracts.py)

外部SDKを知らない戦略の入力・判断・command・JSON状態APIを定義する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`StrategyQuote`](../../src/ogami_oanda/strategy/shared/contracts.py#L19) | class | A market quote supplied to a strategy without exposing a broker adapter. |
| [`StrategyInput`](../../src/ogami_oanda/strategy/shared/contracts.py#L31) | class | The broker-neutral data available for one strategy evaluation. |
| [`StrategyCommandAction`](../../src/ogami_oanda/strategy/shared/contracts.py#L42) | class | Broker-neutral source-scoped portfolio actions. |
| [`StrategyCommand`](../../src/ogami_oanda/strategy/shared/contracts.py#L51) | class | A portfolio action confined to positions owned by one strategy source. |
| [`StrategyCommand.__post_init__`](../../src/ogami_oanda/strategy/shared/contracts.py#L59) | method | 生成直後に入力の整合性確認や不変形式への変換を行う。 |
| [`StrategyDecision`](../../src/ogami_oanda/strategy/shared/contracts.py#L80) | class | Commands and order intents requested by a strategy evaluation. |
| [`TradingStrategy`](../../src/ogami_oanda/strategy/shared/contracts.py#L91) | class | Versioned plugin surface consumed by application services. |
| [`TradingStrategy.decide`](../../src/ogami_oanda/strategy/shared/contracts.py#L94) | method | 現在入力と内部状態から注文/管理commandと診断を決める。 |
| [`TradingStrategy.dump_state`](../../src/ogami_oanda/strategy/shared/contracts.py#L96) | method | 再起動へ引き継ぐ戦略状態をJSON互換形式で返す。 |
| [`TradingStrategy.load_state`](../../src/ogami_oanda/strategy/shared/contracts.py#L98) | method | 保存された戦略状態を検証して読み戻す。 |
| [`StrategyCandleProtection`](../../src/ogami_oanda/strategy/shared/contracts.py#L72) | class | Completed-candle facts for the application lifecycle policies. |
| [`strategy_data_requirements`](../../src/ogami_oanda/strategy/shared/contracts.py#L101) | function | Return validated candle requests, retaining API-v1's historical default. |

## `strategy/shared/loader.py`

[ソース](../../src/ogami_oanda/strategy/shared/loader.py)

パッケージ内の信頼済みPython/YAMLを検証・ロードし、戦略IDを計算する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`StrategyPluginError`](../../src/ogami_oanda/strategy/shared/loader.py#L21) | class | An actionable configuration error that prevents strategy startup. |
| [`LoadedStrategy`](../../src/ogami_oanda/strategy/shared/loader.py#L26) | class | ロード済み戦略・設定・内容ID・元パスをまとめた値。 |
| [`load_strategy`](../../src/ogami_oanda/strategy/shared/loader.py#L34) | function | Validate and instantiate one trusted package-local strategy plugin. |
| [`_resolve_package_path`](../../src/ogami_oanda/strategy/shared/loader.py#L69) | function / internal | 戦略パスが許可パッケージ内の実ファイルか検証する。 |
| [`_load_config`](../../src/ogami_oanda/strategy/shared/loader.py#L83) | function / internal | 戦略YAMLを文字列キーのmappingとして検証して読む。 |
| [`_load_module`](../../src/ogami_oanda/strategy/shared/loader.py#L97) | function / internal | 戦略Pythonを固有名でロードし、失敗時に登録状態を戻す。 |
| [`_validate_api`](../../src/ogami_oanda/strategy/shared/loader.py#L117) | function / internal | 戦略API版とfactoryの存在を検証する。 |
| [`_strategy_id`](../../src/ogami_oanda/strategy/shared/loader.py#L129) | function / internal | Python/YAMLの内容ハッシュから戦略IDを作る。 |
| [`_content_hash`](../../src/ogami_oanda/strategy/shared/loader.py#L133) | function / internal | ファイル内容のSHA-256を計算する。 |

## `strategy/shared/position_management/__init__.py`

[ソース](../../src/ogami_oanda/strategy/shared/position_management/__init__.py)

パッケージの入口。関連型を再公開する。

## `strategy/shared/position_management/entry_confirmation.py`

[ソース](../../src/ogami_oanda/strategy/shared/position_management/entry_confirmation.py)

STOP/LIMITのwatching状態から待機・発注・取消を判断する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`EntryAction`](../../src/ogami_oanda/strategy/shared/position_management/entry_confirmation.py#L8) | class | watchingからの待機・発注・取消の判断区分。 |
| [`EntryConfirmationState`](../../src/ogami_oanda/strategy/shared/position_management/entry_confirmation.py#L15) | class | 発注前価格監視で保持する状態。 |
| [`EntryConfirmationDecision`](../../src/ogami_oanda/strategy/shared/position_management/entry_confirmation.py#L23) | class | 発注前監視の次状態とアクション。 |
| [`EntryConfirmationPolicy`](../../src/ogami_oanda/strategy/shared/position_management/entry_confirmation.py#L30) | class | STOP/LIMITのwatching状態から待機・発注・取消を判断する。 この責任を提供するクラス。 |
| [`EntryConfirmationPolicy.decide`](../../src/ogami_oanda/strategy/shared/position_management/entry_confirmation.py#L37) | method | 現在入力と内部状態から注文/管理commandと診断を決める。 |
| [`EntryConfirmationPolicy._timeout_decision`](../../src/ogami_oanda/strategy/shared/position_management/entry_confirmation.py#L56) | method / internal | watching期限に到達した場合の判断を作る。 |
| [`EntryConfirmationPolicy._stop_decision`](../../src/ogami_oanda/strategy/shared/position_management/entry_confirmation.py#L69) | method / internal | STOPの価格監視条件から待機/発注を判断する。 |
| [`EntryConfirmationPolicy._limit_decision`](../../src/ogami_oanda/strategy/shared/position_management/entry_confirmation.py#L97) | method / internal | LIMITの反転・回復条件から待機/発注を判断する。 |

## `strategy/shared/position_management/exit_policy.py`

[ソース](../../src/ogami_oanda/strategy/shared/position_management/exit_policy.py)

注文期限と保有期限の終了条件を判定する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`ExitPolicy`](../../src/ogami_oanda/strategy/shared/position_management/exit_policy.py#L9) | class | 注文期限と保有期限の終了条件を判定する。 この責任を提供するクラス。 |
| [`ExitPolicy.should_cancel_order`](../../src/ogami_oanda/strategy/shared/position_management/exit_policy.py#L14) | method | 未約定注文の取消期限を判定する。 |
| [`ExitPolicy.should_close`](../../src/ogami_oanda/strategy/shared/position_management/exit_policy.py#L17) | method | 保有ポジションの終了条件を判定する。 |

## `strategy/shared/position_management/hedge.py`

[ソース](../../src/ogami_oanda/strategy/shared/position_management/hedge.py)

反対方向のポジションに対するヘッジ解消commandを選ぶ。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`HedgePosition`](../../src/ogami_oanda/strategy/shared/position_management/hedge.py#L7) | class | ヘッジ判断に必要なポジションの値。 |
| [`HedgeCommand`](../../src/ogami_oanda/strategy/shared/position_management/hedge.py#L14) | class | ヘッジ解消対象を表す指示。 |
| [`HedgePolicy`](../../src/ogami_oanda/strategy/shared/position_management/hedge.py#L20) | class | 反対方向のポジションに対するヘッジ解消commandを選ぶ。 この責任を提供するクラス。 |
| [`HedgePolicy.close_commands`](../../src/ogami_oanda/strategy/shared/position_management/hedge.py#L23) | method | 解消対象のヘッジポジションに対するcommandを返す。 |

## `strategy/shared/position_management/linkage.py`

[ソース](../../src/ogami_oanda/strategy/shared/position_management/linkage.py)

主注文の約定/終了に伴う連動注文への変更commandを選ぶ。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`LinkedPosition`](../../src/ogami_oanda/strategy/shared/position_management/linkage.py#L9) | class | 主注文との連動判断に必要な値。 |
| [`LinkageCommand`](../../src/ogami_oanda/strategy/shared/position_management/linkage.py#L22) | class | 連動先に適用する変更指示。 |
| [`LinkagePolicy`](../../src/ogami_oanda/strategy/shared/position_management/linkage.py#L29) | class | 主注文の約定/終了に伴う連動注文への変更commandを選ぶ。 この責任を提供するクラス。 |
| [`LinkagePolicy.on_main_filled`](../../src/ogami_oanda/strategy/shared/position_management/linkage.py#L32) | method | 主注文の約定に伴う連動commandを返す。 |
| [`LinkagePolicy.on_main_closed`](../../src/ogami_oanda/strategy/shared/position_management/linkage.py#L39) | method | 主ポジションの終了に伴う連動commandを返す。 |

## `strategy/shared/position_management/stop_loss_policy.py`

[ソース](../../src/ogami_oanda/strategy/shared/position_management/stop_loss_policy.py)

利益・経過・足情報に基づくSL変更を判断する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`StopLossAmendment`](../../src/ogami_oanda/strategy/shared/position_management/stop_loss_policy.py#L9) | class | SL変更先と適用段階を表す値。 |
| [`StopLossPolicy`](../../src/ogami_oanda/strategy/shared/position_management/stop_loss_policy.py#L15) | class | 利益・経過・足情報に基づくSL変更を判断する。 この責任を提供するクラス。 |
| [`StopLossPolicy.amended_stop_loss`](../../src/ogami_oanda/strategy/shared/position_management/stop_loss_policy.py#L20) | method | 現在条件でSL変更値を計算する。 |
| [`StopLossPolicy.next_amendment`](../../src/ogami_oanda/strategy/shared/position_management/stop_loss_policy.py#L30) | method | 設定された段階的SL変更の次の適用値を選ぶ。 |
| [`StopLossPolicy.candle_amendment`](../../src/ogami_oanda/strategy/shared/position_management/stop_loss_policy.py#L58) | method | 確定足に基づくSL変更を判断する。 |

## `strategy/original/analysis.py`

[ソース](../../src/ogami_oanda/strategy/original/analysis.py)

足の前処理・ピーク解析・候補選択・OrderIntent生成を行う純粋なoriginal処理。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`MarketAnalysisResult`](../../src/ogami_oanda/strategy/original/analysis.py#L27) | class | 解析で得た足・注文意図・候補診断をまとめた結果。 |
| [`OriginalAnalysis`](../../src/ogami_oanda/strategy/original/analysis.py#L36) | class | 市場データと指標を準備し、選択候補をOrderIntentへ変換する。 この責任を提供するクラス。 |
| [`OriginalAnalysis.__init__`](../../src/ogami_oanda/strategy/original/analysis.py#L37) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`OriginalAnalysis.analyze_frames`](../../src/ogami_oanda/strategy/original/analysis.py#L49) | method | 足の前処理・ピーク解析・候補選択・OrderIntent生成を行う純粋なoriginal処理。 |
| [`OriginalAnalysis.prepare_frame`](../../src/ogami_oanda/strategy/original/analysis.py#L112) | method | 足の前処理・ピーク解析・候補選択・OrderIntent生成を行う純粋なoriginal処理。 |
| [`OriginalAnalysis._candidate_to_intent`](../../src/ogami_oanda/strategy/original/analysis.py#L128) | method | 選択された候補をOrderIntentへ変換する。 |
| [`OriginalAnalysis._legacy_order_name`](../../src/ogami_oanda/strategy/original/analysis.py#L179) | method | 従来の規則に沿って注文名を作る。 |
| [`OriginalAnalysis._intent_metadata`](../../src/ogami_oanda/strategy/original/analysis.py#L182) | method | 候補の判断文脈をintentメタデータへ移す。 |
| [`OriginalAnalysis._pair_name`](../../src/ogami_oanda/strategy/original/analysis.py#L260) | method | 解析で使う通貨ペア名を正規化する。 |

## `strategy/original/context.py`

[ソース](../../src/ogami_oanda/strategy/original/context.py)

originalのライン候補判断へ渡す足・ピーク・RSIの文脈を構築する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`build_line_candidate_context`](../../src/ogami_oanda/strategy/original/context.py#L11) | function | Build the pure line-analysis context required by LineCandidateBuilder. |
| [`_rsi_info`](../../src/ogami_oanda/strategy/original/context.py#L70) | function | 解析文脈用のRSI情報を作る。 |
| [`_timeframe_rsi_info`](../../src/ogami_oanda/strategy/original/context.py#L79) | function | 特定時間足のRSI情報を作る。 |

## `strategy/original/parameters.yaml`

[ソース](../../src/ogami_oanda/strategy/original/parameters.yaml)

originalの明示プラグイン用pair・risk_yen・line_units設定。

## `strategy/original/strategy.py`

[ソース](../../src/ogami_oanda/strategy/original/strategy.py)

originalのAPI v1判断、データ要件、空の状態読込とfactoryを提供する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`OriginalStrategy`](../../src/ogami_oanda/strategy/original/strategy.py#L27) | class | Pure multi-frame decisions; scheduling and broker state stay with callers. |
| [`OriginalStrategy.__init__`](../../src/ogami_oanda/strategy/original/strategy.py#L33) | method | 依存・設定を受け取り初期状態を構築する。 |
| [`OriginalStrategy.decide`](../../src/ogami_oanda/strategy/original/strategy.py#L57) | method | 共通市場入力から戦略判断を返す。 |
| [`OriginalStrategy.dump_state`](../../src/ogami_oanda/strategy/original/strategy.py#L92) | method | JSON互換の戦略状態を返す。 |
| [`OriginalStrategy.load_state`](../../src/ogami_oanda/strategy/original/strategy.py#L95) | method | 保存された戦略状態を検証して読み込む。 |
| [`create_strategy`](../../src/ogami_oanda/strategy/original/strategy.py#L101) | function | originalのAPI v1判断、データ要件、空の状態読込とfactoryを提供する。 |
