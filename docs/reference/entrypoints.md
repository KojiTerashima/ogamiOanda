# entrypoints コード参照

[コード参照の入口](README.md) / [構成](../structure.md)

## `entrypoints/__init__.py`

[ソース](../../src/ogami_oanda/entrypoints/__init__.py)

パッケージの入口。初期化時に業務処理を開始しない。

## `entrypoints/live.py`

[ソース](../../src/ogami_oanda/entrypoints/live.py)

設定から依存を構築し、組込み/プラグインのtick・復旧・CLIを提供する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`LiveFailure`](../../src/ogami_oanda/entrypoints/live.py#L88) | class | 外部障害の分類と再試行情報。 |
| [`LiveRunResult`](../../src/ogami_oanda/entrypoints/live.py#L98) | class | 1 tickの解析・採用結果・スキップ・イベント・失敗の集約。 |
| [`LiveRunObserver`](../../src/ogami_oanda/entrypoints/live.py#L111) | class | 完了tickと失敗を受け取る表示/監視契約。 |
| [`LiveRunObserver.on_result`](../../src/ogami_oanda/entrypoints/live.py#L112) | method | 完了したtickの結果を表示/観測する。 |
| [`LiveRunObserver.on_error`](../../src/ogami_oanda/entrypoints/live.py#L114) | method | tickの失敗と再試行情報を表示/観測する。 |
| [`_notify_observer_result`](../../src/ogami_oanda/entrypoints/live.py#L117) | function / internal | 結果observerがあれば完了tickを通知する。 |
| [`_notify_observer_error`](../../src/ogami_oanda/entrypoints/live.py#L133) | function / internal | エラーobserverがあれば失敗を通知する。 |
| [`_run_forever_with_observer`](../../src/ogami_oanda/entrypoints/live.py#L144) | function / internal | 対応するrunnerへobserverを渡して継続実行する。 |
| [`_configured_log_dir`](../../src/ogami_oanda/entrypoints/live.py#L167) | function / internal | 設定からログ保存先を取り出す。 |
| [`_collect_runtime_events`](../../src/ogami_oanda/entrypoints/live.py#L175) | function / internal | Attach and clear the current tick's transient events on a result. |
| [`LiveApplication`](../../src/ogami_oanda/entrypoints/live.py#L186) | class | 設定から依存を構築し、組込み/プラグインのtick・復旧・CLIを提供する。 この責任を提供するクラス。 |
| [`LiveApplication.__init__`](../../src/ogami_oanda/entrypoints/live.py#L187) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`LiveApplication.run_once`](../../src/ogami_oanda/entrypoints/live.py#L223) | method | 1 tickのスケジュール・判断・状態同期を実行する。 |
| [`LiveApplication.run_forever`](../../src/ogami_oanda/entrypoints/live.py#L331) | method | 固定間隔でtickを継続実行する。 |
| [`LiveApplication.run_resilient_once`](../../src/ogami_oanda/entrypoints/live.py#L355) | method | 既知の一時障害・認証停止を扱いながら1 tickを実行する。 |
| [`LiveApplication._recover_authorization`](../../src/ogami_oanda/entrypoints/live.py#L391) | method / internal | 認証を再確認し、口座条件・状態照合を経て再開可否を決める。 |
| [`LiveApplication._authorization_failure_result`](../../src/ogami_oanda/entrypoints/live.py#L397) | method / internal | 認証停止を表す安全なtick結果を作る。 |
| [`LiveApplication._transient_failure_result`](../../src/ogami_oanda/entrypoints/live.py#L416) | method / internal | 一時障害と再試行を表すtick結果を作る。 |
| [`LiveApplication._schedule_broker_backoff`](../../src/ogami_oanda/entrypoints/live.py#L434) | method / internal | 次のブローカー再試行時刻と待機幅を設定する。 |
| [`LiveApplication._reset_broker_backoff`](../../src/ogami_oanda/entrypoints/live.py#L448) | method / internal | 回復後の再試行待機状態を解除する。 |
| [`LiveApplication._empty_result`](../../src/ogami_oanda/entrypoints/live.py#L452) | method / internal | 解析/登録を行わないtick結果を作る。 |
| [`LiveApplication._quote`](../../src/ogami_oanda/entrypoints/live.py#L466) | method / internal | tick内で共有する価格quoteを取得する。 |
| [`LiveApplication._analyze`](../../src/ogami_oanda/entrypoints/live.py#L469) | method / internal | 市場解析を呼び出して結果を取得する。 |
| [`LiveApplication._sync_positions`](../../src/ogami_oanda/entrypoints/live.py#L472) | method / internal | 市場情報を使ってポジション同期を行う。 |
| [`LiveApplication._candle_input`](../../src/ogami_oanda/entrypoints/live.py#L489) | method / internal | SL判断へ渡す確定足情報を作る。 |
| [`StrategyLiveApplication`](../../src/ogami_oanda/entrypoints/live.py#L507) | class | Evaluate one trusted strategy plugin on every open-market tick. |
| [`StrategyLiveApplication.__init__`](../../src/ogami_oanda/entrypoints/live.py#L510) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`StrategyLiveApplication.run_once`](../../src/ogami_oanda/entrypoints/live.py#L560) | method | 1 tickのスケジュール・判断・状態同期を実行する。 |
| [`StrategyLiveApplication.run_forever`](../../src/ogami_oanda/entrypoints/live.py#L714) | method | 固定間隔でtickを継続実行する。 |
| [`StrategyLiveApplication.run_resilient_once`](../../src/ogami_oanda/entrypoints/live.py#L737) | method | 既知の一時障害・認証停止を扱いながら1 tickを実行する。 |
| [`StrategyLiveApplication._recover_authorization`](../../src/ogami_oanda/entrypoints/live.py#L773) | method / internal | 認証を再確認し、口座条件・状態照合を経て再開可否を決める。 |
| [`StrategyLiveApplication._authorization_failure_result`](../../src/ogami_oanda/entrypoints/live.py#L779) | method / internal | 認証停止を表す安全なtick結果を作る。 |
| [`StrategyLiveApplication._transient_failure_result`](../../src/ogami_oanda/entrypoints/live.py#L798) | method / internal | 一時障害と再試行を表すtick結果を作る。 |
| [`StrategyLiveApplication._schedule_broker_backoff`](../../src/ogami_oanda/entrypoints/live.py#L816) | method / internal | 次のブローカー再試行時刻と待機幅を設定する。 |
| [`StrategyLiveApplication._reset_broker_backoff`](../../src/ogami_oanda/entrypoints/live.py#L830) | method / internal | 回復後の再試行待機状態を解除する。 |
| [`StrategyLiveApplication._empty_result`](../../src/ogami_oanda/entrypoints/live.py#L834) | method / internal | 解析/登録を行わないtick結果を作る。 |
| [`StrategyLiveApplication._load_strategy_state_once`](../../src/ogami_oanda/entrypoints/live.py#L848) | method / internal | 初回に保存された戦略状態をロードする。 |
| [`StrategyLiveApplication._strategy_positions`](../../src/ogami_oanda/entrypoints/live.py#L868) | method / internal | 対象戦略が所有するポジションを選ぶ。 |
| [`StrategyLiveApplication._entry_safety_reasons`](../../src/ogami_oanda/entrypoints/live.py#L888) | method / internal | 新規注文を抑止する条件と理由を集める。 |
| [`StrategyLiveApplication._quote_is_fresh`](../../src/ogami_oanda/entrypoints/live.py#L909) | method / internal | quoteの時刻が新規判断に十分新しいか確認する。 |
| [`StrategyLiveApplication._skipped`](../../src/ogami_oanda/entrypoints/live.py#L931) | method / internal | スキップ理由を含むtick結果を作る。 |
| [`_OfflineSmokeMarketData`](../../src/ogami_oanda/entrypoints/live.py#L939) | class / internal | 固定quoteを返すsmoke専用の市場実装。 |
| [`_OfflineSmokeMarketData.__init__`](../../src/ogami_oanda/entrypoints/live.py#L940) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`_OfflineSmokeMarketData.current_quote`](../../src/ogami_oanda/entrypoints/live.py#L944) | method | 同一tickで共有するquoteを取得する。 |
| [`_OfflineSmokeAnalysis`](../../src/ogami_oanda/entrypoints/live.py#L950) | class / internal | 外部市場を使わないsmoke専用解析。 |
| [`_OfflineSmokeAnalysis.analyze`](../../src/ogami_oanda/entrypoints/live.py#L951) | method | 固定の空MarketAnalysisResultを返す。市場取得・候補計算を行わない。 |
| [`_OfflineSmokePortfolio`](../../src/ogami_oanda/entrypoints/live.py#L969) | class / internal | 外部変更しないsmoke専用ポートフォリオ。 |
| [`_OfflineSmokePortfolio.sync_all`](../../src/ogami_oanda/entrypoints/live.py#L970) | method | 固定の空同期結果を返す。ポジションや外部状態を変更しない。 |
| [`_OfflineSmokePortfolio.register_plans`](../../src/ogami_oanda/entrypoints/live.py#L973) | method | 固定の空RegistrationResultを返す。注文を登録・送信しない。 |
| [`build_offline_smoke_application`](../../src/ogami_oanda/entrypoints/live.py#L982) | function | Build a no-network, no-persistence CLI packaging smoke composition. |
| [`build_live_application`](../../src/ogami_oanda/entrypoints/live.py#L1005) | function | 設定から組込みライン戦略のlive依存一式を構築する。 |
| [`build_strategy_live_application`](../../src/ogami_oanda/entrypoints/live.py#L1180) | function | Compose a live runner for an already validated trusted strategy. |
| [`main`](../../src/ogami_oanda/entrypoints/live.py#L1348) | function | 引数を検証し、smoke・組込み・戦略プラグインの経路を選び実行する。 |
| [`LiveApplication._register_plans`](../../src/ogami_oanda/entrypoints/live.py#L328) | method | 共通strategy契約の型・設定を提供する。 |
| [`StrategyLiveApplication._register_plans`](../../src/ogami_oanda/entrypoints/live.py#L854) | method | 共通strategy契約の型・設定を提供する。 |
| [`StrategyLiveApplication._analyze`](../../src/ogami_oanda/entrypoints/live.py#L859) | method | 共通strategy契約の型・設定を提供する。 |

## `entrypoints/live_console.py`

[ソース](../../src/ogami_oanda/entrypoints/live_console.py)

tickと取引イベント・候補診断・失敗をコンソールへ整形表示する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`format_candidate_diagnostics`](../../src/ogami_oanda/entrypoints/live_console.py#L21) | function | 候補件数・不採用理由を表示文字列へ整形する。 |
| [`ConsoleLiveReporter`](../../src/ogami_oanda/entrypoints/live_console.py#L41) | class | Render one completed live tick and its typed runtime events. The reporter intentionally depends only on the application-shaped object passed by the two production entrypoints. This keeps the domain and service layers free of presentation concerns and makes the output easy to capture in contract tests. |
| [`ConsoleLiveReporter.__init__`](../../src/ogami_oanda/entrypoints/live_console.py#L50) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`ConsoleLiveReporter.on_result`](../../src/ogami_oanda/entrypoints/live_console.py#L66) | method | 完了したtickの結果を表示/観測する。 |
| [`ConsoleLiveReporter.on_error`](../../src/ogami_oanda/entrypoints/live_console.py#L243) | method | tickの失敗と再試行情報を表示/観測する。 |
| [`ConsoleLiveReporter._print_event`](../../src/ogami_oanda/entrypoints/live_console.py#L250) | method / internal | 型付き取引イベントを1行に整形表示する。 |
| [`ConsoleLiveReporter._print_plan`](../../src/ogami_oanda/entrypoints/live_console.py#L342) | method / internal | dry-run計画を表示する。 |
| [`ConsoleLiveReporter._print_order_from_plan`](../../src/ogami_oanda/entrypoints/live_console.py#L349) | method / internal | 注文計画から表示用注文情報を作る。 |
| [`ConsoleLiveReporter._print_command`](../../src/ogami_oanda/entrypoints/live_console.py#L352) | method / internal | 戦略commandの実行/計画を表示する。 |
| [`ConsoleLiveReporter._order_fields`](../../src/ogami_oanda/entrypoints/live_console.py#L379) | method / internal | 注文表示に使う項目を組み立てる。 |
| [`ConsoleLiveReporter._plan_fields`](../../src/ogami_oanda/entrypoints/live_console.py#L400) | method / internal | 計画表示に使う項目を組み立てる。 |
| [`ConsoleLiveReporter._pair`](../../src/ogami_oanda/entrypoints/live_console.py#L411) | method / internal | 表示対象のペアを返す。 |
| [`ConsoleLiveReporter._now`](../../src/ogami_oanda/entrypoints/live_console.py#L426) | method / internal | 注入された時計から表示用時刻を取得する。 |
| [`ConsoleLiveReporter._timestamp`](../../src/ogami_oanda/entrypoints/live_console.py#L437) | method / internal | 表示用時刻文字列を作る。 |
| [`ConsoleLiveReporter._number`](../../src/ogami_oanda/entrypoints/live_console.py#L441) | method / internal | 数値を表示精度に整形する。 |
| [`ConsoleLiveReporter._value`](../../src/ogami_oanda/entrypoints/live_console.py#L449) | method / internal | 省略値を含む表示項目を整形する。 |
| [`ConsoleLiveReporter._retry_text`](../../src/ogami_oanda/entrypoints/live_console.py#L453) | method / internal | 再試行待機時間を表示文字列にする。 |
| [`ConsoleLiveReporter._mode_field`](../../src/ogami_oanda/entrypoints/live_console.py#L460) | method / internal | dry-run/通常実行の表示区分を作る。 |
| [`ConsoleLiveReporter._print`](../../src/ogami_oanda/entrypoints/live_console.py#L464) | method / internal | 整形済みの1行をflush付きで出力する。 |

## `entrypoints/practice_acceptance.py`

[ソース](../../src/ogami_oanda/entrypoints/practice_acceptance.py)

practice受入専用CLIのゲート確認・サービス構築・レポート保存を行う。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`build_service`](../../src/ogami_oanda/entrypoints/practice_acceptance.py#L28) | function | practice受入専用の依存を組み立てる。 |
| [`main`](../../src/ogami_oanda/entrypoints/practice_acceptance.py#L45) | function | practice専用安全ゲートを確認し、受入・後処理・レポート保存を実行する。 |
| [`_strategy_pair`](../../src/ogami_oanda/entrypoints/practice_acceptance.py#L139) | function / internal | 設定された戦略の通貨ペアを取得する。 |
| [`_serialize_operations`](../../src/ogami_oanda/entrypoints/practice_acceptance.py#L148) | function / internal | 受入操作の結果をレポート用形式へ変換する。 |
| [`_write_report`](../../src/ogami_oanda/entrypoints/practice_acceptance.py#L160) | function / internal | 受入レポートをJSONへ保存する。 |

## `entrypoints/backtest.py`

[ソース](../../src/ogami_oanda/entrypoints/backtest.py)

戦略と期間を選択し、認証付きfetchまたはオフラインrunを構築するCLI。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`source_hash`](../../src/ogami_oanda/entrypoints/backtest.py#L25) | function | 戦略と期間を選択し、認証付きfetchまたはオフラインrunを構築するCLI。 |
| [`select_strategy`](../../src/ogami_oanda/entrypoints/backtest.py#L34) | function | 戦略と期間を選択し、認証付きfetchまたはオフラインrunを構築するCLI。 |
| [`parser`](../../src/ogami_oanda/entrypoints/backtest.py#L69) | function | 戦略と期間を選択し、認証付きfetchまたはオフラインrunを構築するCLI。 |
| [`_fetch`](../../src/ogami_oanda/entrypoints/backtest.py#L103) | function | 戦略と期間を選択し、認証付きfetchまたはオフラインrunを構築するCLI。 |
| [`_run`](../../src/ogami_oanda/entrypoints/backtest.py#L132) | function | 戦略と期間を選択し、認証付きfetchまたはオフラインrunを構築するCLI。 |
| [`main`](../../src/ogami_oanda/entrypoints/backtest.py#L168) | function | 戦略と期間を選択し、認証付きfetchまたはオフラインrunを構築するCLI。 |

## `entrypoints/backtest_run.py`

[ソース](../../src/ogami_oanda/entrypoints/backtest_run.py)

仮想broker・再生市場・既存ポートフォリオ・共通strategy評価を接続する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`release_simulation_history`](../../src/ogami_oanda/entrypoints/backtest_run.py#L47) | function | Retain terminal evidence for current slots, not every historical trade. |
| [`run_backtest`](../../src/ogami_oanda/entrypoints/backtest_run.py#L81) | function | 仮想broker・再生市場・既存ポートフォリオ・共通strategy評価を接続する。 |
| [`runtime_versions`](../../src/ogami_oanda/entrypoints/backtest_run.py#L32) | function | 認証設定を読まずPython・OS・CPU・通常依存の版を取得する。 |


## `entrypoints/main_analysis.py`

[ソース](../../src/ogami_oanda/entrypoints/main_analysis.py)

originalの本番組立で原文実行器を注入する。明示された解析・候補生成の依存は維持する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`bind_main_analysis`](../../src/ogami_oanda/entrypoints/main_analysis.py#L25) | function | 実行器を一度注入し、live/backtestのモードへ接続する。 |
| [`validate_analysis_selection`](../../src/ogami_oanda/entrypoints/main_analysis.py#L8) | function | 明示した解析名に戦略が対応していることを検証する。 |
| [`analysis_strategy_id`](../../src/ogami_oanda/entrypoints/main_analysis.py#L16) | function | lineの既存識別子を維持し、ほかの解析をチェックポイント上で区別する。 |
