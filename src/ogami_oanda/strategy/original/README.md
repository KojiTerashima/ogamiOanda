# original — 従来のライン戦略

[戦略一覧](../README.md)

USD/JPY・EUR/USD・AUD/USDの足・ピーク・ラインから注文候補を選びます。
従来の組込み戦略で、起動名は `original` です。

| ファイル/ディレクトリ | 役割 |
| --- | --- |
| `line/builder.py` | 候補生成・選択・数量/保護値補足と診断をまとめる |
| `line/coordinator.py` | ライン候補の文脈・session・近接候補・推薦理由を扱う |
| `line/usd_jpy.py` | USD/JPYのH1/M5反転・突破判断 |
| `line/eur_usd.py`, `line/aud_usd.py` | 通貨ペア別の派生判断 |
| `line/order_timeout.py` | 価格距離に応じた注文期限 |
| `position_sizing.py` | 許容損失とSL幅から数量を計算するoriginal専用方針 |
| `strategy.py`, `parameters.yaml` | 共通API v1の入口、信頼済みプラグインとしての設定 |
| `analysis.py`, `context.py` | 足の解析・候補文脈・OrderIntent生成。applicationの互換サービスも委譲する |

リポジトリルートで継続実行（通常dry-runは外部読み取りあり）:

```sh
.venv/bin/ogami-oanda-live --strategy original --config config/settings.yaml --account practice --pair USD_JPY --dry-run
```

`--pair` をEUR_USD / AUD_USDへ変えて各ペアを選べます。`--once` 追加で1 tick。
`--strategy` 省略時もこの戦略です。
liveの名前指定は共通 `config/settings.yaml` の `trading` を使用します。
明示プラグイン指定には`parameters.yaml`を使用し、`pair,risk_yen,line_units`を受け付けます。
S5/M5/M30/H1を各250本要求し、状態は空のJSONオブジェクトです。
バックテストの設定・操作は[専用ガイド](../../../../docs/backtest.md)を参照してください。
時刻・週末・スプレッド・初回の規則はLiveApplicationが保持し、このディレクトリ自身はループしません。
共有ポートフォリオによる監視・保護・連動の判断は [shared](../shared/README.md) を使います。
