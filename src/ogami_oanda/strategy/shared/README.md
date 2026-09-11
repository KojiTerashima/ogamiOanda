# shared — 戦略共用部品

[戦略一覧](../README.md)

ここには単独で起動する売買戦略を置きません。`--strategy shared` は選択できません。

| ファイル/ディレクトリ | 役割・利用側 |
| --- | --- |
| `contracts.py` | 市場入力、intent/commandの判断結果、状態保存API。プラグインとapplicationが共有 |
| `loader.py` | 戦略本体/YAMLのパッケージ内パス検証、API確認、内容ID計算。entrypointが利用 |
| `position_management/entry_confirmation.py` | 発注前watchingの価格確認 |
| `position_management/exit_policy.py` | 注文・取引の期限判定 |
| `position_management/stop_loss_policy.py` | 段階的/ローソク足由来のSL変更 |
| `position_management/linkage.py` | 主注文との連動判断 |
| `position_management/hedge.py` | 反対ポジションのヘッジ解消判断 |

position_managementは両戦略が使うPositionService/PositionPortfolioServiceから呼ばれる方針です。
すべての戦略が毎tickすべての方針を使うという意味ではなく、注文計画・metadata・状態に応じて適用します。
original固有のライン数量計算はここには置かず `original/position_sizing.py` にあります。
Matchaのロット計算は `matcha/strategy.py` にあります。

ローダーの許可範囲は移動後も `strategy/` 全体です。`shared/` 内だけに限定しません。
OANDA接続、実時計、ポーリングループは共用であってもこの層の責任外です。
新規共用コードは `original` / `matcha` 等の具体戦略をimportしないでください。

`StrategyInput.candles`は従来のM1入力を維持し、`candle_frames`で時間足別の入力を受け取れます。
任意の`data_requirements`がない戦略はM1・1,000本、空辞書を宣言した戦略は足を要求しません。
`StrategyDecision.order_context`と`candle_protection`は注文計画と保護判断に必要な任意の共通情報です。
評価スケジュールはapplicationが管理し、データ要件から頻度を決めません。
