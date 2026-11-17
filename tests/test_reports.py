"""SYNTHETIC end-to-end run in a temporary directory with the REAL worker: scheduling, transient
retry, failure + resume, measurement, paired statistics, bootstrap, figures, EN/UZ reports and ZIP
verification. Nothing here touches the live state/ or results/ trees."""
from __future__ import annotations

import csv
import json
import shutil
import zipfile
from pathlib import Path

from runner.approval import record_decision
from runner.common import ROOT, canonical_json, sha256_file
from runner.controller import EXIT_OK, run_study
from runner.jobs import Ledger, TransientError
from runner.tasks import RealWorker

SVG = ROOT / "fixtures" / "synthetic" / "svg"
PILOT = [("gen_inkscape_like", "illustrations", "fam-a"), ("gen_int_abs", "maps", "fam-b"), ("basic_abs", "icons", "fam-c")]
CONF = [("gen_fixed2_abs", "maps", "fam-d"), ("gen_fixed3_rel", "diagrams", "fam-e"), ("dots", "icons", "fam-f"),
        ("gen_exp_style", "illustrations", "fam-e")]


def build_root(tmp: Path) -> tuple[Path, Path, dict]:
    root = tmp / "root"
    (root / "data" / "manifests").mkdir(parents=True)
    (root / "data" / "originals").mkdir(parents=True)
    cols = ["file_id", "sha256", "size", "category", "family", "creator_family", "original"]
    for split, items in (("pilot", PILOT), ("confirmation", CONF)):
        rows = []
        for n, cat, fam in items:
            src = SVG / f"{n}.svg"
            h = sha256_file(src)
            shutil.copyfile(src, root / "data" / "originals" / f"{h}.svg")
            rows.append({"file_id": f"SYN-{split[0]}-{n}", "sha256": h, "size": src.stat().st_size, "category": cat,
                         "family": fam, "creator_family": fam, "original": f"data/originals/{h}.svg"})
        for name, rs in ((f"{split}.csv", rows), (f"timing_{split}.csv", rows[:1])):
            with open(root / "data" / "manifests" / name, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=cols)
                w.writeheader()
                w.writerows(rs)
    bound = [f"data/manifests/{x}.csv" for x in ("pilot", "confirmation", "timing_pilot", "timing_confirmation")]
    fz = {"design_id": "SVGX-2026-11-A", "build_id": "build-synthetic-e2e", "format": "svgx-1",
          "manifests": {"pilot": bound[0], "confirmation": bound[1]},
          "timing_samples": {"pilot": bound[2], "confirmation": bound[3]}, "corpus_files": [],
          "bound_files": {b: sha256_file(root / b) for b in bound}}
    state = tmp / "state"
    state.mkdir()
    (state / "freeze.json").write_text(canonical_json(fz), encoding="utf-8")
    return root, state, fz


class Flaky:
    """Real worker; first attempt of every xz size job fails transiently; gzip9 size jobs fail hard once."""
    broken = True

    def __init__(self, run, inputs):
        self.w = RealWorker(run, inputs)
        self.seen = set()

    def __call__(self, job):
        if job.task == "size" and job.method == "xz9e" and job.key not in self.seen:
            self.seen.add(job.key)
            raise TransientError("synthetic transient failure")
        if job.task == "size" and job.method == "gzip9" and Flaky.broken:
            raise RuntimeError("synthetic hard failure before interruption")
        return self.w(job)


def test_synthetic_end_to_end(tmp_path):
    root, state, fz = build_root(tmp_path)
    results = tmp_path / "results"
    record_decision(state, decision="approve", scope="full", source="chat", reply_text="ha (synthetic test)",
                    freeze=fz, test_mode=True)
    kw = dict(state_dir=state, results_root=results, root=root, interactive=False, synthetic=True)
    Flaky.broken = True
    assert run_study(run_id="SYN_E2E", worker_factory=Flaky, package=False, **kw) == EXIT_OK
    run = results / "SYN_E2E"
    led = Ledger(run / "ledger.sqlite")
    failed = led.rows("status='failed'")
    att = led.attempts()
    led.close()
    assert failed and all(r["method"] == "gzip9" for r in failed)
    assert any(a["status"] == "transient" for a in att)
    # resume after the "interruption": failed jobs are re-attempted, done jobs are not relaunched
    Flaky.broken = False
    assert run_study(run_id="SYN_E2E", resume=True, worker_factory=Flaky, package=True, **kw) == EXIT_OK
    led = Ledger(run / "ledger.sqlite")
    statuses = {r["status"] for r in led.rows()}
    led.close()
    assert statuses == {"done"}
    # published paths and row counts
    for split, items in (("pilot", PILOT), ("confirmation", CONF)):
        with open(run / "03_raw" / f"{split}_per_file.csv", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == len(items)
        assert all(r["verified"] == "True" for r in rows)
        assert all(r["E_xz9e"] and r["E_gzip9"] for r in rows)
        with open(run / "10_tables" / f"{split}_main_comparisons.csv", encoding="utf-8") as f:
            assert len(list(csv.DictReader(f))) >= 6
        for fig in ("gain_by_comparator", "file_gain_hist", "family_outcomes", "ceiling_vs_actual", "size_vs_gain"):
            assert (run / "09_figures" / f"{split}_{fig}.svg").stat().st_size > 1000
            assert (run / "09_figures" / f"{split}_{fig}.pdf").stat().st_size > 1000
        assert (run / "08_plot_data" / f"{split}_file_gain_vs_brotli.csv").exists()
    st = json.loads((run / "07_statistics" / "confirmation_statistics.json").read_text(encoding="utf-8"))
    assert st["bootstrap"]["m"] == 3 and st["bootstrap"]["resamples"] == 50000
    iv = st["bootstrap"]["intervals"]["G_vs_brotli11"]
    assert iv["bonferroni"][0] <= iv["marginal"][0] <= iv["marginal"][1] <= iv["bonferroni"][1]
    assert "claims" in st
    pd = json.loads((run / "07_statistics" / "pilot_decision.json").read_text(encoding="utf-8"))
    assert pd["cstar"]["selected"] in ("D", "P") and len(pd["pilot_summary_sha256"]) == 64
    en = (run / "11_reports" / "RESULTS_EN.md").read_text(encoding="utf-8")
    uz = (run / "11_reports" / "RESULTS_UZ.md").read_text(encoding="utf-8")
    assert "SYNTHETIC" in en and "SINTETIK" in uz
    timing = json.loads((run / "06_performance" / "timing_summary.json").read_text(encoding="utf-8"))
    assert timing["svgx_G"]["min_repeats"] == 7 and timing["brotli11"]["encode_MiB_per_s"] > 0
    assert json.loads((run / "09_figures" / "STATUS.json").read_text(encoding="utf-8"))["synthetic"] is True
    # ZIP outside the archived tree, clean-extraction verified
    z = results / "SYN_E2E__package.zip"
    assert z.exists()
    ver = json.loads((results / "SYN_E2E__package.verify.json").read_text(encoding="utf-8"))
    assert ver["ok"] and ver["checked"] > 20
    with zipfile.ZipFile(z) as zz:
        names = zz.namelist()
    assert "MANIFEST.sha256" in names and not any(n.endswith("__package.zip") for n in names)
    # offline regeneration reproduces the statistics byte for byte
    from reporting.build import build
    before = (run / "07_statistics" / "confirmation_statistics.json").read_bytes()
    build(run)
    assert (run / "07_statistics" / "confirmation_statistics.json").read_bytes() == before
