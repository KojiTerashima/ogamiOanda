# バックテスト

[操作ガイド](usage.md) / [仕様](specification.md) / [戦略一覧](../src/ogami_oanda/strategy/README.md)

## 実行範囲

`ogami-oanda-backtest` は履歴取得の `fetch` とオフライン再生の `run` を提供します。
1実行につき1戦略・1通貨ペアです。originalはUSD_JPY・EUR_USD・AUD_USD、
matchaはUSD_JPYに対応します。各戦略はliveと同じ判断・注文計画・ポジション管理を使います。
originalの初回解析、時間帯・スプレッド条件、解析前後の同期順序は既存のスケジュールに従います。
ただし再生tickはS5終端に限られるため、liveの1秒ポーリングとは時間解像度が異なります。

初期残高は決済通貨で指定します。USD_JPYはJPY、EUR_USD・AUD_USDはUSDです。
残高を注文可否や数量調整には使いません。証拠金制限、スワップ、手数料、複数通貨の共有資金、
自動最適化、バックテスト途中からの再開は含みません。データ取得の再開には対応します。

## 履歴取得

次のコマンドは認証付きOANDA通信を行います。実行には外部読み取りの明示的な承認が必要です。
設定値はGit管理外とし、保存データや結果に認証情報・口座識別子は記録しません。

```sh
.venv/bin/ogami-oanda-backtest fetch \
  --pair USD_JPY --strategy original \
  --from 2024-01-01T00:00:00Z --to 2026-01-01T00:00:00Z \
  --data-dir data/history/usd-jpy \
  --config config/settings.yaml --account practice
```

未インストールの開発環境では、入口を `.venv/bin/python -m ogami_oanda.entrypoints.backtest` に置換できます。
最新ソースのCLI登録には `.venv/bin/python -m pip install -e '.[dev]'` を使います。

指定期間は開始を含み、終了を含みません。時刻はUTCオフセット必須、S5境界に合わせます。
6時間以内・UTC日境界で分割し、`from`・`to`・`granularity=S5`・`price=MBA`を指定します。
`count`は併用しません。完了済みの取得区間は件数・ハッシュを検証してスキップします。
一時障害は最大4回試行し、認証失敗は再試行せず停止します。空応答も取得済み区間として記録します。
同じ保存先への同時取得は排他ロックで拒否します。

戦略の要求足数から前歴を自動計算します。最長時間足の必要期間を2倍し7日を加え、UTC日初へ丸めます。
`--warmup-days N`で上書きできます。前歴不足は明示的なエラーとなります。
前歴は足生成だけに使い、戦略判断・売買・損益評価から除外します。

## オフライン再生

`run`は認証設定を必要とせず、実口座チェックポイント・通知・live構築関数を利用しません。
仮想注文を実行するため、liveの`--dry-run`は使用しません。

```sh
.venv/bin/ogami-oanda-backtest run \
  --pair USD_JPY --strategy original \
  --from 2024-01-01T00:00:00Z --to 2026-01-01T00:00:00Z \
  --data-dir data/history/usd-jpy \
  --initial-balance 1000000 --slippage-pips 0.2 \
  --output-dir results/original-usd-jpy-001
```

出力先は毎回新しいディレクトリを指定します。既存結果は上書きしません。
名前指定originalの数量設定は `--risk-yen`（既定500）と `--line-units`（既定1）です。
`risk_yen`は既存戦略の設定名を維持しており、損益の決済通貨指定とは別です。
matcha本体・同梱YAMLの設定は変更しません。

### MidのみのCSV

```sh
.venv/bin/ogami-oanda-backtest run \
  --pair USD_JPY --strategy matcha \
  --from 2024-01-02T00:00:00Z --to 2024-01-03T00:00:00Z \
  --mid-csv data/mid-s5.csv.gz --fixed-spread-pips 1 \
  --initial-balance 1000000 --output-dir results/matcha-mid-001
```

列は `time,open,high,low,close`、任意で `volume,complete` を持つ昇順S5です。
`time`がない旧CSVはAsia/Tokyoの`time_jp`（`YYYY/MM/DD HH:MM:SS`）を受け付けます。
評価開始前の前歴を含めてください。未確定足・重複・逆順・不正OHLCは拒否します。
固定スプレッドの明示指定が必須で、Midから半スプレッドずつBid/Askを推定します。
結果の`price_mode=MID_FIXED_SPREAD`と`fixed_spread_pips`に推定条件を記録します。
Mid CSVには取得マニフェストがないため、空白の原因が休場か未取得かは判断できません。

## データ形式

日別ファイルは `YYYY-MM-DD-<hash>.csv.gz`、索引は `manifest.json` です。
CSV列は `time`、`mid_open,mid_high,mid_low,mid_close`、同じ4列の`bid_`・`ask_`、
`volume,complete`です。時刻はUTCの足開始、価格はOHLC、`complete=True`のS5だけを保存します。
Bid <= Mid <= Askを各OHLC成分で検証します。

マニフェストの`schema_version=1`は`pair,price_mode,intervals,files`を持ちます。
`intervals`は`from,to,count`、`files`はUTC日をキーに`path,sha256,rows`を持ちます。
日別ファイルを確定してからマニフェストをatomic replaceし、中断時も直前の確定状態を保ちます。
取得途中の区間・欠落ファイル・ハッシュ不一致は再生前に拒否します。
追加取得で日別ファイルが更新されても、過去のハッシュ名のファイルは保持します。
実行中の読込は開始時のマニフェストに固定されるため、同じ保存先への追加取得の影響を受けません。
`run.json`の`data_manifest`に使用した索引を保存し、その正規化JSONのSHA-256を
`data_sha256`へ記録します。正規化方法は`data_manifest_encoding`に記録します。

再生時は日別ストリームと必要なローリング窓だけを保持します。全期間DataFrameは作りません。
S5からM1/M5/M30/H1を増分生成し、先頭に形成中の足を置きます。
形成中の足には観測済み価格のみを含め、`complete=False`にします。
足境界直後の形成中行は直近観測価格・volume=0です。空白を架空の確定足で埋めません。
`time_jp`と取引スケジュールはAsia/Tokyo、保存・レポートの時刻はUTCです。

## 約定モデル

1. S5ごとに以前の注文・決済要求を処理し、市場と足を更新してから、ポジション同期と戦略判断を行います。
2. MARKETと戦略決済要求は判断後の次の利用可能なS5始値で執行します。判断に使った足へ遡りません。
3. 買いはAskで入りBidで決済、売りはBidで入りAskで決済します。
4. LIMITは指定価格より不利に約定しません。始値が有利なら価格改善を認めます。
5. STOP・SLの窓開けは始値を使います。MARKET・STOP・SLへ指定pipsの不利なスリッページを適用します。
6. 足開始時保有のTP/SL同時到達はSL優先です。TPを超える始値でも同じ足でSLに達すればSLを優先します。
7. 足途中の新規約定は、同じ足での順序不明なTPを計上せず、SL到達は適用します。
8. 一部決済は決済数量分だけ損益を計上します。既存の全決済履歴は損益の再計上に使いません。
9. 終了時は未約定を取消し、残存ポジションを最後のBid/Ask終値で決済します。この終了決済に追加スリッページは適用しません。

終了取消・決済は`END_OF_TEST`で区別します。要求理由と実行結果は別イベントに記録します。
未発注の監視注文も終了時に取り消し、終了後の新規発注は拒否します。
ポジション・未約定・未解決の操作が残る場合、結果を`complete`にはしません。
このモデルはS5内の真の価格順序・ティック単位の約定を再現しない保守的近似です。

## 出力

| ファイル | 内容 |
| --- | --- |
| `orders.csv` | 注文・約定・取消・拒否・保護変更・決済要求とruntimeイベント。イベントID、時刻、数量、価格、理由 |
| `trades.csv` | `FILL,REDUCE,CLOSE`の数量・価格・実現損益。取引ID単位で追跡 |
| `equity.csv` | S5終端の時刻・残高・含み損益・総資産。終了清算後は同時刻に最終行を追加 |
| `gaps.csv` | 観測できない区間の`from,to,seconds`。前歴を含み、評価区間端の空白も記録 |
| `summary.json` | 取引数・勝率・PF・損益・最大DD・月別実現損益・足数・欠損集計 |
| `run.json` | 戦略ID、コード・設定・データのハッシュ、期間、近似条件、最終戦略状態、実行状態 |

残高 = 初期残高 + 実現損益、総資産 = 残高 + 含み損益です。
最大DDは初期残高を起点としたS5総資産の高値からの最大下落幅・率です。
勝率・PFは一部決済を取引ごとに集約した最終損益で計算し、月別は各決済時点のUTC月へ計上します。
取引ゼロの勝率・損失ゼロのPFは`null`です。
`run.json`は`running`から成功時`complete`、例外時`failed`へ変化します。
強制終了時は`running`のまま残る場合があります。未完了結果を完成結果として使わないでください。

## strategy追加

信頼済みコードを`src/ogami_oanda/strategy/<name>/`へ置き、Python/YAML両方を指定します。
パッケージ外・外部へ解決されるシンボリックリンクはローダーが拒否します。

```sh
.venv/bin/ogami-oanda-backtest run \
  --pair USD_JPY \
  --strategy-py src/ogami_oanda/strategy/original/strategy.py \
  --strategy-yaml src/ogami_oanda/strategy/original/parameters.yaml \
  --from 2024-01-01T00:00:00Z --to 2026-01-01T00:00:00Z \
  --data-dir data/history/usd-jpy --initial-balance 1000000 \
  --output-dir results/plugin-001
```

モジュールに`STRATEGY_API_VERSION = 1`と`create_strategy(config)`を定義し、
返すオブジェクトは`decide, dump_state, load_state`を実装します。
`StrategyInput.candles`は従来のM1入力、`candle_frames`は時間足別入力です。
任意の`data_requirements`は時間足から正の本数への辞書で、未指定は`{"M1": 1000}`、
originalはS5/M5/M30/H1各250本です。空辞書なら足の前歴は不要です。
状態はJSON互換値に限定し、初期状態の読込・繰返し実行をテストしてください。
注文は`StrategyDecision.intents`、source限定操作は`commands`で返します。
必要なら`order_context`と`candle_protection`を返せます。
strategyからapplication・broker・外部I/Oへ依存を作らないでください。

## 検証

既存のgolden照合はPythonと数値ライブラリの版も検証します。
全体ゲートの再現にはPython 3.12.5・NumPy 2.3.2・pandas 2.3.1を使用します。
通常の開発環境と版が異なる場合は、別の仮想環境へ`.[dev]`とこの依存版をインストールしてください。

goldenのBollinger列6値にあった微小差は、2026-09-11に固定旧版コミットから
全41シナリオを正規手順で再取得して更新しました。旧版自体の再生でも同じ差が出ることを
先に確認し、変更は6値と対応する2つのトレースハッシュに限定しています。
比較器・許容差リスト・指標の数式は維持しています。数値差の環境要因自体は未特定です。
出典と更新手順は[差分検証ガイド](differential-verification.md)に記載しています。
取得前の比較、更新差分、最終検証結果は`runtime/backtest-verification/`に保存しています。

```sh
.venv/bin/python -m pytest -q tests/test_backtest_*.py tests/test_contract_original_strategy_api.py
.venv/bin/python -m pytest -q -m 'not integration'
.venv/bin/python -m ruff check src tests
.venv/bin/python -m compileall -q src tests
.venv/bin/python scripts/check_documentation.py
```

長期検証は通常pytestと別に実行します。Linuxの最大RSSをMiB単位で記録します。
5種類の時間足各250本、251時間の前歴、全評価S5、一部決済を含む合成strategyを使います。
初期残高は数量制約にならず、全量読込を拒否する一回限りの入力iteratorを使います。

```sh
.venv/bin/python scripts/verify_backtest_long_run.py \
  --days 730 --max-memory-mib 512 --output-dir results/synthetic-730-days
```

`benchmark.json`に実行時間・最大RSS・日別の最大RSSを記録します。
`--days 1`の短縮検証では評価17,280本と前歴180,720本を処理します。

2026-09-10の730日検証は、評価12,614,400本・前歴180,720本を完走しました。
Python 3.12.5・NumPy 2.3.2・pandas 2.3.1、Linux環境で約4,454.55秒（74.24分）、
最大RSS 280.16 MiBでした。730回の日次計測で最大RSSの増加はありませんでした。
部分決済を含む12,112取引を処理し、終了時の含み損益は0、残高の台帳整合性も確認しました。
結果は`runtime/backtest-verification/synthetic-730-days/`に保存しています。
この完走後にイベントIDの保持判定を完全一致へ修正し、10万件の不要履歴を使う回帰テストと
1日分の再生を追加実施しました。修正前後の`trades.csv`・`equity.csv`はバイト単位で一致しました。
所要時間・メモリは環境と戦略で変動し、この合成戦略の損益は戦略性能の評価には使えません。
認証付き取得後の実データ2年間の検証は、別途行う受入確認です。

## originalのmain参照先

originalの`run`はmainディレクトリの解析コードを直接読みます。ogamiOandaルートからの起動では
既定の`../main`を使い、別配置では`--main-analysis-dir PATH`を指定します。`fetch`とMatchaには不要です。
mainの変更は次の実行で反映します。コードを同梱・同期する処理はありません。
`run.json`の`main_source_directory`は参照パスです。既存の`source_sha256`はogamiOanda内のコードが対象で、
外部mainの内容は含みません。同じ結果の再現には同じmainの内容を用意します。
[main解析ガイド](main-analysis.md)にPython APIとエラー時の扱いを記載しています。
