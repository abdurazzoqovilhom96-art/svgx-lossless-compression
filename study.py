#!/usr/bin/env python3
"""Portable controller of the SVG experiment (the .cmd launchers call this file).

    python study.py prepare [--skip-fetch] [--skip-tests]
    python study.py selftest
    python study.py status
    python study.py run [--scope pilot|full] [--resume --run-id RUN_ID]
    python study.py approve --reply "<foydalanuvchining aniq javobi>"
    python study.py report --run-id RUN_ID
    python study.py package --run-id RUN_ID
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from runner.common import RESULTS, STATE, VENV_PY, read_json, say  # noqa: E402


def in_venv() -> bool:
    try:
        return Path(sys.executable).resolve() == VENV_PY.resolve()
    except OSError:
        return False


def reexec_in_venv(argv: list[str]) -> int:
    return subprocess.call([str(VENV_PY), str(ROOT / "study.py"), *argv])


def cmd_prepare(a) -> int:
    from runner import pyenv
    if not in_venv():
        say("SVG tajribasi: tayyorgarlik boshlandi (bootstrap Python bilan virtual muhit yaratiladi)")
        pyenv.ensure()
        return reexec_in_venv(["prepare", *(["--skip-fetch"] if a.skip_fetch else []), *(["--skip-tests"] if a.skip_tests else [])])
    from runner.prepare import run_prepare
    return run_prepare(skip_fetch=a.skip_fetch, skip_tests=a.skip_tests)


def cmd_selftest(a) -> int:
    from runner.selftest import run_selftest
    r = run_selftest()
    say(f"Self-test: {'muvaffaqiyatli' if r['ok'] else 'XATO'} · cargo {r['cargo_tests_passed']} · pytest {r['pytest_summary']}"
        f" · fixture'lar {r['fixtures']}")
    return 0 if r["ok"] else 1


def cmd_status(a) -> int:
    from runner import approval
    fz = approval.load_freeze(STATE)
    ok, why, rec = approval.check(STATE, fz, None)
    say(f"Muzlatish: {'bor' if fz else 'yo‘q'}" + (f" ({fz['design_id']}, {fz['build_id']})" if fz else ""))
    if rec is None:
        say("Ruxsat: kutilmoqda (qaror yozilmagan). Haqiqiy job'lar yuborilmaydi.")
    else:
        say(f"Ruxsat: {rec['decision']} / doira {rec.get('scope')} / {rec['recorded_utc']} · tekshiruv: {'ok' if ok else why}")
    runs = sorted(p.name for p in RESULTS.iterdir() if p.is_dir()) if RESULTS.exists() else []
    say("Run'lar: " + (", ".join(runs) if runs else "yo‘q"))
    return 0


def cmd_approve(a) -> int:
    """Records a genuine explicit reply relayed from chat (same operation as the terminal prompt)."""
    from runner import approval
    fz = approval.load_freeze(STATE)
    if fz is None:
        say("Muzlatilgan holat yo'q — avval prepare.")
        return 2
    mism = approval.binding_mismatches(fz)
    if mism:
        say("Muzlatilgan fayllar o'zgargan, qaror yozilmadi: " + ", ".join(mism[:5]))
        return 4
    decision, scope = approval.parse_reply(a.reply)
    if decision is None:
        say("Javob bo'sh yoki aniq emas — qaror yozilmadi.")
        return 3
    rec = approval.record_decision(STATE, decision=decision, scope=scope, source=a.source, reply_text=a.reply, freeze=fz)
    say(f"Qaror yozildi: {rec['decision']} / doira {rec['scope']} / {rec['recorded_utc']} / freeze {rec['freeze_sha256'][:12]}")
    return 0


def cmd_run(a) -> int:
    from runner.controller import run_study
    summary = ""
    ready = ROOT / "readiness" / "READY_UZ.md"
    if ready.exists():
        summary = ready.read_text(encoding="utf-8")[:4000]
    return run_study(scope_flag=a.scope, resume=a.resume, run_id=a.run_id, summary_uz=summary)


def cmd_report(a) -> int:
    run = RESULTS / a.run_id
    if not run.exists():
        say(f"Run topilmadi: {a.run_id}")
        return 2
    from reporting.build import build
    s = build(run)
    say(f"Hisobotlar qayta yaratildi: {len(s['outputs'])} fayl · {run / '11_reports'}")
    return 0


def cmd_package(a) -> int:
    run = RESULTS / a.run_id
    if not run.exists():
        say(f"Run topilmadi: {a.run_id}")
        return 2
    from tools.package import make_package
    r = make_package(run)
    say(f"Paket: {r['zip']} · tekshiruv: {'ok' if r['ok'] else 'XATO'} ({r['checked']} a'zo)")
    return 0 if r["ok"] else 1


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="study.py", description="SVG byte-exact tajribasi boshqaruvchisi")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare", help="tayyorgarlik (qayta ishga tushirish xavfsiz)")
    p.add_argument("--skip-fetch", action="store_true", help="tarmoqdan qayta yuklamaslik (kesh/manifestdan)")
    p.add_argument("--skip-tests", action="store_true")
    sub.add_parser("selftest", help="sun'iy sinovlar")
    sub.add_parser("status", help="muzlatish va ruxsat holati")
    p = sub.add_parser("run", help="ruxsat berilgan tadqiqotni ishga tushirish/davom ettirish")
    p.add_argument("--scope", choices=["pilot", "full"])
    p.add_argument("--resume", action="store_true")
    p.add_argument("--run-id")
    p = sub.add_parser("approve", help="foydalanuvchining aniq javobini qaror sifatida yozish")
    p.add_argument("--reply", required=True)
    p.add_argument("--source", default="chat", choices=["chat", "terminal"])
    p = sub.add_parser("report", help="hisobotlarni oflayn qayta yaratish")
    p.add_argument("--run-id", required=True)
    p = sub.add_parser("package", help="ZIP paket yaratish va tekshirish")
    p.add_argument("--run-id", required=True)
    a = ap.parse_args(argv)
    if a.cmd != "prepare" and not in_venv() and VENV_PY.exists():
        return reexec_in_venv(argv)
    os.environ.setdefault("PYTHONUTF8", "1")
    return {"prepare": cmd_prepare, "selftest": cmd_selftest, "status": cmd_status, "run": cmd_run,
            "approve": cmd_approve, "report": cmd_report, "package": cmd_package}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
