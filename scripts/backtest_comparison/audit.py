"""Audit reported native monetary results independently of broker differences."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path

from .common import write_json


def monetary_difference(record):
    candidate, result = record["candidate"], record["main"]
    reported = result.get("reported_yen")
    actual = result.get("pnl_quote")
    rate = 1.0 if candidate["pair"] == "USD_JPY" else candidate["metadata"].get("usd_jpy_rate")
    if reported is None or actual is None or rate is None:
        return None
    expected = actual*rate
    # result_yen is an unrounded numeric result, not just a currency display string.
    if abs(reported-expected) <= 1e-6:
        return None
    return {"at":record["at"], "ordinal":record["ordinal"], "pair":candidate["pair"],
            "reported_yen":reported, "price_quantity_yen":expected, "difference_yen":reported-expected,
            "conversion_rate":rate, "entry_price":result["entry_price"], "exit_price":result["exit_price"],
            "direction":candidate["direction"], "units":candidate["units"],
            "ideal_lc_pips":candidate["metadata"].get("lc_pips"),
            "rounded_order_lc_pips":record["main_raw"].get("lc_pips"),
            "rounded_actual_risk_yen":candidate["metadata"].get("actual_risk_yen")}


def audit_money(root, *, complete=None):
    """Can also describe an active run; never labels partial input as complete."""
    root = Path(root)
    counts = Counter()
    sums = Counter()
    examples = {}
    paths = []
    for path in sorted(root.glob("*/*/run/isolated-orders.jsonl")):
        name = str(path.parent.relative_to(root))
        paths.append(name)
        counts[f"{name}:checked"] += 0
        with path.open() as stream:
            for line in stream:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    # Only a final, unterminated writer fragment can be skipped.
                    if not line.endswith("\n"):
                        break
                    raise
                counts[f"{name}:checked"] += 1
                delta = monetary_difference(record)
                if delta:
                    counts[f"{name}:mismatches"] += 1
                    sums[name] += delta["difference_yen"]
                    examples.setdefault(name, delta)
    controller = root/"controller.json"
    if complete is None:
        complete = controller.exists() and json.loads(controller.read_text()).get("status") == "complete"
    audit = {"status":"complete" if complete else "provisional", "counts":dict(counts),
             "sum_difference_yen":dict(sums), "first_examples":examples,
             "report_generator_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    write_json(root/"monetary-audit.json", audit)
    lines = ["# mainの円損益計算の追加監査", "",
             "**確定結果**" if complete else "**本比較の実行中に得られた暫定結果。期間全体の結果ではありません。**", "",
             "同じmainの約定・決済価格と数量から算出した損益を、mainが報告した`result_yen`と比較します。",
             "モデル間のスリッページ差や資産曲線の比較とは別の監査です。", "",
             "| 実行 | 読込み済み候補 | 円損益不一致 | 円換算差の合計 |", "|---|---|---|---|"]
    for name in paths:
        lines.append(f"| {name} | {counts[name+':checked']} | {counts[name+':mismatches']} | {sums[name]:.6f} |")
    for name, example in examples.items():
        lines.extend(["", f"## 最初の例: {name}", "",
            f"判断時刻UTC `{example['at']}`、方向 `{example['direction']}`、数量 `{example['units']}`。",
            f"約定 `{example['entry_price']}` → 決済 `{example['exit_price']}`、換算レート `{example['conversion_rate']}`。",
            f"価格差×方向×数量×換算レートは **{example['price_quantity_yen']:.6f}円**、mainの表示値は **{example['reported_yen']:.6f}円**。",
            f"原文の理想LC幅 `{example['ideal_lc_pips']}` pipsと、価格丸め後のLC幅 `{example['rounded_order_lc_pips']}` pipsが記録されています。",
            f"証拠: [{name}/isolated-orders.jsonl]({name}/isolated-orders.jsonl)"])
    lines.extend(["", "## 修正候補", "",
        "`main/classInspection.py`の`order_result_row`は、丸めたpips損益を価格丸め後のLC幅で割り、理想LC幅から算出・丸めた`actual_risk_yen`を掛けています。異なる基準のLC幅と表示用丸めが金額に混入するため、数量と約定価格からの損益と一致しない場合があります。",
        "修正案は、実際の約定・決済価格差×方向×数量で決済通貨の損益を計算し、USD建て通貨だけ注文記録の`usd_jpy_rate`で円換算することです。pipsやLCリスクの丸めは表示・参考指標に限定します。",
        "回帰検証はUSD_JPY・EUR_USD・AUD_USD、買い／売り、数量上限あり／なし、価格丸めでLC幅が変わる注文、SL・TP・時間決済を対象にします。未約定・未決済を実現損益に含めません。",
        "現時点では不具合候補としての提案です。main側の売買・表示ロジックは変更していません。", ""])
    (root/"MONETARY-AUDIT.md").write_text("\n".join(lines), encoding="utf-8")
    return audit


def audit_execution(root, *, complete=None):
    """Reclassify saved executions only; never rerun or change the simulated trades."""
    from collections import OrderedDict
    from datetime import datetime, time, timedelta, timezone
    import pandas as pd
    from ogami_oanda.adapters.repositories.historical_store import HistoricalStore
    from .data import fixed_spread
    from .execution import classify_execution

    root = Path(root)

    class Quotes:
        def __init__(self, pair):
            self.pair = pair
            self.store = HistoricalStore(root/'source/history'/pair,pair)
            self.days = OrderedDict()

        def bounds(self, start, end):
            return pd.Timestamp(start).to_pydatetime(), None

        def candle(self, stamp, fixed=False):
            day=stamp.date()
            if day not in self.days:
                start=datetime.combine(day,time(),tzinfo=timezone.utc)
                self.days[day]={bar.time:bar for bar in self.store.read(start,start+timedelta(days=1))}
                if len(self.days)>3:
                    self.days.popitem(last=False)
            self.days.move_to_end(day)
            candle=self.days[day][stamp]
            return fixed_spread(candle,self.pair) if fixed else candle

    counts=Counter()
    examples={}
    changed=[]
    for path in sorted(root.glob('*/*/run/isolated-orders.jsonl')):
        name=str(path.parent.relative_to(root))
        quotes=Quotes(path.parent.parent.name)
        with path.open() as stream:
            for line in stream:
                try:
                    record=json.loads(line)
                except json.JSONDecodeError:
                    if not line.endswith('\n'):
                        break
                    raise
                _,causes=classify_execution(record['main'],record['ogami'],record['candidate'],record['events'],quotes)
                for cause in causes:
                    counts[f'{name}:{cause}']+=1
                    examples.setdefault(f'{name}:{cause}',{'at':record['at'],'ordinal':record['ordinal'],
                                                         'main':record['main'],'ogami':record['ogami']})
                if causes!=record['causes']:
                    changed.append({'run':name,'at':record['at'],'ordinal':record['ordinal'],
                                    'original_causes':record['causes'],'reviewed_causes':causes})
    controller=root/'controller.json'
    if complete is None:
        complete=controller.exists() and json.loads(controller.read_text()).get('status')=='complete'
    payload={'status':'complete' if complete else 'provisional','categories':dict(counts),'first_examples':examples,
             'classification_changes':changed,
             'classifier_sha256':hashlib.sha256(Path(__file__).with_name('execution.py').read_bytes()).hexdigest()}
    write_json(root/'execution-review.json',payload)
    return payload
