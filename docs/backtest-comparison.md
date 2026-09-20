# mainとのバックテスト比較

`scripts/compare_main_backtest.py` は、mainの抵抗線ブレイクとogamiOandaの
`original --analysis resistance_breakout`を取得済みS5だけで比較する研究用ツールです。
本番CLI・戦略設定・売買ロジックを変更せず、OANDA通信、通知、秘密設定の読込みを拒否します。

## 実行

ogamiOandaルートから実行します。3通貨の保存履歴には評価開始前28日も必要です。
出力先は新しいディレクトリを指定します。

```sh
.venv/bin/python scripts/compare_main_backtest.py \
  --main-analysis-dir ../main --data-root runtime/history \
  --output-dir runtime/backtest-comparison/EXAMPLE --workers 3
```

既定はUTC `[2024-09-01, 2024-09-08)`。通貨ごとに、解析・候補・約定の不足、
同一入力の差、未分類の約定差があれば `[2024-09-01, 2024-10-01)`へ延長します。
最終的に選んだ期間を、キャッシュした解析結果を使わず独立に再実行します。
USD_JPY、EUR_USD、AUD_USDは別プロセスで処理し、各通貨の状態を共有しません。
長期解析は時間を要します。出力先の`RUNNING.md`に、通貨別の段階内進捗率、
独立再実行を含む全工程の進捗率、経過時間、推定残り時間、JSTの完了予測時刻を30秒ごとに表示します。
機械可読の全体記録は出力先直下の`progress.json`、詳細は`logs/`と各実行の`progress.json`です。

延長の要否が未確定の間は、7日で終了する場合と1か月へ延長する場合を別々に表示します。
進捗率は休場を除く5分判断数を使い、A/B・固定スプレッド再生・保存Bid/Ask再生を等重みで数えます。
時間の消化率ではありません。完了予測は実測速度からの概算で、未計測の段階はA/Bと同速度と仮定します。
初期推定には準備時間を含みますが、今後の準備・最終集計時間は未計測です。
実行停止、失敗、15分以上の記録更新途絶、測定不足のときは完了予測を保留します。

表示機能追加前から動いているジョブにも、現在のツールから観測だけを追加できます。
ワーカーや固定ソースは変更しません。新しい実行では自動更新が標準で有効です。

```sh
.venv/bin/python scripts/compare_main_backtest.py \
  --output-dir runtime/backtest-comparison/EXAMPLE --watch-progress
```

`--progress`なら一度だけ更新します。同じ出力への観測プロセスの重複起動は拒否します。
自動更新中の表示確認には`RUNNING.md`または出力先直下の`progress.json`を開いてください。

`--pairs EUR_USD`で対象を絞れます。期間を変更する場合は
`--from`・`--pilot-to`・`--max-to`をUTC日初のオフセット付き時刻で指定します。
スプレッド0.8 pips、ブローカーのスリッページ0.5 pips、リスク500円は比較条件として固定します。
取得履歴のBid/Askを使う連続再生も同じスリッページで実行します。

## 固定・再開

最初に、必要なmain原文、ogamiOandaのproductionソースと比較ツール、必要範囲の日別履歴を
`source/`へコピーし、ファイルハッシュ、Gitコミット、依存版、policyを`conditions.json`へ記録します。
main全体や認証ファイルはコピーしません。ワーカーは固定したproductionソースを使用します。

```sh
.venv/bin/python runtime/backtest-comparison/EXAMPLE/source/ogami/scripts/compare_main_backtest.py \
  --output-dir runtime/backtest-comparison/EXAMPLE --resume --workers 3
```

再開時は環境・固定ソース・manifestの改変を拒否し、日別データは読込み時にも照合します。
完成済み実行は成果物のハッシュを再検査したうえで再利用します。
失敗・中断した実行を完成扱いせず、新しい試行ディレクトリでやり直します。
同じ出力へのコントローラー同時起動は拒否します。

## 比較の意味

- **A: 同一入力** — main原文の足加工・解析・注文作成とアダプター経由を別に呼び、
  足、指標、ピーク、抵抗線候補、注文価格・数量・期限を照合します。
  mainの通常Inspection相当の履歴窓（M5 721、M30 241、H1 250）で5分ごとに判断します。
  通常のコンストラクターの通信・保存処理は呼びません。
  連続した休場区間の入口では両方の解析不可を確認し、残りの休場判断は同じ原文カレンダーで記録します。
  正常な休場を履歴不足や差分として数えません。
- **B: 単独注文** — 同じ注文と固定スプレッドS5を、原文`Inspection.inspect_order_after`と
  `SimulatedBroker`に渡します。比較ドライバーはS5処理後に期限を確認し、時間決済は次の始値へ要求します。
  この期限確認方法を本番のポジション同期と同一視しません。
- **C: 連続再生** — 既存`run_backtest`を固定スプレッドと保存Bid/Askで実行します。
  ogamiOandaの履歴窓・スケジュール・注文管理・終了処理をそのまま使用します。
  mainと候補が異なる場合、その実際の入力をmainへも渡して変換差と入力差を切り分けます。

S5は足開始時刻です。終値は5秒後に利用可能となります。M5/M30/H1は観測済みS5だけから生成し、
足境界の形成中行には直近価格だけを置きます。欠損を架空の確定足で補いません。
独立したpandas集計を`HistoricalMarket`と各観測M5境界で照合します。

注文は出自とリスト内の出現番号で対応付けます。価格や実行ごとに変わるIDをキーにせず、
価格だけの変化、片側だけの候補、重複を見落としません。
価格は通貨の価格精度、数量・採否は完全一致、損益は決済通貨で絶対誤差`1e-6`、
その他内部数値は絶対・相対誤差`1e-9`を基準にします。

## 成果物・制約

`REPORT.md`に比較表と修正案、`comparison.json`に集計結果を保存します。
各実行の`analysis.jsonl`、`isolated-orders.jsonl`、`C-*-analysis.jsonl`が全判断・全候補の台帳です。
`differences.jsonl`は差の両側の値を保持し、`examples/`に分類ごとの最初の再現入力を保存します。
連続再生は既存のorders/trades/equity/gaps/summary/runファイルも生成します。

mainの金額合計は独立した仮想注文の集計です。ポートフォリオの共有資金・最大DDには変換しません。
mainの`result_yen`は原文の丸めを含む参考値として残し、比較用損益は約定価格差×方向×数量から
決済通貨で計算します。取引0件、履歴不足、例外、未分類事項を一致に含めません。

単独注文再生（B段階）はmainの検証モデルと同じ境界規則で実行します:
注文期限は「期限ちょうどに開始する足まで約定可」、時間決済は約定〜保有期限の窓が
mainのカバレッジ条件（実在S5が期待本数の50%超かつ最終足終了が期限以達）を満たす場合のみ
期限内最終足の終値で執行し、不成立時と再生範囲終端で保有中の建玉は「未決済」として報告します
（終端清算の損益は成績に計上しません）。カバレッジ条件はmain検証器の写しであり、
live経路・連続再生のポジション管理には適用しません。
残る分類カテゴリは回帰検知用で、パリティ達成後の期待差分は0件です。本番修正は自動適用しません。

合成ケースと比較器の検証:

```sh
.venv/bin/python -m pytest -q tests/test_main_backtest_comparison.py tests/test_backtest_comparison_progress.py --main-analysis-dir ../main
.venv/bin/python -m ruff check scripts/backtest_comparison scripts/compare_main_backtest.py tests/test_main_backtest_comparison.py tests/test_backtest_comparison_progress.py
```

### 金額・約定原因の追加監査

`MONETARY-AUDIT.md` / `monetary-audit.json` はmainの表示円損益を、
実際の価格差・方向・数量・記録された換算レートから独立計算した金額と照合します。
`execution-review.json` は約定台帳を変更せず、固定した履歴の始値を根拠にSL窓開け等の分類を追加します。
実行後に監査コードを更新した場合も、監査・分類コードのハッシュを別途保存し、
当初の実行コードや元の分類と混同しません。途中実行の監査は`provisional`と表示します。
