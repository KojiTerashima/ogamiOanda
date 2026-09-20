# 操作ガイド

[索引](README.md) / [仕様](specification.md)

コマンドはリポジトリのルートで実行します。Python 3.10以上が必要です。
以下の外部接続を伴う例は運用手順の説明であり、自動実行の許可ではありません。

## 開発環境とオフライン確認

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/ogami-oanda-live --help
.venv/bin/ogami-oanda-live --offline-smoke --dry-run --once
```

インストールはパッケージ取得を伴う場合があります。最後のsmokeは設定を読み込まず、
OANDA・Discord・CSV adapterを作らず、固定データで1 tickを確認します。
Pythonモジュールとしては `.venv/bin/python -m ogami_oanda.entrypoints.live` でも同じCLIに入れます。

## 設定

公開テンプレート [settings.example.yaml](../config/settings.example.yaml) を基に
Git管理外の `config/settings.yaml` を用意します。`${変数名}` は環境変数で置換されます。
実値をソース・テスト・ドキュメントへ記録しません。

| セクション・キー | 役割 |
| --- | --- |
| `accounts.<name>` | `--account` で選ぶ接続設定。テンプレートの名前は `practice` |
| `account_id`, `access_token`, `environment` | 接続先の認証と `practice` / `live` の区別 |
| `client_extensions_enabled` | クライアント拡張の使用可否。既定false |
| `require_hedging` | ヘッジ機能の要求。既定true |
| `live_trading_enabled` | live環境の明示的な有効化。既定false |
| `trading.default_pair` | 省略時の通貨ペア |
| `trading.spread_limit_pips` | 通貨ペア別の新規注文スプレッド上限（pips） |
| `trading.line_units`, `risk_yen` | 組込みライン戦略の数量・リスク計算設定 |
| `trading.max_positions` | 全枠数。既定15 |
| `normal_slot_count`, `mid_slot_count`, `high_slot_count` | 優先度別枠。既定6・8・1、合計は全枠数と一致させる |
| `mid_priority_threshold`, `high_priority_threshold` | 優先度の境界。既定10・100 |
| `notifications.strategy_pair_webhooks.<strategy>.<pair>` | strategyと通貨ペア別の通常通知先 |
| `notifications.inspection_webhook` | 全strategy共通の検証用通知先 |
| `paths.result_dir`, `cache_dir` | 結果・キャッシュ用の設定パス |
| `paths.history_file` | 決済履歴CSV |
| `paths.position_state_dir` | 注文・ポジション・未確定操作のチェックポイント |
| `paths.log_dir` | stdout/stderrを保存する日次ログディレクトリ |

相対パスは実行時の作業ディレクトリを基準にします。CLIの `--account` 既定値は `primary` なので、
公開テンプレートを使う例では必ず `--account practice` を指定しています。
トークン変更は実行中プロセスへ自動反映されません。再起動の扱いは
[復旧と構築の詳細](architecture-migration.md) を参照してください。

### スプレッド上限

`config/settings.yaml`の既存の`trading`へ次の項目を追加できます。
値は現行の既定値です。必要な通貨ペアだけ指定できます。

```yaml
trading:
  default_pair: USD_JPY
  spread_limit_pips:
    USD_JPY: 1.1
    EUR_USD: 1.5
    AUD_USD: 1.8
```

未指定のペアはUSD_JPY=1.1、EUR_USD=1.5、AUD_USD=1.8 pipsを使用します。
有限の非負数を指定してください。文字列・真偽値・null・負数・無限値・NaN・未知のペアはエラーです。
0はスプレッドゼロのみ許可し、制限解除の指定ではありません。
上限と等しい価格差は許可し、価格桁への丸め方は従来と同じです。

上限はoriginal・Matcha・既存プラグイン共通です。liveとpractice受入コマンドに反映されます。
設定は起動時に確定し、変更の反映には再起動が必要です。
スプレッド超過時もポジション管理を継続し、originalの初回解析例外を維持します。
バックテストで同じ設定を使う場合は、[再生コマンド](backtest.md)に`--config`を指定してください。

## Discord通知の設定と移行

通常の注文・約定・拒否・結果不明・決済・隔離通知は、起動したstrategyと通知対象の通貨ペアに対応するWebhookへ送信します。

```yaml
notifications:
  strategy_pair_webhooks:
    original:
      USD_JPY: ${DISCORD_ORIGINAL_USD_JPY_WEBHOOK}
      EUR_USD: ${DISCORD_ORIGINAL_EUR_USD_WEBHOOK}
      AUD_USD: ${DISCORD_ORIGINAL_AUD_USD_WEBHOOK}
    matcha:
      USD_JPY: ${DISCORD_MATCHA_USD_JPY_WEBHOOK}
  inspection_webhook: ${DISCORD_INSPECTION_WEBHOOK}
```

`--strategy`省略時は`original`、`--strategy matcha`は`matcha`を使用します。
originalの`--analysis line`と`--analysis resistance_breakout`は同じ通知設定を共有します。
`--strategy-py`で明示指定した場合は、解決済みPythonファイルの`strategy/`配下の先頭ディレクトリ名を使います。
例えば`strategy/matcha/strategy.py`は`matcha`、`strategy/custom/variant/strategy.py`は`custom`です。
`strategy/`直下の`custom.py`は`custom`となり、YAMLファイル名や内容ハッシュは通知先に影響しません。
Python APIの`build_strategy_live_application`を直接使う場合は`notification_strategy_name`で指定します。省略時の通常通知は送信されません。

組み合わせが未設定、空文字、または参照する環境変数が未定義なら通常通知は送信されません。
旧`pair_webhooks`が残っていてもフォールバックしません。検証通知は従来どおり共通の`inspection_webhook`を使います。
通知本文と通信失敗時の取引継続動作は従来どおりです。同一通知経路の連続同文は2回まで送り、他のペアへの通知とは独立して重複を抑止します。

既存設定からは、次の手順で移行します。

1. 非公開の`config/settings.yaml`で、通知が必要なstrategy・通貨ペアを`strategy_pair_webhooks`に追加する。
2. 対応する環境変数を設定する。従来と同じDiscordチャンネルを使う場合は既存のWebhookを再利用できる。
3. 不要になった`pair_webhooks`を削除し、通常の運用手順でプロセスを再起動して設定を反映する。

**旧`pair_webhooks`だけのYAML設定では、通常通知が送信されなくなります。**
`main_exe.py`などの互換スクリプトと`send_notice.line_send()`が`tokens`経由で使うペア別通知は従来どおり動作します。
通知用strategy名は復旧用strategy IDとは独立しており、チェックポイントの形式や同一口座・同一ペアの複数strategy同時稼働の制約は変わりません。

## live CLI

外部読み取りを許可して1回解析する例:

```sh
.venv/bin/ogami-oanda-live   --config config/settings.yaml --account practice --pair USD_JPY   --dry-run --once --trace-candidates
```

| 引数 | 動作 |
| --- | --- |
| `--config PATH` / `--settings PATH` | 設定ファイル。smoke以外で必須 |
| `--account NAME` | 接続設定名。既定 `primary` |
| `--strategy {original,matcha}` | 起動する戦略。省略時original。明示Python/YAMLとの併用不可 |
| `--analysis {line,resistance_breakout}` | originalで使用するmain解析。省略時line。組込みoriginalのプラグイン起動にも対応。Matcha・非対応プラグイン・offline smokeとの併用不可 |
| `--main-analysis-dir PATH` | originalの解析コードを直接読むmainディレクトリ。既定 `../main`。詳細は[main解析ガイド](main-analysis.md) |
| `--pair PAIR` | `USD_JPY`, `EUR_USD`, `AUD_USD`。未指定時は構築処理の設定に従う |
| `--dry-run` | 分析を行い、発注・取消・決済・保護変更・起動取消を抑止する。通常は外部読み取りあり |
| `--once` | 1 tickで終了。単独指定では発注を抑止しない |
| `--offline-smoke` | 外部接続・設定不要の固定データ確認。`--dry-run --once` が必須 |
| `--trace-candidates` | 組込みライン候補数・不採用理由を追加表示 |
| `--cancel-pending-on-start` | 起動時の未約定取消を明示的に要求する。操作を伴う運用オプション |
| `--strategy-py PATH`, `--strategy-yaml PATH` | 信頼済み戦略のPython/YAML。必ず両方指定。smokeとの併用不可 |

`--once` を外すと固定間隔ループを継続します。
`--dry-run` を外すと注文可能な経路になります。practice/liveの発注・取消・決済は
実行直前の明示的承認を必要とします。

従来の `main_exe*.py` は互換起動口です。特に `main_exe.py` は従来の口座選択と
起動取消の挙動を引き継ぐため、新規の操作手順は引数が明示できるCLIを使います。
旧ルートの手動検証スクリプトは退役済みです。現在のpytestは `tests/` を収集します。

## 戦略の選択と継続ループ

[戦略ディレクトリの一覧](../src/ogami_oanda/strategy/README.md) に、起動名と専用/共用の所有区分をまとめています。
`original/` が従来のライン戦略、`matcha/` がMatcha、`shared/` が共用です。
ループはentrypointが担当し、以下のどちらも `--once` を付けなければ継続します。
通常dry-runなのでOANDAへの読み取り通信を伴います。

```sh
.venv/bin/ogami-oanda-live --strategy original --config config/settings.yaml --account practice --pair USD_JPY --dry-run
.venv/bin/ogami-oanda-live --strategy matcha --config config/settings.yaml --account practice --pair USD_JPY --dry-run
```

`--strategy` 省略時はoriginal。sharedは起動対象ではありません。
名前指定のMatchaはインストール先から本体/YAMLを解決するので、作業ディレクトリに依存しません。
`--strategy matcha` とoffline-smokeは併用できません。

## Matcha戦略（明示パス指定）

外部読み取りを許可して同梱戦略を1回評価する例:

```sh
.venv/bin/ogami-oanda-live   --config config/settings.yaml --account practice --pair USD_JPY   --strategy-py src/ogami_oanda/strategy/matcha/strategy.py   --strategy-yaml src/ogami_oanda/strategy/matcha/parameters.yaml   --dry-run --once
```

両ファイルとも `src/ogami_oanda/strategy/` 内の実ファイルに解決される必要があります。
明示パス指定と `--strategy` は併用しません。旧 `strategy/matcha_oanda.py` と
`strategy/matcha_param2019_oanda.yaml` のファイルパスは、新しい `matcha/` 内のパスへ更新してください。
Pythonモジュールは実行されるため信頼済みコードを使用します。
`STRATEGY_API_VERSION = 1`、`create_strategy(config)`、
`decide(input)` / `dump_state()` / `load_state(state)` が契約です。
内容ハッシュが戦略識別子になり、状態チェックポイントにも対応づけられます。
同梱YAMLの対応範囲と数量・価格・遅延の意味は [戦略仕様](specification.md) を参照してください。

## 出力と復旧

履歴の取得・オフライン再生は専用の`ogami-oanda-backtest fetch/run`を使用します。
操作例・保存形式・約定の近似・結果の読み方は[バックテストガイド](backtest.md)を参照してください。
`run`は認証設定不要です。

継続実行時は `[TICK]` と、`[ORDER]`, `[FILL]`, `[TP]`, `[LC]`, `[LC_UPDATE]`,
`[CANCEL]`, `[REJECT]` 等のイベントを表示します。dry-runは `DRY_RUN` / `PLAN` で区別します。
`--once` は採用数・不採用理由・計画名を1行で返します。
ログは `paths.log_dir` に日次保存され、過去分は圧縮されます。
履歴CSVと状態JSONは役割が異なり、両方を保持します。

一時通信障害はバックオフ、認証失敗は停止・再検証、結果不明の操作は照合対象になります。
起動時に `QUARANTINED` となった場合、状態ファイルを消してやり直す操作は復旧手順ではありません。
[詳細な復旧契約](architecture-migration.md) と [現行仕様](specification.md) に従い、
保存状態とブローカーの状態を確認します。

## 検証用コマンド

旧互換テストは `classOanda.py` が使う `pytz` を必要とします。開発依存に含まれるので、
未導入なら `.venv/bin/python -m pip install -e '.[dev]'` で導入します。
このインストールはネットワークアクセスを伴う場合があります。

```sh
.venv/bin/python -m pytest --collect-only -q
.venv/bin/python -m pytest -q -m 'not integration'
.venv/bin/python -m ruff check src tests
.venv/bin/python -m compileall -q src tests
```

差分比較CLIの引数は [差分検証ガイド](differential-verification.md) を正本とします。
外部読み取り検証は [tests/README.md](../tests/README.md)、実注文を伴う
`ogami-oanda-practice-acceptance` は [外部受入手順](architecture-migration.md) を参照してください。
practice受入はpractice環境・有効化環境変数・実行フラグ・口座確認・少額損失許容を確認し、
所有する注文・取引の後処理が完了した場合だけ成功します。通常のオフライン検証には含めません。

文書更新時は `python3 scripts/check_documentation.py` でローカルリンクとコード参照を確認します。
アーカイブを扱う変更時の検証は [アーカイブ方針](archive-policy.md) を参照してください。
