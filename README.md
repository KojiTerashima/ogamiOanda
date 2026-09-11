# ogamiOanda

OANDA向けのPython取引プログラムです。現行実装は `src/ogami_oanda/` にあり、
市場分析・戦略判断・注文とポジションの管理・外部接続を層ごとに分けています。

## 読み始める場所

| 目的 | 説明書 |
| --- | --- |
| ドキュメント全体を探す | [ドキュメント索引](docs/README.md) |
| 各ディレクトリ・ファイルの役割を知る | [構成と処理の流れ](docs/structure.md) |
| 起動する売買戦略を選ぶ | [戦略一覧](src/ogami_oanda/strategy/README.md) |
| セットアップ・CLI・設定・ログを調べる | [操作ガイド](docs/usage.md) |
| 入出力・状態遷移・戦略の制約を調べる | [現行仕様](docs/specification.md) |
| クラス・関数・メソッドを探す | [コード参照](docs/reference/README.md) |
| オフラインで検証する | [テストガイド](tests/README.md) |
| mainの原文の解析を呼び出す | [main解析ガイド](docs/main-analysis.md) |
| 履歴データで戦略を検証する | [バックテストガイド](docs/backtest.md) |
| 旧ファイルを残した理由・復元方法を調べる | [アーカイブ方針](docs/archive-policy.md) |

設定不要・外部通信なしの動作確認（開発環境の導入は操作ガイド参照）:

```sh
.venv/bin/ogami-oanda-live --offline-smoke --dry-run --once
```

通常の `--dry-run` はOANDAへの読み取り通信を行います。
`--once` は実行回数を1回にする指定で、発注を禁止する指定ではありません。

ルートの互換モジュールは比較テストと従来の呼び出し口のために残しています。
新規開発では `src/ogami_oanda/` を参照してください。
未使用の旧プログラム・過去の計画書は `archive/retired/` に圧縮保存し、通常検索から除外しています。
