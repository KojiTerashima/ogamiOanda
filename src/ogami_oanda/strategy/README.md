# 起動できる売買戦略

このディレクトリには2つの売買判断ロジックと共用部品を置きます。
ディレクトリ名 `original` / `matcha` がlive CLIの `--strategy` 名に対応します。
`shared` は起動対象ではありません。

```text
strategy/
├── original/                   # 従来のライン戦略（USD/JPY・EUR/USD・AUD/USD）
│   ├── line/                   # 候補生成、通貨ペア別判断、期限
│   └── position_sizing.py      # ライン戦略のリスク数量計算
├── matcha/                     # Matcha戦略（USD/JPY）
│   ├── strategy.py             # 判断本体とcreate_strategy
│   └── parameters.yaml         # 同梱の戦略設定
├── shared/                     # 両戦略から利用する共通基盤
│   ├── contracts.py            # StrategyInput / Decision / Command等
│   ├── loader.py               # 信頼済みPython + YAMLのロード
│   └── position_management/    # 状態管理から使う判断方針
└── __init__.py                 # 公開型の再公開と旧import名の互換窓口
```

| 起動名 | 説明・専用ファイル | 評価経路 |
| --- | --- | --- |
| `original` | [従来ライン戦略](original/README.md) | LiveApplicationで時刻・スプレッド条件に沿って解析 |
| `matcha` | [Matcha戦略](matcha/README.md) | StrategyLiveApplicationで開場tickごとにプラグイン判断 |
| 起動不可 | [共用部品](shared/README.md) | 判断契約・ロード・管理ポリシー。単独の売買判断ではない |

## ループの起動

リポジトリルートで、設定を用意してから起動します。
下記は発注を抑止した継続ループですが、OANDAへの読み取り通信とログ出力を伴います。

```sh
.venv/bin/ogami-oanda-live --strategy original --config config/settings.yaml --account practice --pair USD_JPY --dry-run
.venv/bin/ogami-oanda-live --strategy matcha --config config/settings.yaml --account practice --pair USD_JPY --dry-run
```

どちらも `--once` を追加すると1 tickで終了します。`--strategy` 省略時は従来どおりoriginalです。
各プロセスは1戦略を選択します。同一口座・同一ペアの状態保存先は共通なので、
別戦略の同時稼働を分離する仕組みではありません。戦略切替時は既存のチェックポイント照合規則に従います。
実発注を伴うpractice/live操作には実行直前の明示的承認が必要です。
設定不要・通信なしのsmokeは `--strategy original --offline-smoke --dry-run --once` です。
これは共通CLIと組込み経路の確認で、Matchaの市場判断の検証ではありません。

`--strategy matcha` はインストールされたパッケージ内の本体と同梱YAMLを選ぶため、
作業ディレクトリからソースのパスを指定する必要はありません。
別の戦略設定は `--strategy-py` と `--strategy-yaml` をペアで指定します。
この明示パス指定と `--strategy` は併用できません。

## 責任の境界と追加方法

戦略には売買判断を置き、ループ・接続・口座設定・保存は
[entrypoints](../entrypoints/live.py) / application / adapters / infrastructureが担当します。
`original` と `matcha` は互いの実装をimportしません。
`shared` は特定戦略の実装に依存しません。

新しい戦略は専用ディレクトリへPython本体・YAML・READMEをまとめ、
`STRATEGY_API_VERSION = 1` と `create_strategy(config)` を公開します。
返すオブジェクトは `decide` / `dump_state` / `load_state` を実装します。
明示パス指定なら既存のプラグインループで動かせます。
短い `--strategy` 名も提供する場合はlive CLIの選択肢・構築分岐・両起動モードのテストを追加します。

## 配置移行の互換性

旧 `strategy.line`, `contracts`, `loader`, `position_management`, `position_sizing` のPython importは `__init__.py` が新配置の同一モジュールへつなぎます。
旧ファイルや重複した実装は残しません。新規コードは所有ディレクトリ付きのimportを使用します。
Matcha本体の旧contracts importだけは、Pythonの内容ハッシュと保存済み戦略IDを保つため維持しています。
本体とYAMLは移動前とバイト一致し、移動だけでは戦略IDが変わりません。

旧 `ogami_oanda.strategy.matcha_oanda` の直接importは `ogami_oanda.strategy.matcha.strategy` へ更新してください。
Matchaは選択時にロードし、originalの起動時にその本体を実行しません。
旧ファイルパスを指定するCLIや外部スクリプトは新パスへ更新してください。
Python importの互換性と、ファイルパスの互換性は別です。
詳しい設定・状態復旧は [操作ガイド](../../../docs/usage.md)、
全定義は [コード参照](../../../docs/reference/strategy.md) を参照してください。
