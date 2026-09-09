# backtest コード参照

[コード参照の入口](README.md) / [構成](../structure.md)

## `backtest/__init__.py`

[ソース](../../src/ogami_oanda/backtest/__init__.py)

パッケージの入口。初期化時に業務処理を開始しない。 現時点ではバックテストCLIはなく、決済判定はapplicationのBacktestSimulatorが担当。
