# matcha — Matcha戦略

[戦略一覧](../README.md)

USD/JPYの過去価格帯・標準偏差・保有量・価格鮮度から売買判断を作ります。
起動名は `matcha` です。

| ファイル | 役割 |
| --- | --- |
| `strategy.py` | MatchaConfig、MatchaStrategy、create_strategy、価格帯/数量計算 |
| `parameters.yaml` | 同梱設定。口座情報や通知先は含めない |
| `__init__.py` | 専用パッケージの説明 |

リポジトリルートで継続実行（通常dry-runは外部読み取りあり）:

```sh
.venv/bin/ogami-oanda-live --strategy matcha --config config/settings.yaml --account practice --pair USD_JPY --dry-run
```

`--once` 追加で1 tick。USD_JPY以外はこの戦略では使えません。
市場判断の繰り返しはStrategyLiveApplicationが担当します。
判断は共通のStrategyDecisionで返し、注文処理・状態保存は共通ポートフォリオに委譲します。

同梱YAML以外を使う場合は、このパッケージ配下に信頼済みの設定を置いて両パスを指定します。

```sh
.venv/bin/ogami-oanda-live --config config/settings.yaml --account practice --pair USD_JPY --strategy-py src/ogami_oanda/strategy/matcha/strategy.py --strategy-yaml src/ogami_oanda/strategy/matcha/parameters.yaml --dry-run
```

明示パス指定時は `--strategy matcha` を付けません。対応するパラメータの範囲は
MatchaConfig.from_mappingが検証します。価格計算、ロット、遅延条件等の売買ロジックは今回変更していません。
Python/YAMLの内容から作る戦略IDは配置変更前と同じです。
今後、本体や設定内容を変えた場合はIDが変わるため、既存のチェックポイント照合規則に従います。
