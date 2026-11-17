"""REV1 B2: train the zstd dictionary on the PILOT split only (docs/PROTOCOL_REV1.md §B2).

zstd 1.5.7 `--train` with its defaults (fastcover, --maxdict=112640) over all 248 pilot files (copied to a private
directory, recursive mode). The dictionary is written to config/zstd_pilot.dict and frozen by freeze.py; it is never
retrained after the confirmation split has been touched.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
from common import OUT, REV1, ZSTD_EXE, manifest, run, sha256_file, write_json  # noqa: E402


def main() -> int:
    rows = manifest("pilot")
    tdir = OUT / "_work" / "zstd_train"
    shutil.rmtree(tdir, ignore_errors=True)
    tdir.mkdir(parents=True)
    for r in rows:
        shutil.copyfile(r["path"], tdir / f"{r['sha256']}.svg")
    dst = REV1 / "config" / "zstd_pilot.dict"
    r = run([ZSTD_EXE, "--train", "-r", tdir, "-o", dst, "-f"])
    shutil.rmtree(tdir, ignore_errors=True)
    if r.returncode != 0:
        print(r.stderr.decode("utf-8", "replace")[-800:])
        return 1
    info = {"tool": str(ZSTD_EXE), "tool_sha256": sha256_file(ZSTD_EXE), "command": "zstd --train -r <248 pilot files> -o zstd_pilot.dict",
            "training_files": len(rows), "training_bytes": sum(int(x["size"]) for x in rows),
            "dict_len": dst.stat().st_size, "dict_sha256": sha256_file(dst),
            "stderr_tail": r.stderr.decode("utf-8", "replace")[-400:]}
    write_json(REV1 / "config" / "zstd_pilot_dict.json", info)
    print(f"[zstd-dict] {info['dict_len']} bytes, sha256 {info['dict_sha256'][:16]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
