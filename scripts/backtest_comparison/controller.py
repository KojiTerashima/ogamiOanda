"""Snapshot inputs and execute isolated workers, then independently repeat results."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
import fcntl
from datetime import datetime, timedelta
import hashlib
import json
import os
import shutil
import subprocess
import sys

from ogami_oanda.adapters.repositories.historical_store import HistoricalStore
from ogami_oanda.entrypoints.backtest_run import runtime_versions

from .common import write_json
from .native import NativeAnalysis, inspection_sources
from .report import make_report
from .progress import background_progress
from .runner import normalized_hashes


def revision(directory):
    return subprocess.check_output(["git", "-C", str(directory), "rev-parse", "HEAD"], text=True).strip()


def snapshot(root, repo, main, data, pairs, start, pilot_end, end):
    root.mkdir(parents=True, exist_ok=False)
    sources = inspection_sources(main)
    source_root = root/"source"
    main_root = source_root/"main"
    main_root.mkdir(parents=True)
    for name, content in sources.contents.items():
        (main_root/f"{name}.py").write_bytes(content)
    files = [p for p in (repo/"src").rglob("*") if p.is_file() and p.suffix in {".py", ".yaml"}]
    files += list((repo/"scripts/backtest_comparison").glob("*.py")) + [repo/"scripts/compare_main_backtest.py"]
    manifest = []
    for path in sorted(files):
        relative = path.relative_to(repo)
        target = source_root/"ogami"/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        content = path.read_bytes()
        target.write_bytes(content)
        manifest.append({"path":str(relative), "sha256":hashlib.sha256(content).hexdigest(), "bytes":len(content)})
    from_time = datetime.fromisoformat(start)-timedelta(days=28)
    until = datetime.fromisoformat(end)
    datasets = {}
    for pair in pairs:
        store = HistoricalStore(data/pair, pair)
        if not store.covers(from_time, until):
            raise ValueError(f"{pair}: local history does not cover warmup and maximum period")
        manifest_data = {**store.manifest,
                "intervals":[i for i in store.manifest["intervals"] if from_time <= datetime.fromisoformat(i["from"]) < until],
                "files":{day:e for day,e in store.manifest["files"].items()
                         if from_time.date().isoformat() <= day < until.date().isoformat()}}
        destination = source_root/"history"/pair
        destination.mkdir(parents=True)
        for entry in manifest_data["files"].values():
            # Use HistoricalStore's path checks; do not accept paths outside the dataset.
            source_file = store._file(entry)
            target = destination/entry["path"]
            shutil.copyfile(source_file, target)
            if hashlib.sha256(target.read_bytes()).hexdigest() != entry["sha256"]:
                raise ValueError(f"{pair}: snapshot file hash mismatch")
        write_json(destination/"manifest.json", manifest_data)
        datasets[pair] = manifest_data
    conditions = {"schema_version":1, "from":start, "pilot_to":pilot_end, "max_to":end, "pairs":pairs,
                  "warmup_days":28, "fixed_spread_pips":.8, "slippage_pips":.5,
                  "main_policy":NativeAnalysis(sources).policy(), "runtime_versions":runtime_versions(),
                  "revisions":{"ogami":revision(repo), "main":revision(main)},
                  "main_source_manifest":sources.manifest, "main_source_sha256":sources.sha256,
                  "ogami_source_manifest":manifest, "data_manifests":datasets,
                  "main_windows":{"M5":721, "M30":241, "H1":250},
                  "ogami_windows":{"M5":250, "M30":250, "H1":250, "S5":250},
                  "range":"start-inclusive/end-exclusive; main target interval overridden to 5 minutes",
                  "isolated_deadline":"expire after processing S5 at deadline; holding close on next observed open",
                  "no_network":True, "no_production_changes":True}
    write_json(root/"conditions.json", conditions)
    return conditions


def run_job(root, conditions, pair, end, attempt):
    parent = root/f"{conditions['from'][:10]}_{end[:10]}"/pair
    # Completed attempts are reusable only after verifying their actual artifact hashes.
    for directory in sorted(parent.glob(f"{attempt}*")) if parent.exists() else []:
        result = directory/"result.json"
        hashes = directory/"normalized-hashes.json"
        if result.exists() and hashes.exists() and json.loads(result.read_text()).get("status") == "complete":
            if normalized_hashes(directory) == json.loads(hashes.read_text()):
                return directory
    selected = attempt
    number = 1
    while (parent/selected).exists():
        number += 1
        selected = f"{attempt}-{number}"
    log_directory = root/"logs"
    log_directory.mkdir(exist_ok=True)
    command = [sys.executable, str(root/"source/ogami/scripts/compare_main_backtest.py"),
               "--worker", "--output-dir", str(root), "--pair", pair, "--end", end, "--attempt", selected]
    environment = {**os.environ, "PYTHONPATH":str(root/"source/ogami/src"), "PYTHONDONTWRITEBYTECODE":"1",
                   "OPENBLAS_NUM_THREADS":"1", "OMP_NUM_THREADS":"1"}
    with (log_directory/f"{pair}-{end[:10]}-{selected}.log").open("x") as log:
        subprocess.run(command, env=environment, cwd=root, stdout=log, stderr=subprocess.STDOUT, check=True)
    return parent/selected



def validate_snapshot(root, conditions):
    if runtime_versions() != conditions["runtime_versions"]:
        raise ValueError("runtime differs from the frozen comparison environment")
    for entry in conditions["ogami_source_manifest"]:
        path = root/"source/ogami"/entry["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("frozen ogami source was modified")
    for entry in conditions["main_source_manifest"]["files"]:
        path = root/"source/main"/entry["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("frozen main source was modified")
    for pair, expected in conditions["data_manifests"].items():
        actual = json.loads((root/"source/history"/pair/"manifest.json").read_text())
        if actual != expected:
            raise ValueError("frozen data manifest was modified")


@contextmanager
def controller_lock(root):
    with (root/"controller.lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("a controller is already running for this output") from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def run_comparison(root, conditions, workers):
    with controller_lock(root):
        validate_snapshot(root, conditions)
        write_json(root/"controller.json", {"status":"running", "pairs":conditions["pairs"], "workers":workers})
        with background_progress(root):
            return _run_comparison(root, conditions, workers)


def _run_comparison(root, conditions, workers):
    selections = {}

    def pair_job(pair):
        pilot = run_job(root, conditions, pair, conditions["pilot_to"], "run")
        result = json.loads((pilot/"result.json").read_text())
        end = conditions["max_to"] if result["needs_extension"] else conditions["pilot_to"]
        run = run_job(root, conditions, pair, end, "run") if end != conditions["pilot_to"] else pilot
        repeat = run_job(root, conditions, pair, end, "repeat")
        a,b = normalized_hashes(run), normalized_hashes(repeat)
        mismatch = {name:{"run":a.get(name),"repeat":b.get(name)} for name in a.keys()|b.keys() if a.get(name)!=b.get(name)}
        return {"pilot":str(pilot), "run":str(run), "repeat":str(repeat),
                "repeat_comparison":{"equal":not mismatch,"mismatches":mismatch,"files":len(a)}}

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            pending = {pool.submit(pair_job,pair):pair for pair in conditions["pairs"]}
            for future in as_completed(pending):
                pair = pending[future]
                selections[pair] = future.result()
                write_json(root/"controller.json", {"status":"running", "workers":workers, "completed":selections})
                print(f"{pair} comparison and independent repeat complete", flush=True)
        make_report(root, selections)
        write_json(root/"controller.json", {"status":"complete", "workers":workers, "completed":selections})
        return selections
    except BaseException as error:
        write_json(root/"controller.json", {"status":"failed", "workers":workers, "error_type":type(error).__name__, "completed":selections})
        raise
