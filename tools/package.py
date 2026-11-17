"""Create and verify the portable, checksum-verified archive of one run.

    python tools/package.py --run-dir results/<run_id>        # create + verify
    python tools/package.py --verify results/<run_id>__package.zip

The ZIP is written next to (outside) the archived run tree to prevent self-inclusion. Entries use a
fixed timestamp and sorted order; MANIFEST.sha256 inside lists every member. Distributable
originals are not copied: data/manifests/*.csv carry URL, revision and SHA-256 for re-fetching under
each source's own terms.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from runner.common import atomic_write_json, sha256_file, utc_now  # noqa: E402

SOURCE_GLOBS = ["study.py", "*.cmd", "README_UZ.md", "requirements.in", "requirements.lock",
                "codec/Cargo.toml", "codec/Cargo.lock", "codec/build.rs", "codec/rust-toolchain.toml", "codec/src/*.rs",
                "reference/*.py", "config/*.toml", "docs/*.md", "datasets/*.py", "baselines/*.py", "runner/*.py",
                "reporting/*.py", "tools/*.py", "tests/*.py", "fixtures/synthetic/expected.json",
                "fixtures/synthetic/svg/*.svg", "data/sources.csv", "data/candidates.csv", "data/manifests/*",
                "readiness/*", "state/freeze.json"]
RUN_EXCLUDE = ("03_raw/streams/", "04_verification/work/", "06_performance/work/", "run.lock", "ledger.sqlite-wal",
               "ledger.sqlite-shm")
FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def collect(run: Path, root: Path) -> list[tuple[str, Path]]:
    items = []
    for g in SOURCE_GLOBS:
        for p in sorted(root.glob(g)):
            if p.is_file():
                items.append(("source/" + p.relative_to(root).as_posix(), p))
    for p in sorted(run.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(run).as_posix()
        if any(rel.startswith(x) or rel == x for x in RUN_EXCLUDE):
            continue
        items.append((f"results/{run.name}/{rel}", p))
    return items


def make_package(run: Path, root: Path = ROOT) -> dict:
    run = Path(run)
    zpath = run.parent / f"{run.name}__package.zip"
    items = collect(run, root)
    manifest_lines = []
    for arc, p in items:
        manifest_lines.append(f"{sha256_file(p)}  {p.stat().st_size}  {arc}")
    manifest = "\n".join(manifest_lines) + "\n"
    tmp = zpath.with_suffix(".zip.part")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for arc, p in items:
            zi = zipfile.ZipInfo(arc, FIXED_TIME)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, p.read_bytes())
        zi = zipfile.ZipInfo("MANIFEST.sha256", FIXED_TIME)
        zi.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(zi, manifest)
        zi = zipfile.ZipInfo("README_ARCHIVE.txt", FIXED_TIME)
        z.writestr(zi, ("Excluded (reproducible from the frozen build and manifests): " + ", ".join(RUN_EXCLUDE)
                        + "\nOriginals: re-fetch from data/manifests/*.csv (url, revision, sha256) under each source's terms.\n"))
    tmp.replace(zpath)
    rep = verify_package(zpath)
    rep.update({"zip": str(zpath), "zip_sha256": sha256_file(zpath), "members": len(items), "created_utc": utc_now()})
    atomic_write_json(zpath.with_suffix(".verify.json"), rep)
    atomic_write_json(run / "12_reproducibility" / "package_verification.json", rep)
    (run / "12_reproducibility" / "archive_manifest.sha256").write_text(manifest, encoding="utf-8")
    return rep


def verify_package(zpath: Path) -> dict:
    """Clean extraction into a temporary directory and SHA-256 check of every member."""
    bad, n = [], 0
    with tempfile.TemporaryDirectory(prefix="svgx_pkg_") as td:
        with zipfile.ZipFile(zpath) as z:
            if z.testzip() is not None:
                return {"ok": False, "error": "corrupt member"}
            z.extractall(td)
        lines = (Path(td) / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines()
        for line in lines:
            if not line.strip():
                continue
            h, size, arc = line.split("  ", 2)
            p = Path(td) / arc
            n += 1
            if not p.exists() or p.stat().st_size != int(size) or hashlib.sha256(p.read_bytes()).hexdigest() != h:
                bad.append(arc)
    return {"ok": not bad, "checked": n, "mismatches": bad[:50]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir")
    ap.add_argument("--verify")
    a = ap.parse_args()
    if a.verify:
        r = verify_package(Path(a.verify))
    else:
        r = make_package(Path(a.run_dir))
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
