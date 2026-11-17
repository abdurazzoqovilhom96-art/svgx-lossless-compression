"""Run controller for the authorized study (pilot → dated decision → confirmation → reports → package).

Every real entry point goes through `run_study`, which requires a recorded decision bound to the
frozen state, and the dispatcher re-checks authorization before each launch (also on resume).
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Callable

from . import approval
from .common import RESULTS, ROOT, STATE, atomic_write_json, read_json, say, sha256_bytes, study_config, utc_now
from .jobs import JobSpec, Ledger, RunLock, dispatch
from .results import init_run_tree, set_status

EXIT_OK, EXIT_NOT_PREPARED, EXIT_PENDING, EXIT_REFUSED, EXIT_PAUSED = 0, 2, 3, 4, 5


def read_manifest(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_id(freeze: dict) -> str:
    return freeze.get("build_id", "build-unknown")


def size_jobs(split: str, rows: list[dict], bid: str, external: list[str]) -> list[JobSpec]:
    jobs = []
    for r in rows:
        jobs.append(JobSpec(split, r["sha256"], bid, "svgx", 0, "size", {"file_id": r["file_id"]}))
        for m in external:
            jobs.append(JobSpec(split, r["sha256"], bid, m, 0, "size", {"file_id": r["file_id"]}))
    return jobs


def timing_jobs(split: str, sample: list[dict], bid: str, methods: list[str], repeats: int, seed: str) -> list[JobSpec]:
    """Warm-up (repeat 0) plus `repeats` measured repeats; reproducibly interleaved per repeat."""
    jobs = []
    for r in range(repeats + 1):
        pairs = [(s["sha256"], m) for s in sample for m in methods]
        pairs.sort(key=lambda p: hashlib.sha256(f"{seed}|{split}|{r}|{p[0]}|{p[1]}".encode()).hexdigest())
        for sha, m in pairs:
            jobs.append(JobSpec(split, sha, bid, m, r, "timing", {}))
    return jobs


def _inputs(root: Path, rows: list[dict]) -> dict[str, str]:
    return {r["sha256"]: str((root / r["original"]).resolve()) for r in rows}


def new_run_id(freeze: dict) -> str:
    return utc_now().replace("-", "").replace(":", "").replace("T", "_").rstrip("Z") + "_" + freeze["design_id"]


def pilot_decision(run: Path, freeze: dict, rows_by_split: dict) -> dict:
    """Dated decision record after the pilot and before any confirmation evaluation."""
    from reporting import stats as S
    from reporting.build import collect
    path = run / "07_statistics" / "pilot_decision.json"
    rec = read_json(path)
    if rec:
        return rec
    data = collect(run)
    rows = data["splits"].get("pilot", {}).get("rows", [])
    summary = {"n": len(rows), "sum_B": sum(r["B"] for r in rows), **{f"sum_C_{p}": sum(r[f"C_{p}"] for r in rows) for p in "DPIUG"}}
    rec = {"design_id": freeze["design_id"], "build_id": build_id(freeze), "recorded_utc": utc_now(),
           "cstar": S.cstar_selection(rows), "pilot_targets": S.pilot_targets(rows) if rows else None,
           "pilot_summary": summary,
           "pilot_summary_sha256": sha256_bytes(json.dumps(summary, sort_keys=True).encode()),
           "rule_source": "frozen selection rule in config/study.toml [design] cstar_candidates / cstar_tie_break"}
    atomic_write_json(path, rec)
    return rec


def run_study(*, scope_flag: str | None = None, resume: bool = False, run_id: str | None = None,
              state_dir: Path = STATE, results_root: Path = RESULTS, root: Path = ROOT,
              worker_factory: Callable | None = None, interactive: bool | None = None, input_fn=input,
              summary_uz: str = "", synthetic: bool = False, package: bool = True) -> int:
    cfg = study_config()
    freeze = approval.load_freeze(state_dir)
    if freeze is None:
        say("Tayyorgarlik tugallanmagan: state/freeze.json topilmadi. Avval .\\prepare.cmd ni bajaring.")
        return EXIT_NOT_PREPARED
    ok, why, rec = approval.check(state_dir, freeze, None, root)
    if rec is None:
        if interactive is None:
            interactive = approval.is_interactive()
        if not interactive:
            say("HOLAT: ruxsat kutilmoqda. Haqiqiy SVG tajribasi uchun qaror hali yozilmagan; hech narsa ishga tushirilmadi.")
            say(approval.QUESTION_UZ)
            return EXIT_PENDING
        rec = approval.interactive_prompt(state_dir, freeze, summary_uz or "Tayyorlik hisoboti: readiness/READY_UZ.md",
                                          input_fn=input_fn)
        if rec is None:
            return EXIT_PENDING
        ok, why, rec = approval.check(state_dir, freeze, None, root)
    if not ok:
        say(f"Ishga tushirish rad etildi: {why}. Hech qanday haqiqiy job yuborilmadi.")
        return EXIT_REFUSED
    scope = rec["scope"]
    if scope_flag == "full" and scope == "pilot":
        say("Ruxsat faqat pilot uchun berilgan. To'liq tadqiqot uchun alohida aniq ruxsat kerak.")
        return EXIT_REFUSED
    run_scope = "pilot" if scope_flag == "pilot" else scope
    # run directory
    if resume:
        if not run_id or not (Path(results_root) / run_id).exists():
            say(f"Davom ettirish uchun mavjud run topilmadi: {run_id}")
            return EXIT_REFUSED
    else:
        run_id = run_id or new_run_id(freeze)
    run = init_run_tree(Path(results_root), run_id, scope=run_scope, synthetic=synthetic)
    meta = read_json(run / "01_protocol" / "run.json", {}) or {}
    if meta and meta.get("freeze_sha256") != approval.freeze_hash(freeze):
        say("Run boshqa muzlatilgan holat bilan boshlangan — xesh mos emas, job yuborilmadi.")
        return EXIT_REFUSED
    meta.update({"run_id": run_id, "design_id": freeze["design_id"], "build_id": build_id(freeze), "scope": run_scope,
                 "synthetic": synthetic, "freeze_sha256": approval.freeze_hash(freeze), "approval": rec,
                 "study_config": cfg, "updated_utc": utc_now()})
    meta.setdefault("started_utc", utc_now())
    atomic_write_json(run / "01_protocol" / "run.json", meta)
    atomic_write_json(run / "01_protocol" / "freeze.json", freeze)
    atomic_write_json(run / "01_protocol" / "approval.json", rec)
    for extra in ("environment.json", "baselines.json"):
        src = Path(root) / "readiness" / extra
        if src.exists():
            shutil.copyfile(src, run / "01_protocol" / extra)
    set_status(run, "01_protocol", "complete", "frozen settings, approval and environment copied", scope=run_scope,
               synthetic=synthetic)
    manifests = {}
    for split, rel in freeze["manifests"].items():
        p = Path(root) / rel
        manifests[split] = read_manifest(p)
        shutil.copyfile(p, run / "02_corpus" / f"{split}.csv")
    for rel in freeze.get("corpus_files", []):
        p = Path(root) / rel
        if p.exists():
            shutil.copyfile(p, run / "02_corpus" / p.name)
    set_status(run, "02_corpus", "complete", "manifests, sources, dedup decisions", scope=run_scope, synthetic=synthetic,
               coverage={s: len(r) for s, r in manifests.items()})
    samples = {s: read_manifest(Path(root) / rel) for s, rel in freeze.get("timing_samples", {}).items()}
    from baselines.adapters import methods as all_methods
    meths = all_methods()
    external = [n for n, m in meths.items() if not m.project and not m.speed_only and m.available()[0]]
    timed = [n for n, m in meths.items() if m.available()[0]]
    bid = build_id(freeze)
    inputs = {}
    for rows in manifests.values():
        inputs.update(_inputs(Path(root), rows))
    if worker_factory is None:
        from .tasks import RealWorker
        worker = RealWorker(run, inputs, float(cfg["run"]["job_timeout_seconds"]))
    else:
        worker = worker_factory(run, inputs)

    def gate(job: JobSpec):
        ok_, why_, _ = approval.check(state_dir, freeze, job.split, root)
        if ok_ and run_scope == "pilot" and job.split != "pilot":
            return False, "run doirasi faqat pilot"
        return ok_, why_

    ledger = Ledger(run / "ledger.sqlite")
    lock = RunLock(run / "run.lock")
    try:
        stale = lock.acquire()
        if stale:
            ledger.event("stale_lock_taken_over", stale)
        ledger.event("run_start", {"scope": run_scope, "resume": resume, "pid": os.getpid()})
        workers = max(1, min(int(cfg["run"]["max_workers"]), (os.cpu_count() or 2) - 2))
        retries = int(cfg["run"]["retries"])
        tcfg = cfg["timing"]
        splits = ["pilot"] + (["confirmation"] if run_scope == "full" else [])
        for split in splits:
            ok_s, why_s, _ = approval.check(state_dir, freeze, split, root)
            if not ok_s:
                say(f"{split}: ruxsat yo'q — {why_s}")
                return EXIT_REFUSED
            say(f"[{split}] o'lcham va tekshiruv job'lari: {len(manifests[split])} fayl")
            c1 = dispatch(ledger, size_jobs(split, manifests[split], bid, external), worker, gate, max_workers=workers,
                          retries=retries, on_progress=_progress(split, "size"))
            say(f"[{split}] o'lcham: {c1}")
            if ledger.paused_scopes():
                say("Asosiy dekodlash nuqsoni aniqlandi: dalillar saqlandi, ta'sirlangan taqqoslashlar to'xtatildi.")
                set_status(run, "04_verification", "paused", "reproducible decoding defect; see defects/", scope=run_scope)
                return EXIT_PAUSED
            tj = timing_jobs(split, samples.get(split, []), bid, timed, int(tcfg["repeats"]), tcfg["seed"])
            c2 = dispatch(ledger, tj, worker, gate, max_workers=1, retries=retries, on_progress=_progress(split, "timing"))
            say(f"[{split}] vaqt o'lchovi: {c2}")
            if split == "pilot":
                pd = pilot_decision(run, freeze, manifests)
                say(f"Pilot qaror yozuvi: C* = {pd['cstar']['selected']} (xesh {pd['pilot_summary_sha256'][:12]})")
        from reporting.build import build as build_reports
        build_reports(run, synthetic=synthetic)
        if run_scope == "pilot":
            set_status(run, "12_reproducibility", "pilot-only", "pilot complete; confirmation awaits a separate decision",
                       scope=run_scope)
            say("Pilot yakunlandi. Tasdiqlash bosqichi uchun alohida qaror kutilmoqda.")
        if package:
            from tools.package import make_package
            make_package(run, root=Path(root))
        ledger.event("run_end", {"scope": run_scope})
        return EXIT_OK
    finally:
        lock.release()
        ledger.close()


def _progress(split: str, kind: str):
    last = {"t": 0}

    def f(done: int, total: int) -> None:
        import time
        now = time.monotonic()
        if done == total or now - last["t"] > 10:
            last["t"] = now
            say(f"  [{split}/{kind}] {done}/{total}")
    return f
