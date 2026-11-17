"""Initializer for one results/<run_id>/ tree (tested on a synthetic tree during preparation)."""
from __future__ import annotations

from pathlib import Path

from .common import atomic_write_json, utc_now

SUBDIRS = {
    "01_protocol": "Frozen settings, method/build IDs, versions, machine inventory, scope and approval record.",
    "02_corpus": "Input hashes, sources, licenses, splits, family mapping and duplicate decisions.",
    "03_raw": "Per-file paired size and component measurements, per-method states and stream paths.",
    "04_verification": "Byte-compare results, decoded hashes and independent-decoder coverage.",
    "05_ablations": "D/P/I/U/G component comparisons, rule collisions, escapes, mode choices and headroom.",
    "06_performance": "Per-repeat times, peak memory, workload, concurrency and timed-sample denominators.",
    "07_statistics": "Paired gains, intervals, family wins/ties/losses, sensitivity, targets, pilot control selection.",
    "08_plot_data": "Source CSVs for every plot.",
    "09_figures": "Publication-ready SVG/PDF figures.",
    "10_tables": "Reproducible CSV and publication tables.",
    "11_reports": "RESULTS_UZ.md, RESULTS_EN.md, failure/retry ledger and completeness audit.",
    "12_reproducibility": "Commands, checksums and archive manifest.",
}


def init_run_tree(results_root: Path, run_id: str, *, scope: str, synthetic: bool) -> Path:
    """Create every subdirectory with a machine-readable status until deliverables replace it."""
    run = Path(results_root) / run_id
    for name, purpose in SUBDIRS.items():
        d = run / name
        d.mkdir(parents=True, exist_ok=True)
        st = d / "STATUS.json"
        if not st.exists():
            atomic_write_json(st, {"status": "pending", "purpose": purpose, "scope": scope,
                                   "synthetic": synthetic, "coverage": None, "reason": "stage not yet run",
                                   "updated_utc": utc_now()})
    return run


def set_status(run: Path, sub: str, status: str, reason: str, coverage=None, scope: str | None = None,
               synthetic: bool | None = None) -> None:
    p = Path(run) / sub / "STATUS.json"
    from .common import read_json
    cur = read_json(p, {}) or {}
    cur.update({"status": status, "reason": reason, "coverage": coverage, "updated_utc": utc_now()})
    if scope is not None:
        cur["scope"] = scope
    if synthetic is not None:
        cur["synthetic"] = synthetic
    atomic_write_json(p, cur)
