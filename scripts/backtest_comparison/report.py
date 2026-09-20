"""Human-readable results, with counterfactual and portfolio metrics kept distinct."""

from __future__ import annotations

import json
from pathlib import Path

from .common import write_json
from .audit import audit_execution, audit_money


def make_report(root, selections):
    root = Path(root)
    records = {}
    lines = ["# main / ogamiOanda 抵抗線ブレイク比較", "",
             "固定した同一コード・取得済みS5によるオフライン検証。金額は各通貨の決済通貨（JPYまたはUSD）。", "",
             "mainおよび単独注文の損益は独立した仮想注文の合計であり、同時保有するポートフォリオの成績ではありません。", "",
             "| 通貨 | 終了日UTC（含まない） | 解析成功 / 予定 | 同一入力差分 | main候補 / 約定 | 単独main損益 | 単独ogami損益 | 連続固定:取引 / 損益 | 連続MBA:取引 / 損益 | 再現性 |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for pair, selection in sorted(selections.items()):
        directory = Path(selection["run"])
        result = json.loads((directory/"result.json").read_text())
        repeat = selection.get("repeat_comparison", {})
        records[pair] = {**result, "run_directory":str(directory.relative_to(root)), "repeat":repeat}
        a, f, m = result["analysis"], result["fixed"]["summary"], result["mba"]["summary"]
        lines.append(f"| {pair} | {result['to'][:10]} | {a.get('evaluated',0)} / {a.get('scheduled',0)} | {a.get('mismatches',0)} | "
                     f"{a.get('candidates',0)} / {a.get('filled',0)} | {a['main_counterfactual_pnl_quote']:.6f} | "
                     f"{a['ogami_isolated_pnl_quote']:.6f} | {f['trade_count']} / {f['realized_pl']:.6f} | "
                     f"{m['trade_count']} / {m['realized_pl']:.6f} | {'一致' if repeat.get('equal') else '不一致・未完了'} |")
    lines.extend(["", "## 原因・証拠", ""])
    for pair, result in records.items():
        lines.extend([f"### {pair}", "", f"実行結果: [{result['run_directory']}]({result['run_directory']}/result.json)", ""])
        for category, count in sorted(result["categories"].items()):
            example = result["examples"].get(category.replace(":", "-", 1))
            link = f" [最初の再現入力]({result['run_directory']}/{example})" if example else ""
            lines.append(f"- `{category}`: {count}件。{link}")
        if not result["categories"]:
            lines.append("- 観測した比較範囲で差分なし。取引・入力カバレッジは上表を参照。")
        if result["needs_extension"]:
            lines.append("- 最大期間でも未充足のカバレッジまたは未分類事項あり。一致の保証対象から除外。")
        lines.extend(["", f"固定スプレッド時の見送り: `{result['fixed']['summary'].get('skipped',{})}`",
                      f"保存Bid/Ask時の見送り: `{result['mba']['summary'].get('skipped',{})}`", ""])
    lines.extend(["## 修正案・維持する仕様", "",
        "1. `A:input_enrichment` / `A:indicators_peaks` / `A:candidate_conversion` がある場合: 最初の再現入力を回帰テストにし、入力変換・確定足選択・注文変換の該当箇所を修正する。期待値を現状へ更新して差を消さない。",
        "2. `same_input_candidate_mismatch` がある場合: 連続再生時のアダプター状態・変換を調査する。`native_window_or_evaluation_input` は同一入力で原文と一致した証拠を持つが、履歴窓と評価価格の個別寄与は未分離であり、仕様か不具合かの確定判断を保留する。",
        "3. SLスリッページ、STOP窓開け、約定足内TP抑止、終了時清算は約定モデルの仕様差として維持する。変更が必要なら本番既定値を変更せず、研究用モデルを明示して選ぶ別提案とする。",
        "4. 時間決済はmainの足終値評価、単独比較ドライバーのS5ごとの期限確認、連続再生のポジション同期を区別する。期限前後・欠損後の最初の約定可能足を固定したテストで意図しない遅延だけを修正候補とする。",
        "5. MBAで解析や約定が0件でも一致としない。スプレッド閾値・見送り内訳を根拠として掲載し、成績を見て閾値を自動調整しない。",
        "", "## 制約と再現", "",
        "- `conditions.json`にソース・データ・環境の固定条件、各実行の`normalized-hashes.json`に再現性照合対象を保存。",
        "- `analysis.jsonl`は全5分判断境界、`isolated-orders.jsonl`は候補単位、`C-*-analysis.jsonl`は実際の連続再生の解析記録。",
        "- `differences.jsonl`は両側の値を保持。足開始時刻と実行イベント時刻を別々に保存し、表示上の時刻差だけを損益差に数えない。",
        "- mainの`result_yen`は原文の丸め済みリスク額から算出する参考値。比較損益は価格差×方向×数量で独立計算。",
        "- 連続再生の勝率・PF・最大DDは各`C-*/summary.json`に保存。mainへ仮の資産曲線や最大DDは付与しない。",
        "- 原文の通常起動・通知・認証読込みは使わない。mainのS5補完や別取得キャッシュとの同一性は対象外。",
        "- `evaluation_unavailable`、未分類差分、実データで未発生の経路は未確認のまま報告する。取引ゼロを一致扱いしない。",
        "- 本番売買ロジックへの修正は適用していない。", ""])
    audit_money(root, complete=True)
    audit_execution(root, complete=True)
    lines.extend(["## 追加監査", "",
                  "[mainの円損益の算出と修正候補](MONETARY-AUDIT.md)、[固定履歴の始値を使った約定差の再分類](execution-review.json)。",
                  "元の台帳・実行時分類は保存したまま、追加の根拠による分類変更を別ファイルに記録しています。", ""])
    (root/"REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    write_json(root/"comparison.json", {"status":"complete", "pairs":records,
                                       "all_repeats_equal":all(v["repeat"].get("equal") for v in records.values())})
