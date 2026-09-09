# コード参照

[ドキュメント索引](../README.md) / [構成と処理の流れ](../structure.md)

現行 `src/ogami_oanda/` の全Pythonファイルと同梱戦略YAMLを掲載します。
各ファイルの役割、直下のクラス・関数、クラス内のメソッドを実装へのリンク付きで示します。
`internal` は内部補助処理であり、互換性を保証する外部APIではありません。
関数内の局所関数、定数、型フィールド、継承しただけのメソッド、dataclassの自動生成メソッドは
別項目にせず、親の実装を参照します。引数・戻り値・フィールド・例外の厳密な型はソースが正本です。

| 層 | 内容 |
| --- | --- |
| [domain](domain.md) | 市場・分析・注文・ポジションの値と純粋計算 |
| [strategy](strategy.md) | ライン判断・ポジション方針・数量・Matcha・プラグイン |
| [application](application.md) | ports・設定・スケジュール・各ユースケース |
| [adapters](adapters.md) | OANDA・Discord・CSV・JSON・旧形式との変換 |
| [infrastructure](infrastructure.md) | 設定読込・時計・ループ・日次ログ |
| [entrypoints](entrypoints.md) | live/strategyの構築、CLI、表示、practice受入 |
| [backtest](backtest.md) | 現在のパッケージ入口と実装先 |

全体パッケージの [__init__.py](../../src/ogami_oanda/__init__.py) はパッケージ説明のみを持ち、
業務処理を開始しません。旧ルートAPIは [移行マップ](../migration-map.md) を参照してください。

## 保守

シンボルを追加・変更した際は該当層の表へ役割とソースリンクを追加・修正します。
ファイル分割や行移動後にはリンク先の定義も確認してください。
この参照表はソースをimport/実行せずASTで定義を列挙し、役割説明を付けて作成しています。

文書のローカルリンクとソース定義の網羅・行番号は、リポジトリルートで
`python3 scripts/check_documentation.py` を実行して確認できます。
説明文の意味や設定例の妥当性は実装と照合してレビューします。
