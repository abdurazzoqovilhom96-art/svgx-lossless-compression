"""Preparation orchestrator (pre-authorized): environment, toolchain, build, fixtures, data, timing
sample, self-test, inventory, freeze and the Uzbek readiness report. Safe to re-run."""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .common import (CODEC_BIN, READINESS, ROOT, STATE, VENV_PY, atomic_write_json, atomic_write_text, canonical_json,
                     read_json, rel, run, say, sha256_bytes, sha256_file, study_config, tool_env, utc_now)

MAN = ROOT / "data" / "manifests"


def build_codec() -> dict:
    cargo = ROOT / ".tools" / "cargo" / "bin" / "cargo.exe"
    manifest = ROOT / "codec" / "Cargo.toml"
    say("  … svgx (Rust, release) yig'ilmoqda")
    run([cargo, "build", "--release", "--locked", "--manifest-path", manifest], env=tool_env(), capture=True)
    say("  … cargo test (release)")
    r = subprocess.run([str(cargo), "test", "--release", "--locked", "--manifest-path", str(manifest)],
                       capture_output=True, env=tool_env())
    out = (r.stdout + r.stderr).decode("utf-8", "replace")
    passed = sum(int(x.split()[0]) for x in [l.split("result: ok. ")[1] for l in out.splitlines() if "test result: ok." in l]) if r.returncode == 0 else 0
    return {"build": "ok", "cargo_test_returncode": r.returncode, "cargo_tests_passed": passed,
            "cargo_test_tail": out[-1500:] if r.returncode else "", "binary_sha256": sha256_file(CODEC_BIN)}


def timing_sample(split: str, rows: list[dict], cfg: dict) -> list[dict]:
    """Frozen from input metadata only: every category × size bracket with files, `per_cell` each."""
    t = cfg["timing"]
    br = list(t["size_brackets"])
    seed = t["seed"]

    def bracket(n: int) -> int:
        k = 0
        for i, lo in enumerate(br):
            if n >= lo:
                k = i
        return k
    cells = {}
    for r in rows:
        cells.setdefault((r["category"], bracket(int(r["size"]))), []).append(r)
    out = []
    for key in sorted(cells):
        rs = sorted(cells[key], key=lambda r: hashlib.sha256(f"{seed}|{split}|{r['sha256']}".encode()).hexdigest())
        for r in rs[: int(t["per_cell"])]:
            out.append({**r, "bracket": key[1], "bracket_low": br[key[1]]})
    return out


def write_csv(path: Path, rows: list[dict]) -> None:
    import io
    if not rows:
        atomic_write_text(path, "")
        return
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    atomic_write_text(path, buf.getvalue())


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def data_stage(skip_fetch: bool = False) -> dict:
    py = str(VENV_PY)
    if not skip_fetch:
        say("  … ochiq manbalardan SVG nomzodlari yuklanmoqda (davom ettiriladigan, muloyim tezlikda)")
        run([py, "-u", ROOT / "datasets" / "fetch.py", "public"], cwd=ROOT, env=tool_env())
    say("  … dedup, provenance guruhlari va split tanlovi")
    run([py, ROOT / "datasets" / "split.py"], cwd=ROOT, env=tool_env())
    cfg = study_config()
    out = {}
    for split in ("pilot", "confirmation"):
        rows = read_csv(MAN / f"{split}.csv")
        ts = timing_sample(split, rows, cfg)
        write_csv(MAN / f"timing_{split}.csv", ts)
        out[split] = {"files": len(rows), "timing_sample": len(ts)}
    return out


def bound_files() -> list[str]:
    pats = ["config/study.toml", "config/baselines.toml", "config/toolchain.toml", "docs/FORMAT.md", "docs/PROTOCOL.md",
            "docs/PROOF.md", "data/manifests/pilot.csv", "data/manifests/confirmation.csv", "data/manifests/dedup.csv",
            "data/manifests/design.json", "data/manifests/timing_pilot.csv", "data/manifests/timing_confirmation.csv",
            "data/sources.csv", "reference/decode.py", "baselines/adapters.py", "codec/Cargo.lock", "codec/Cargo.toml",
            "codec/build.rs", "readiness/baselines.json", "requirements.lock"]
    pats += sorted(rel(p) for p in (ROOT / "codec" / "src").glob("*.rs"))
    pats += sorted(rel(p) for p in (ROOT / "runner").glob("*.py"))
    pats += sorted(rel(p) for p in (ROOT / "reporting").glob("*.py"))
    pats.append(rel(CODEC_BIN))
    return pats


def freeze() -> dict:
    cfg = study_config()
    files = {p: sha256_file(ROOT / p) for p in bound_files() if (ROOT / p).exists()}
    build_src = sha256_bytes("".join(f"{k}:{v}\n" for k, v in sorted(files.items()) if k.startswith(("codec/", "reference/"))).encode())
    fz = {
        "design_id": cfg["design"]["id"], "format": cfg["design"]["format"], "frozen_utc": utc_now(),
        "build_id": "build-" + build_src[:12],
        "primary_settings": {"profile": cfg["design"]["primary_profile"], "brotli": "1.2.1 q11 lgwin22",
                             "window_blocks": cfg["model"]["window_blocks"], "top_candidates": cfg["model"]["top_candidates"],
                             "rescale_at": cfg["model"]["rescale_at"]},
        "manifests": {"pilot": "data/manifests/pilot.csv", "confirmation": "data/manifests/confirmation.csv"},
        "timing_samples": {"pilot": "data/manifests/timing_pilot.csv", "confirmation": "data/manifests/timing_confirmation.csv"},
        "corpus_files": ["data/sources.csv", "data/manifests/dedup.csv", "data/manifests/design.json"],
        "bound_files": files,
    }
    atomic_write_json(STATE / "freeze.json", fz)
    return fz


def baselines_inventory() -> dict:
    from baselines.adapters import methods, roundtrip
    from .common import FIXTURES
    out = {"generated_utc": utc_now(), "methods": {}}
    sample = FIXTURES / "svg" / "gen_structured_wins.svg"
    import tempfile
    for name, m in methods().items():
        d = m.describe()
        d["version"] = _version(m)
        if d["available"]:
            with tempfile.TemporaryDirectory() as td:
                try:
                    d["fixture_roundtrip"] = roundtrip(m, str(sample), td)
                except Exception as e:  # noqa: BLE001
                    d["fixture_roundtrip"] = {"roundtrip_ok": False, "error": str(e)}
        out["methods"][name] = d
    atomic_write_json(READINESS / "baselines.json", out)
    return out


def _version(m) -> str:
    args = {"brotli": ["--version"], "xz": ["--version"], "zstd": ["--version"], "gzip": ["--version"], "svgx": ["--version"],
            "7za": [], "xwrt": []}.get(m.tool, ["--version"])
    try:
        r = subprocess.run([m.exe, *args], capture_output=True, timeout=30)
        txt = (r.stdout + r.stderr).decode("utf-8", "replace").strip().splitlines()
        txt = [t for t in txt if t.strip()]
        import re
        return re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "<email>", txt[0])[:200] if txt else ""
    except Exception as e:  # noqa: BLE001
        return f"unavailable: {e}"


def estimate(selftest: dict, data: dict, cfg: dict) -> dict:
    """Pre-approval cost estimate from synthetic throughput and machine inventory only."""
    tp = selftest.get("throughput_MiB_s", {})
    design = read_json(MAN / "design.json", {}) or {}
    total_bytes = sum(v.get("bytes", 0) for v in (design.get("splits") or {}).values())
    workers = max(1, min(int(cfg["run"]["max_workers"]), 14))
    mib = total_bytes / (1 << 20)
    if not tp:
        return {"reliable": False, "reason": "synthetic throughput unavailable"}
    # size pass: every method compresses + decompresses once; project streams also decoded natively
    # and by the Python reference (2 × 10 streams per file)
    size_methods = {k: v for k, v in tp.items() if v and not k.startswith("svgx_") and k not in ("zstd1", "gzip1")}
    size_s = (sum(mib / max(v, 1e-6) for v in size_methods.values())       # external compress + decompress
              + 2 * mib / max(tp.get("svgx_G") or 1e-6, 1e-6)                # encode-all + native decodes
              + mib * 6 / max(tp.get("svgx_ref_decode") or 0.5, 1e-6))      # reference decodes of distinct streams
    n_files = sum(v.get("files", 0) for v in (design.get("splits") or {}).values())
    # per-process start-up costs (Windows): native ~0.06 s, Python reference decoder ~0.2 s
    size_s += n_files * (16 * 0.06 + 10 * 0.2)
    timing_files = sum(v.get("timing_sample", 0) for v in data.values()) if data else 0
    reps = int(cfg["timing"]["repeats"]) + 1
    avg_file_mib = mib / max(1, n_files)
    timed = [v for k, v in tp.items() if k != "svgx_ref_decode" and v]
    timing_s = timing_files * reps * sum(avg_file_mib / v + 2 * 0.06 for v in timed)
    est = {"reliable": True, "corpus_bytes": total_bytes, "files": n_files, "workers": workers,
           "size_and_verification_hours": size_s / workers / 3600, "timing_hours": timing_s / 3600,
           "assumptions": ["throughput measured on synthetic fixtures during self-test (cold processes)",
                           "process start-up: ~0.06 s per native invocation, ~0.2 s per Python reference decode",
                           f"{workers} parallel workers for size/verification jobs; timing stage sequential "
                           f"({timing_files} sampled files × {reps} runs × {len(timed)} methods)",
                           "real SVGs may be slower or faster than synthetic ones; large maps and diagrams dominate",
                           "rough estimate: a factor of two either way is plausible"]}
    est["total_hours"] = est["size_and_verification_hours"] + est["timing_hours"]
    return est


def ready_report(state: dict) -> str:
    st = state
    cfg = study_config()
    design = read_json(MAN / "design.json", {}) or {}
    bl = read_json(READINESS / "baselines.json", {}) or {}
    env = read_json(READINESS / "environment.json", {}) or {}
    sf = read_json(READINESS / "selftest.json", {}) or {}
    fz = read_json(STATE / "freeze.json", {}) or {}
    L = ["# SVG tajribasi — tayyorlik hisoboti", "",
         f"- Loyiha: `{ROOT}`", f"- Dizayn: `{fz.get('design_id')}` · build `{fz.get('build_id')}` · muzlatildi: {fz.get('frozen_utc')}",
         f"- Holat: **{'TAYYOR' if st.get('complete') else 'TUGALLANMAGAN'}**", ""]
    exp = read_json(ROOT / "fixtures" / "synthetic" / "expected.json", {}) or {}
    n_fix = len(exp.get("files", {}))
    n_streams = sum(len(v.get("streams", {})) for v in exp.get("files", {}).values())
    L += ["## Sinovlar", f"- Umumiy natija: {'muvaffaqiyatli' if sf.get('ok') else 'xato bor'}",
          f"- Rust unit testlari: {sf.get('cargo_tests_passed')} ta o'tdi", f"- pytest: {sf.get('pytest_summary')}",
          f"- Sun'iy fixture'lar: {sf.get('fixtures')} — {n_fix} ta SVG, {n_streams} ta oltin oqim; har biri native va "
          "mustaqil Python dekoderi bilan bayt-bayt tiklandi",
          f"- Launcherlar (PowerShell): {sf.get('launchers')}", ""]
    L += ["## Ma'lumotlar"]
    dd = {}
    dpath = MAN / "dedup.csv"
    if dpath.exists():
        for r in read_csv(dpath):
            key = r["reason"] if r["decision"] in ("removed", "grouped") else r["decision"].split(":")[0]
            dd[key] = dd.get(key, 0) + 1
    L.append(f"- Nomzodlar: {design.get('candidates')} ta, noyob: {design.get('unique')} ta, provenance komponentlari "
             f"(statistik oilalar): {design.get('components')} ta; dedup/guruhlash qarorlari: "
             + ", ".join(f"{k} {v}" for k, v in sorted(dd.items())))
    for s in ("pilot", "confirmation"):
        v = (design.get("splits") or {}).get(s)
        if not v:
            continue
        L.append(f"- {s}: {v['files']} fayl, {v['families']} provenance oilasi ({v['creator_families']} muallif/oila), "
                 f"kategoriyalar: " + ", ".join(f"{c} {n}" for c, n in v["per_category"].items()))
        L.append("  - oilalar soni kategoriya bo'yicha: " + ", ".join(f"{c} {n}" for c, n in v["families_per_category"].items()))
    L.append(f"- Kvotalar: pilot {cfg['corpus']['pilot_per_category']}/kategoriya, tasdiq {cfg['corpus']['confirmation_per_category']}/kategoriya; "
             f"dizayn: {design.get('design_label')}")
    if design.get("shortfall"):
        L.append(f"- Yetishmovchilik (haqiqiy son muzlatildi): {json.dumps(design['shortfall'], ensure_ascii=False)}")
    L.append(f"- Splitlar orasida umumiy oila: {design.get('cross_split_family_overlap')}")
    srcs = read_csv(ROOT / "data" / "sources.csv") if (ROOT / "data" / "sources.csv").exists() else []
    partial = [r for r in srcs if not r.get("status", "").startswith("ok")]
    if partial:
        L.append("- Manba cheklovlari: " + "; ".join(f"{r['source_id']}: {r['status'][:110]}" for r in partial))
    if any(r["source_id"].startswith("commons:") for r in partial):
        L.append("- Wikimedia Commons identifikatsiyasiz (aloqa ma'lumotisiz) klientlarni qattiq cheklaydi (429, Retry-After 600 s); "
                 "shuning uchun Commons fayllari kam va kvotalar to'liq bajarilmadi. Haqiqiy son va qisqartirilgan dizayn muzlatildi.")
    L.append("- Tarixiy kesishma: oldingi tadqiqot manifestlari mavjud emas; to'liq tekshirib bo'lmaydi. Tasdiq splitiga "
             f"yangiroq asarlar ({cfg['corpus']['confirmation_min_date']} dan keyin) va boshqa oilalar ustuvor berildi.")
    L.append("")
    L += ["## Baseline’lar va dekoderlar", "| Usul | Mavjud | Versiya | Fixture round-trip |", "|---|---|---|---|"]
    for n, m in (bl.get("methods") or {}).items():
        rt = (m.get("fixture_roundtrip") or {}).get("roundtrip_ok")
        L.append(f"| {n} | {'ha' if m['available'] else 'yo‘q: ' + m.get('reason', '')} | {m.get('version', '')[:60]} | {rt} |")
    lims = [(n, m["limitations"]) for n, m in (bl.get("methods") or {}).items() if m.get("limitations")]
    L += ["", "Qolgan baseline cheklovlari:"] + ([f"- {n}: {t}" for n, t in lims] or ["- yo'q"])
    L += ["- Dekoderlar: native `svgx decode` va mustaqil `reference/decode.py` har bir loyiha oqimini (yakuniy va majburiy "
          "strukturali) alohida jarayonlarda tekshiradi; tashqi oqimlar o'z dekoderlari bilan."]
    L += ["", "## Muhit", f"- OS: {env.get('os', {}).get('system')} {env.get('os', {}).get('release')} · Python {env.get('python')}",
          f"- CPU: {env.get('cpu', {}).get('model')} ({env.get('cpu', {}).get('logical')} mantiqiy yadro)",
          f"- RAM: {round((env.get('ram', {}).get('total_bytes') or 0) / 2**30, 1)} GiB · bo'sh disk: "
          f"{round((env.get('disk', {}).get('project_drive_free_bytes') or 0) / 2**30, 1)} GiB",
          f"- Toolchain: {env.get('toolchain', {}).get('rustc')} · {env.get('toolchain', {}).get('gcc')}", ""]
    est = st.get("estimate") or {}
    L += ["## Vaqt bahosi (ruxsatdan oldingi, faqat sintetik ish asosida)"]
    if est.get("reliable"):
        L.append(f"- Korpus: {est['files']} fayl, {est['corpus_bytes'] / 2**20:.1f} MiB")
        L.append(f"- O'lcham + tekshiruv: ~{est['size_and_verification_hours'] * 60:.0f} daqiqa ({est['workers']} worker); "
                 f"vaqt o'lchovi: ~{est['timing_hours'] * 60:.0f} daqiqa; jami ~{est['total_hours'] * 60:.0f} daqiqa "
                 f"(pilot taxminan 1/5 qismi)")
        L += [f"  - faraz: {a}" for a in est["assumptions"]]
    else:
        L.append(f"- Ishonchli baho yo'q: {est.get('reason')}")
    L += ["", "## Rejalashtirilgan doira",
          "- To'liq tadqiqot: pilot → sanali qaror yozuvi (C* = D/P dan kichigi) → mustaqil tasdiqlash (50 000 oilaviy bootstrap) → EN/UZ hisobotlar → ZIP paket.",
          "- Faqat pilot: pilot natijalari va hisobotlari; tasdiqlash uchun alohida qaror.",
          "", "## Buyruqlar (shu kompyuter uchun)", "```powershell",
          f"cd \"{ROOT}\"", ".\\run_experiment.cmd", ".\\run_experiment.cmd --scope pilot", ".\\run_experiment.cmd --scope full",
          ".\\run_experiment.cmd --resume --run-id RUN_ID", ".\\report.cmd --run-id RUN_ID", ".\\package.cmd --run-id RUN_ID", "```",
          "`RUN_ID` — boshqaruvchi chop etadigan haqiqiy identifikator.", "",
          "Haqiqiy SVG fayllarida siqish, profil va vaqt o'lchovi faqat foydalanuvchining aniq ruxsatidan keyin boshlanadi."]
    if st.get("blockers"):
        L += ["", "## To'siqlar"] + [f"- {b}" for b in st["blockers"]]
    return "\n".join(L) + "\n"


def run_prepare(skip_fetch: bool = False, skip_tests: bool = False) -> int:
    from . import pyenv, toolchain
    state = {"started_utc": utc_now(), "steps": {}, "blockers": []}
    say("1/7 Python muhiti va bog'liqliklar")
    pyenv.ensure()
    say("2/7 Toolchain va tashqi dasturlar")
    tools = toolchain.acquire_all({})
    state["steps"]["toolchain"] = tools
    for k in ("rust", "winlibs_gcc", "brotli_cli", "brotli_source"):
        if tools.get(k, {}).get("status") != "ok":
            state["blockers"].append(f"asosiy komponent yo'q: {k} — {tools[k].get('reason', '')[:200]}")
    if state["blockers"]:
        atomic_write_text(READINESS / "READY_UZ.md", ready_report(state))
        say("Tayyorgarlik to'xtadi: asosiy komponent yo'q (readiness/READY_UZ.md).")
        return 1
    say("3/7 Kodekni yig'ish va Rust testlari")
    state["steps"]["codec"] = build_codec()
    say("4/7 Sun'iy fixture'lar")
    if not (ROOT / "fixtures" / "synthetic" / "expected.json").exists():
        run([VENV_PY, ROOT / "tools" / "fixtures.py", "generate"], cwd=ROOT, env=tool_env())
    say("5/7 Ma'lumotlar: yuklash, xeshlash, dedup, split, vaqt namunasi")
    state["steps"]["data"] = data_stage(skip_fetch)
    say("6/7 Inventar, baseline’lar va self-test")
    from tools.inventory import environment, write_project_files
    atomic_write_json(READINESS / "environment.json", environment())
    baselines_inventory()
    if not skip_tests:
        from .selftest import run_selftest
        st = run_selftest(state["steps"]["codec"])
    else:
        st = read_json(READINESS / "selftest.json", {}) or {}
    say("7/7 Muzlatish va tayyorlik hisoboti")
    fz = freeze()
    write_project_files(READINESS / "project_files.tsv")
    state["estimate"] = estimate(st, state["steps"]["data"], study_config())
    state["complete"] = bool(st.get("ok")) and not state["blockers"]
    state["freeze_build_id"] = fz["build_id"]
    atomic_write_json(STATE / "prepare_state.json", state)
    atomic_write_text(READINESS / "READY_UZ.md", ready_report(state))
    say(f"Tayyorlik hisoboti: {READINESS / 'READY_UZ.md'}")
    return 0 if state["complete"] else 1
