# infrastructure コード参照

[コード参照の入口](README.md) / [構成](../structure.md)

## `infrastructure/__init__.py`

[ソース](../../src/ogami_oanda/infrastructure/__init__.py)

パッケージの入口。初期化時に業務処理を開始しない。

## `infrastructure/config/__init__.py`

[ソース](../../src/ogami_oanda/infrastructure/config/__init__.py)

パッケージの入口。関連型を再公開する。

## `infrastructure/config/legacy_tokens.py`

[ソース](../../src/ogami_oanda/infrastructure/config/legacy_tokens.py)

従来tokensオブジェクトの属性を現行AppSettingsへ変換する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`settings_from_tokens`](../../src/ogami_oanda/infrastructure/config/legacy_tokens.py#L14) | function | Adapt the root token module at the infrastructure boundary. |

## `infrastructure/config/loader.py`

[ソース](../../src/ogami_oanda/infrastructure/config/loader.py)

YAMLと環境変数を型付き設定へ読み込み、必要項目を検証する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`_environment_value`](../../src/ogami_oanda/infrastructure/config/loader.py#L18) | function / internal | 環境変数プレースホルダーを値へ置換する。 |
| [`_boolean_value`](../../src/ogami_oanda/infrastructure/config/loader.py#L26) | function / internal | boolおよび文字列形式のbool設定を解釈する。 |
| [`load_settings`](../../src/ogami_oanda/infrastructure/config/loader.py#L39) | function | YAMLと環境変数から設定を読み取り、必要項目を検証する。 |
| [`_validate_settings`](../../src/ogami_oanda/infrastructure/config/loader.py#L99) | function / internal | 口座必須値・環境・ペア・枠合計を検証する。 |

## `infrastructure/config/models.py`

[ソース](../../src/ogami_oanda/infrastructure/config/models.py)

口座・通知・保存先・全体設定の型を定義する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`RuntimeAccountConfig`](../../src/ogami_oanda/infrastructure/config/models.py#L11) | class | 認証・環境・ヘッジ/live有効化などの実行口座設定。 |
| [`NotificationSettings`](../../src/ogami_oanda/infrastructure/config/models.py#L21) | class | ペア別と検証用通知先の不変設定。 |
| [`NotificationSettings.__post_init__`](../../src/ogami_oanda/infrastructure/config/models.py#L25) | method | 生成直後に入力の整合性確認や不変形式への変換を行う。 |
| [`PathSettings`](../../src/ogami_oanda/infrastructure/config/models.py#L30) | class | 結果・キャッシュ・履歴・状態・ログの保存先設定。 |
| [`AppSettings`](../../src/ogami_oanda/infrastructure/config/models.py#L39) | class | 口座・業務・通知・保存先をまとめた設定。 |
| [`AppSettings.__post_init__`](../../src/ogami_oanda/infrastructure/config/models.py#L45) | method | 生成直後に入力の整合性確認や不変形式への変換を行う。 |
| [`AppSettings.account`](../../src/ogami_oanda/infrastructure/config/models.py#L48) | method | 指定名の口座設定を取り出す。 |

## `infrastructure/logging/__init__.py`

[ソース](../../src/ogami_oanda/infrastructure/logging/__init__.py)

パッケージの入口。関連型を再公開する。

## `infrastructure/logging/daily_file.py`

[ソース](../../src/ogami_oanda/infrastructure/logging/daily_file.py)

stdout/stderrを日次ログへ複製し、古いログをgzip圧縮する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`DailyFileTee`](../../src/ogami_oanda/infrastructure/logging/daily_file.py#L18) | class | stdout/stderrを日次ログへ複製し、古いログをgzip圧縮する。 この責任を提供するクラス。 |
| [`DailyFileTee.__init__`](../../src/ogami_oanda/infrastructure/logging/daily_file.py#L19) | method | 依存オブジェクト・設定を受け取り、インスタンスの初期状態を構築する。 |
| [`DailyFileTee.write`](../../src/ogami_oanda/infrastructure/logging/daily_file.py#L37) | method | 出力文字列を元のstreamと日次ログへ複製する。 |
| [`DailyFileTee.flush`](../../src/ogami_oanda/infrastructure/logging/daily_file.py#L43) | method | streamとログのバッファをflushする。 |
| [`DailyFileTee.close_log_file`](../../src/ogami_oanda/infrastructure/logging/daily_file.py#L48) | method | 開いているログファイルを閉じる。 |
| [`DailyFileTee.isatty`](../../src/ogami_oanda/infrastructure/logging/daily_file.py#L55) | method | 元のstreamの端末属性を返す。 |
| [`DailyFileTee.fileno`](../../src/ogami_oanda/infrastructure/logging/daily_file.py#L58) | method | 元のstreamのファイル記述子を返す。 |
| [`DailyFileTee.encoding`](../../src/ogami_oanda/infrastructure/logging/daily_file.py#L62) | method | 元のstreamの文字コードを返す。 |
| [`DailyFileTee.errors`](../../src/ogami_oanda/infrastructure/logging/daily_file.py#L66) | method | 元のstreamの文字コードエラー処理を返す。 |
| [`DailyFileTee.__getattr__`](../../src/ogami_oanda/infrastructure/logging/daily_file.py#L69) | method | 未定義属性を元のstreamへ委譲する。 |
| [`DailyFileTee._open_log_file`](../../src/ogami_oanda/infrastructure/logging/daily_file.py#L72) | method / internal | 現在日付に対応するログファイルを開く。 |
| [`setup_daily_file_logging`](../../src/ogami_oanda/infrastructure/logging/daily_file.py#L96) | function | stdout/stderrに日次ログへの複製を設定する。 |
| [`compress_old_daily_logs`](../../src/ogami_oanda/infrastructure/logging/daily_file.py#L123) | function | 過去日付のログをgzip圧縮する。 |
| [`_current_jst_datetime`](../../src/ogami_oanda/infrastructure/logging/daily_file.py#L148) | function / internal | 日次ログ処理用のJST日時を取得する。 |
| [`_date_from_log_path`](../../src/ogami_oanda/infrastructure/logging/daily_file.py#L154) | function / internal | ログファイル名から日付を取り出す。 |
| [`_gzip_log_file`](../../src/ogami_oanda/infrastructure/logging/daily_file.py#L162) | function / internal | 指定ログをgzipへ圧縮する。 |

## `infrastructure/runtime/__init__.py`

[ソース](../../src/ogami_oanda/infrastructure/runtime/__init__.py)

パッケージの入口。関連型を再公開する。

## `infrastructure/runtime/clock.py`

[ソース](../../src/ogami_oanda/infrastructure/runtime/clock.py)

JSTの実時計をClock契約へ提供する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`SystemClock`](../../src/ogami_oanda/infrastructure/runtime/clock.py#L9) | class | JSTの実時計をClock契約へ提供する。 この責任を提供するクラス。 |
| [`SystemClock.now`](../../src/ogami_oanda/infrastructure/runtime/clock.py#L12) | method | 現在時刻を返す。 |

## `infrastructure/runtime/polling_loop.py`

[ソース](../../src/ogami_oanda/infrastructure/runtime/polling_loop.py)

単調時計とsleepを使って固定間隔でtickを実行する。

| 定義 | 種別 | 役割 |
| --- | --- | --- |
| [`Sleeper`](../../src/ogami_oanda/infrastructure/runtime/polling_loop.py#L8) | class | ポーリング待機を差し替えるための呼出契約。 |
| [`Sleeper.__call__`](../../src/ogami_oanda/infrastructure/runtime/polling_loop.py#L9) | method | 指定秒数の待機を提供する注入可能な契約。 |
| [`system_sleep`](../../src/ogami_oanda/infrastructure/runtime/polling_loop.py#L12) | function | 実環境で指定秒数待つ。 |
| [`PollingLoop`](../../src/ogami_oanda/infrastructure/runtime/polling_loop.py#L20) | class | Infrastructure-owned fixed-interval loop around a single use-case tick. |
| [`PollingLoop.run`](../../src/ogami_oanda/infrastructure/runtime/polling_loop.py#L27) | method | 単調時計の締切でtickを繰り返す。有限回数にも対応し、無制限時は結果を蓄積しない。 |
