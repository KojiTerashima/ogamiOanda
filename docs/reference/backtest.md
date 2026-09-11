# backtest コード参照

[コード参照の入口](README.md) / [構成](../structure.md)

## `backtest/__init__.py`

[ソース](../../src/ogami_oanda/backtest/__init__.py)

互換パッケージの入口。初期化時に業務処理を開始しない。
履歴取得・再生CLIは[entrypoints](entrypoints.md)、仮想ブローカーと結果出力は
[adapters](adapters.md)、増分市場・再生時計は[application](application.md)が担当する。
操作・保存形式・約定規則は[バックテストガイド](../backtest.md)を参照。
