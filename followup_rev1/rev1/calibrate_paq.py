"""REV1 B2 calibration of the paq8px level on the PILOT split only (docs/PROTOCOL_REV1.md §B2).

Rule (fixed before calibration, config/rev1.toml): the highest level whose peak committed memory
(Job Object PeakJobMemoryUsed) is <= 8 GiB (2^33 bytes) on every calibration file, compression and decompression.
Levels are tried in ascending order 9, 10, 11, 12; the first level that exceeds the cap stops the search
(memory grows with the level). Level 8 (nominal 2433 MB) is the floor and is also measured.

Calibration set (deterministic, pilot only, every file <= 1 MiB so that each run completes):
  * five files without base64 data URIs at the size-rank quantiles 0.50, 0.75, 0.90, 0.95 and 0.98 of those files;
  * the three smallest pilot files containing a base64 data URI and the largest such file <= 1 MiB
    (embedded images switch paq8px to its image models, which use more memory).
Writes config/paq_calibration.json (frozen by freeze.py).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
from common import OUT, REV1, manifest, sha256_file, write_json, PAQ_EXE  # noqa: E402
import paq  # noqa: E402

CAP = 1 << 33
LEVELS = [8, 9, 10, 11, 12]
MAXSIZE = 1 << 20


def calibration_set() -> list[dict]:
    rows = [r for r in manifest("pilot") if int(r["size"]) <= MAXSIZE]
    for r in rows:
        r["_b64"] = b"base64," in Path(r["path"]).read_bytes()
    plain = sorted((r for r in rows if not r["_b64"]), key=lambda r: (int(r["size"]), r["sha256"]))
    b64 = sorted((r for r in rows if r["_b64"]), key=lambda r: (int(r["size"]), r["sha256"]))
    pick = []
    for q in (0.50, 0.75, 0.90, 0.95, 0.98):
        r = plain[min(len(plain) - 1, round(q * (len(plain) - 1)))]
        if r not in pick:
            pick.append(r)
    for r in b64[:3] + b64[-1:]:
        if r not in pick:
            pick.append(r)
    return pick


def main() -> int:
    cal = calibration_set()
    print("[paq-cal] calibration files:", [(r["file_id"], r["size"], r["_b64"]) for r in cal])
    results, chosen = {}, None
    for level in LEVELS:
        runs = []
        for r in cal:
            res = paq.roundtrip(Path(r["path"]).read_bytes(), level, OUT / "_work" / "paqcal" / f"L{level}")
            res["file_id"] = r["file_id"]
            res["base64"] = r["_b64"]
            runs.append(res)
            peak = max(res["compress"]["peak_memory_bytes"], res.get("decompress", {}).get("peak_memory_bytes", 0))
            print(f"   L{level} {r['file_id']} size {r['size']} ok {res['ok']} len {res.get('len')} "
                  f"peak {peak / 2**20:.0f} MiB  c {res['compress']['elapsed_s']:.1f}s")
            if not res["ok"] or peak > CAP:
                break
        peaks = [max(x["compress"]["peak_memory_bytes"], x.get("decompress", {}).get("peak_memory_bytes", 0)) for x in runs]
        fits = len(runs) == len(cal) and all(x["ok"] for x in runs) and max(peaks) <= CAP
        results[level] = {"fits": fits, "max_peak_bytes": max(peaks), "runs": runs}
        if fits:
            chosen = level
        elif level > LEVELS[0]:
            break
        else:
            print("[paq-cal] even the floor level failed; stop")
            break
    tot_in = sum(x["input_len"] for x in results[chosen]["runs"]) if chosen else 0
    tot_c = sum(x["compress"]["elapsed_s"] for x in results[chosen]["runs"]) if chosen else 0
    tot_d = sum(x["decompress"]["elapsed_s"] for x in results[chosen]["runs"]) if chosen else 0
    out = {"rule": "highest level with peak committed memory <= 2^33 bytes on every calibration file",
           "cap_bytes": CAP, "paq8px_sha256": sha256_file(PAQ_EXE), "calibration_files": [r["file_id"] for r in cal],
           "levels": {str(k): v for k, v in results.items()}, "chosen_level": chosen,
           "throughput_bytes_per_s": {"compress": tot_in / tot_c if tot_c else None,
                                      "decompress": tot_in / tot_d if tot_d else None}}
    write_json(REV1 / "config" / "paq_calibration.json", out)
    print(f"[paq-cal] chosen level: {chosen}; throughput {out['throughput_bytes_per_s']}")
    return 0 if chosen else 1


if __name__ == "__main__":
    sys.exit(main())
