"""Read-only observation of comparison workers, including frozen older workers."""

from __future__ import annotations

from bisect import bisect_left
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from statistics import median
import threading
import time

from .common import write_json


STAGES = ("analysis", "C-fixed", "C-mba")
LABELS = {"load": "データ準備・集計照合", "analysis": "A/B 解析・注文別比較",
          "C-fixed": "C 固定スプレッド", "C-mba": "C 保存Bid/Ask", "complete": "完了"}
JST = timezone(timedelta(hours=9))


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


@lru_cache(maxsize=16)
def open_slots(root, start, end):
    """Use exactly the frozen main calendar, without importing main's startup."""
    import pandas as pd
    from .native import OfflineRuntime, inspection_sources

    times = pd.date_range(start, end, freq="5min", inclusive="left")
    with OfflineRuntime(sources=inspection_sources(Path(root)/"source/main")) as runtime:
        mask = runtime.load("fCandleDataQuality").oanda_market_open_mask(times)
    return tuple(at.timestamp() for at in times[mask])


def last_record(path, csv=False):
    """Bounded tail read; incomplete writes and very large records are ignored."""
    try:
        with path.open("rb") as stream:
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(max(0, size-65536))
            data = stream.read()
        rows = data.split(b"\n")[:-1]
        if size > 65536:
            rows = rows[1:]
        if not rows:
            return None
        row = rows[-1].decode()
        value = row.split(",")[0] if csv else json.loads(row).get("at")
        if value:
            datetime.fromisoformat(value)  # Reject a CSV header or a malformed timestamp.
        return value
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def observe_job(directory, slots, now):
    progress = read_json(directory/"progress.json")
    result = read_json(directory/"result.json")
    if not progress:
        return None
    stamp = (directory/"progress.json").stat().st_mtime
    started = stamp-progress.get("elapsed_seconds", 0)
    complete = (progress.get("status") == "complete" and result.get("status") == "complete"
                and (directory/"normalized-hashes.json").exists())
    stage = "complete" if complete else progress.get("stage", "load")
    if not complete:
        for label in ("C-fixed", "C-mba"):
            if (directory/label/"run.json").exists():
                stage = label
    at = progress.get("at") if stage == progress.get("stage") else None
    trace = directory/"analysis.jsonl" if stage == "analysis" else directory/stage/"equity.csv"
    tail = last_record(trace, csv=stage != "analysis")
    if tail:
        at = tail
        stamp = trace.stat().st_mtime
    boundary = datetime.fromisoformat(at).timestamp() if at else 0
    # Analysis records describe a completed decision at the beginning of a slot.
    if tail and stage == "analysis":
        boundary += 300
    units = bisect_left(slots, boundary)
    fraction = min(1, units/len(slots)) if slots else 0
    done = 3*len(slots) if complete else (
        STAGES.index(stage)*len(slots)+units if stage in STAGES else 0)
    return {"directory": str(directory), "stage": stage, "at": at,
            "status": "complete" if complete else result.get("status", "running"),
            "phase_percent": 100 if complete else round(100*fraction, 2),
            "units": units, "total_units": len(slots), "done_units": done,
            "started_at": started, "observed_at": stamp, "elapsed_seconds": max(0, stamp-started),
            "age_seconds": max(0, now-stamp), "counts": progress.get("counts", {})}


def choose_job(parent, attempt, slots, now):
    paths = [p for p in parent.glob(f"{attempt}*")
             if p.name == attempt or p.name.removeprefix(attempt+"-").isdigit()]
    jobs = [job for path in paths if (job := observe_job(path, slots, now))]
    complete = [job for job in jobs if job["status"] == "complete"]
    return min(complete, key=lambda job: job["started_at"]) if complete else (
        max(jobs, key=lambda job: job["started_at"]) if jobs else None)


def update_rates(jobs, previous):
    samples = dict(previous.get("samples", {}))
    rates = dict(previous.get("rates", {}))
    for pair, job in jobs:
        if job["stage"] not in STAGES or job["status"] != "running":
            continue
        key = job["directory"]+":"+job["stage"]
        first = samples.setdefault(key, {"units": job["units"], "elapsed": job["elapsed_seconds"]})
        delta = job["units"]-first["units"]
        elapsed = job["elapsed_seconds"]-first["elapsed"]
        if delta >= 12 and elapsed >= 30:
            rates[pair+":"+job["stage"]] = elapsed/delta
    return {"samples": samples, "rates": rates}


def scenario(pairs, ends, jobs, slots, rates, workers, now, status):
    total = done = 0
    remaining_by_pair = []
    assumptions = set()
    unknown = False
    for pair, end in ends.items():
        planned = [(pairs["pilot_to"], "run")]
        if end != pairs["pilot_to"]:
            planned.append((end, "run"))
        planned.append((end, "repeat"))
        remaining = pair_done = 0
        for until, attempt in planned:
            size = len(slots[until])
            total += 3*size
            job = jobs.get((pair, until, attempt))
            completed = job["done_units"] if job else 0
            done += completed
            pair_done += completed
            for index, stage in enumerate(STAGES):
                left = size-min(size, max(0, completed-index*size))
                if not left:
                    continue
                rate = rates.get(pair+":"+stage)
                if rate is None:
                    rate = rates.get(pair+":analysis")
                    assumptions.add(stage)
                if rate is None:
                    unknown = True
                else:
                    remaining += left*rate
        remaining_by_pair.append((pair_done > 0, remaining))
    # Each executor slot owns one pair through its extension and repeat.
    lanes = [0.0]*max(1, min(workers, len(ends)))
    for _, remaining in sorted(remaining_by_pair, reverse=True):
        lane = min(range(len(lanes)), key=lanes.__getitem__)
        lanes[lane] += remaining
    seconds = None if unknown or status != "running" or total == done else max(lanes)
    percent = 100 if status == "complete" else min(99.9, 100*done/total) if total else 0
    return {"selected_ends": ends, "percent": round(percent, 2), "done_units": done,
            "total_units": total, "remaining_seconds": seconds,
            "estimated_finish": datetime.fromtimestamp(now+seconds, timezone.utc).isoformat() if seconds is not None else None,
            "assumed_analysis_speed_for": sorted(assumptions)}


def build_status(root, conditions, controller, previous=None, now=None, active=True, calendars=None):
    now = time.time() if now is None else now
    previous = previous or {}
    ends = {conditions["pilot_to"], conditions["max_to"]}
    slots = calendars if calendars is not None else {
        end: open_slots(str(root), conditions["from"], end) for end in ends}
    jobs = {}
    for pair in conditions["pairs"]:
        for end in ends:
            parent = root/f"{conditions['from'][:10]}_{end[:10]}"/pair
            for attempt in ("run", "repeat"):
                job = choose_job(parent, attempt, slots[end], now)
                if job:
                    jobs[pair, end, attempt] = job
    state = update_rates([(key[0], job) for key, job in jobs.items()], previous)
    state["workers"] = controller.get("workers", previous.get("workers", len(conditions["pairs"])))
    rates = dict(state["rates"])
    # Bootstrap older frozen jobs before the observer has measured a slope.
    for (pair, _, _), job in jobs.items():
        if pair+":analysis" not in rates:
            if job["stage"] == "analysis" and job["units"] >= 12:
                rates[pair+":analysis"] = job["elapsed_seconds"]/job["units"]
            elif job["status"] == "complete" and job["total_units"]:
                rates[pair+":analysis"] = job["elapsed_seconds"]/(3*job["total_units"])
    fallback = median(rates.values()) if rates else None
    for pair in conditions["pairs"]:
        if fallback is not None:
            rates.setdefault(pair+":analysis", fallback)
    status = controller.get("status", "waiting")
    if status == "running" and not active:
        status = "interrupted"
    low, high, rows = {}, {}, []
    for pair in conditions["pairs"]:
        pilot = jobs.get((pair, conditions["pilot_to"], "run"))
        result = read_json(Path(pilot["directory"])/"result.json") if pilot else {}
        extension = result.get("needs_extension") if result.get("status") == "complete" else None
        low[pair] = conditions["max_to"] if extension else conditions["pilot_to"]
        high[pair] = conditions["pilot_to"] if extension is False else conditions["max_to"]
        observed = [(key, job) for key, job in jobs.items() if key[0] == pair]
        current = max(observed, key=lambda item: item[1]["started_at"]) if observed else None
        rows.append({"pair": pair, "extension": extension, "end": current[0][1] if current else None,
                     "attempt": current[0][2] if current else None, "current": current[1] if current else None})
    if status == "running" and any(row["current"] and row["current"]["status"] == "failed" for row in rows):
        status = "failed"
    stale = any(row["current"] and row["current"]["status"] == "running"
                and row["current"]["age_seconds"] > 900 for row in rows)
    effective_status = "stale" if stale and status == "running" else status
    scenarios = {"selected" if low == high else "without_optional_extension":
                 scenario(conditions, low, jobs, slots, rates, state["workers"], now, effective_status)}
    if low != high:
        scenarios["with_optional_extension"] = scenario(
            conditions, high, jobs, slots, rates, state["workers"], now, effective_status)
    starts = [job["started_at"] for job in jobs.values()]
    observed_end = max((job["observed_at"] for job in jobs.values()), default=now)
    elapsed_until = now if status == "running" else observed_end
    return {"schema_version": 1, "status": status, "updated_at": datetime.fromtimestamp(now, timezone.utc).isoformat(),
            "elapsed_seconds": max(0, elapsed_until-min(starts)) if starts else 0,
            "stale": stale, "pairs": rows, "scenarios": scenarios, "estimator_state": state,
            "estimation": "Open M5 decisions per stage; A/B, fixed, MBA equally weighted for percent. "
                          "ETA uses observed stage rates; unmeasured stages borrow A/B speed. "
                          "Initial A/B rate includes preparation. Future preparation/final reports are unmeasured. "
                          "No ETA during interruption, failure, stale progress, or insufficient samples.",
            "observer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def local_time(value):
    return datetime.fromisoformat(value).astimezone(JST).strftime("%Y-%m-%d %H:%M:%S JST") if value else "推定待ち"


def duration(seconds):
    if seconds is None:
        return "推定待ち"
    minutes = max(0, round(seconds/60))
    return f"{minutes//60}時間{minutes%60:02d}分"


def render(status):
    names = {"running": "実行中", "complete": "完了", "failed": "失敗", "interrupted": "中断", "waiting": "開始待ち"}
    lines = ["# 抵抗線ブレイク比較の進捗", "",
             f"状態: **{names.get(status['status'], status['status'])}** ／ 更新: {local_time(status['updated_at'])}", "",
             f"経過: {duration(status['elapsed_seconds'])}。30秒ごとに更新します。", "",
             "| 完了条件 | 全工程の進捗 | 推定残り時間 | 完了予測時刻 |", "|---|---:|---|---|"]
    for key, estimate in status["scenarios"].items():
        name = {"selected": "確定した対象期間＋独立再実行", "without_optional_extension": "未確定の通貨は7日で終了＋独立再実行",
                "with_optional_extension": "未確定の通貨は1か月へ延長＋独立再実行"}[key]
        remaining = "0時間00分" if status["status"] == "complete" else duration(estimate["remaining_seconds"])
        finish = "完了" if status["status"] == "complete" else local_time(estimate["estimated_finish"])
        lines.append(f"| {name} | {estimate['percent']:.1f}% | {remaining} | {finish} |")
    lines += ["", "| 通貨 | 実行 | 対象期間の終了（UTC・未満） | 現在の段階 | 段階内の進捗 | 処理済み時刻（UTC） | 記録の経過 |",
              "|---|---|---|---|---:|---|---|"]
    for row in status["pairs"]:
        job = row["current"]
        if not job:
            lines.append(f"| {row['pair']} | 待機 | — | — | — | — | — |")
            continue
        attempt = "独立再実行" if row["attempt"] == "repeat" else "初回"
        lines.append(f"| {row['pair']} | {attempt} | {row['end'][:10]} | {LABELS.get(job['stage'], job['stage'])} | "
                     f"{job['phase_percent']:.1f}% | {job['at'] or '—'} | {round(job['age_seconds'])}秒前 |")
    lines += ["", "進捗率は休場を除く5分判断数を使い、A/B・固定スプレッド再生・保存Bid/Ask再生を等重みで集計します。"
              "独立再実行も分母に含み、最終レポート完成前は100%にしません。時間の消化率ではありません。", "",
              "**完了予測は概算です。** 段階ごとの実測速度を優先し、未計測の段階はA/Bと同速度と仮定します。"
              "初期の速度にはデータ準備を含みます。今後の準備・最終集計時間は未計測です。"
              "延長の判定、候補数、CPU負荷に応じて更新されます。", ""]
    if status["stale"]:
        lines += ["15分以上更新されていない実行があります。進捗の再観測まで完了予測を保留します。", ""]
    if status["status"] in {"failed", "interrupted"}:
        lines += ["実行が停止しているため完了予測を表示していません。保存済みの進捗を表示しています。", ""]
    lines += ["- [機械可読の進捗・予測](progress.json)", "- [コントローラー](controller.json)",
              "- [円損益の追加監査](MONETARY-AUDIT.md)", "- [約定差の再分類](execution-review.json)",
              "- [検証結果](validation.json)", "",
              "全通貨の独立再実行後に `REPORT.md` と `comparison.json` を生成します。"
              "実行中の解析コードは `source/` に固定し、この表示は既存の成果物だけを観測します。", ""]
    return "\n".join(lines)


def controller_active(root):
    try:
        with (root/"controller.lock").open("r") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
    except FileNotFoundError:
        pass
    return False


def refresh(root):
    status = build_status(root, read_json(root/"conditions.json"), read_json(root/"controller.json"),
                          read_json(root/"progress.json").get("estimator_state", {}), active=controller_active(root))
    write_json(root/"progress.json", status)
    temporary = root/"RUNNING.md.tmp"
    temporary.write_text(render(status), encoding="utf-8")
    temporary.replace(root/"RUNNING.md")
    return status


@contextmanager
def observer_lock(root):
    with (root/"progress.lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("a progress observer is already running for this output") from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def watch(root, once=False):
    with observer_lock(root):
        while True:
            status = refresh(root)
            print(json.dumps({"status": status["status"], "updated_at": status["updated_at"],
                              "scenarios": status["scenarios"]}, ensure_ascii=False), flush=True)
            if once or status["status"] in {"complete", "failed", "interrupted"}:
                return status
            time.sleep(30)


@contextmanager
def background_progress(root):
    stop = threading.Event()

    def observe():
        try:
            with observer_lock(root):
                while not stop.is_set():
                    try:
                        refresh(root)
                    except Exception as error:
                        print(f"progress observer: {type(error).__name__}: {error}", flush=True)
                    stop.wait(30)
                refresh(root)
        except Exception as error:
            # Monitoring must not change the outcome of a comparison worker.
            print(f"progress observer: {type(error).__name__}: {error}", flush=True)

    thread = threading.Thread(target=observe, name="comparison-progress", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=30)
