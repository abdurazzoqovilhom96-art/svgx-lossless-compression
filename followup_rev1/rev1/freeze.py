"""REV1 freeze record (docs/PROTOCOL_REV1.md §Freeze).

Refuses to freeze unless every preparation gate passed:
  R0 on fixtures and on the pilot split, the T/Z/restricted-mode self-check, the B1 pilot dry run, the paq8px
  calibration (a level chosen), the zstd pilot dictionary, the confirmed P-core choice, the B3 sample, cargo test and
  pytest logs (state/prep_tests.json), and the unchanged frozen inputs of the original run.
Then hashes every REV1 file that defines the experiment and writes state/freeze_rev1.json. Any later change of a
hashed file makes the approval (bound to the SHA-256 of this record) invalid.
"""
from __future__ import annotations

import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
from common import (BROTLI_EXE, FREEZE, OUT, PAQ_EXE, PY, REF_DECODER, REV1, STATE, SVGX, ZSTD_EXE,  # noqa: E402
                    check_frozen_inputs, sha256_file, write_json)
import datetime as dt  # noqa: E402

HASHED_GLOBS = ["rev1/*.py", "tests_rev1/*.py", "config/rev1.toml", "config/paq_calibration.json", "config/zstd_pilot.dict",
                "config/zstd_pilot_dict.json", "config/cpu_topology.json", "config/b3_sample.csv",
                "config/license_sensitivity_exclude.csv", "docs/PROTOCOL_REV1.md", "codec/src/*.rs", "codec/Cargo.toml",
                "codec/Cargo.lock", "codec/build.rs", "data/manifests/pilot.csv", "data/manifests/confirmation.csv",
                "reference/decode.py", "runner/measure.py", "baselines/adapters.py", "config/baselines.toml",
                "run_rev1.cmd", "READY_REV1_UZ.md", "config/b4_power.json"]


def load(p):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def gates() -> dict:
    g = {}
    r0f, r0p = load(OUT / "r0" / "r0_fixtures.json"), load(OUT / "r0" / "r0_pilot.json")
    g["R0_fixtures"] = bool(r0f and r0f["passed"])
    g["R0_pilot"] = bool(r0p and r0p["passed"] and r0p["files"] == 248)
    sc = load(OUT / "prep" / "selfcheck_sections.json")
    g["sections_selfcheck"] = bool(sc and not sc["failures"] and sc["modelled"] > 0)
    b1 = load(OUT / "b1" / "b1_pilot_summary.json")
    g["B1_pilot_dry_run"] = bool(b1 and b1["complete"] and b1["defect_files"] == 0)
    b2 = load(OUT / "b2" / "b2_pilot_smoke_summary.json")
    g["B2_pilot_smoke"] = bool(b2 and b2["complete"] and b2["defect_files"] == 0)
    b3 = load(OUT / "b3" / "b3_pilot_smoke_meta.json")
    g["B3_pilot_smoke"] = bool(b3 and b3["complete"] and b3["defect_files"] == 0)
    cal = load(REV1 / "config" / "paq_calibration.json")
    g["paq_calibrated"] = bool(cal and cal["chosen_level"])
    g["zstd_dict"] = (REV1 / "config" / "zstd_pilot.dict").exists()
    topo = load(REV1 / "config" / "cpu_topology.json")
    g["p_core_confirmed"] = bool(topo and topo["confirmed"])
    g["b3_sample"] = (REV1 / "config" / "b3_sample.csv").exists()
    t = load(STATE / "prep_tests.json")
    g["cargo_test"] = bool(t and t["cargo_test"]["passed"])
    g["pytest"] = bool(t and t["pytest"]["passed"])
    g["frozen_inputs_unchanged"] = all(v["ok"] for v in check_frozen_inputs().values())
    return g


def main() -> int:
    force = "--force" in sys.argv
    if FREEZE.exists() and not force:
        print(f"[freeze] {FREEZE} already exists; use --force to replace it (this invalidates any approval).")
        return 1
    g = gates()
    if not all(g.values()):
        print("[freeze] gates not passed:", {k: v for k, v in g.items() if not v})
        return 1
    files = {}
    for pat in HASHED_GLOBS:
        hits = sorted(REV1.glob(pat))
        if not hits:
            print(f"[freeze] missing: {pat}")
            return 1
        for p in hits:
            files[p.relative_to(REV1).as_posix()] = sha256_file(p)
    tools = {"svgx_rev1": sha256_file(SVGX), "paq8px": sha256_file(PAQ_EXE),
             "paq8px_archive": sha256_file(PAQ_EXE.parent.parent / "paq8px_v217_windows_x64.7z"),
             "zstd": sha256_file(ZSTD_EXE), "brotli": sha256_file(BROTLI_EXE), "python": sha256_file(PY),
             "reference_decoder": sha256_file(REF_DECODER)}
    rec = {"design_id": "SVGX-REV1", "created_utc": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
           "gates": g, "frozen_inputs": check_frozen_inputs(), "files": files, "tools": tools,
           "paq_level": load(REV1 / "config" / "paq_calibration.json")["chosen_level"],
           "p_core": load(REV1 / "config" / "cpu_topology.json")["chosen_logical_processor"],
           "scope_available": ["R0", "B1", "B3", "B2", "analysis"]}
    write_json(FREEZE, rec)
    print(f"[freeze] written {FREEZE} ({len(files)} files, sha256 {sha256_file(FREEZE)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
