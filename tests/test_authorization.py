"""Authorization gate with a mocked worker that records every attempted launch, in isolated state.

No test writes into the live state/ or results/ directories; test approvals are flagged test_mode.
"""
from __future__ import annotations

import csv
import shutil
from pathlib import Path

import pytest

from runner import approval
from runner.approval import GateError, parse_reply, record_decision
from runner.common import ROOT, STATE, canonical_json, sha256_file
from runner.controller import EXIT_OK, EXIT_PAUSED, EXIT_PENDING, EXIT_REFUSED, run_study
from runner.jobs import DefectError

SVG = ROOT / "fixtures" / "synthetic" / "svg"
FILES = ["gen_inkscape_like", "gen_fixed2_abs", "gen_int_abs", "basic_abs", "gen_fixed3_rel", "dots"]
PROFILES = "DPIUG"


def make_root(tmp: Path) -> Path:
    """Isolated project-like root with synthetic manifests and a freeze bound to them."""
    root = tmp / "root"
    (root / "data" / "manifests").mkdir(parents=True)
    (root / "data" / "originals").mkdir(parents=True)
    cols = ["file_id", "sha256", "size", "category", "family", "creator_family", "original"]
    for split, names in (("pilot", FILES[:3]), ("confirmation", FILES[3:])):
        rows = []
        for i, n in enumerate(names):
            src = SVG / f"{n}.svg"
            h = sha256_file(src)
            shutil.copyfile(src, root / "data" / "originals" / f"{h}.svg")
            rows.append({"file_id": f"{split}-{n}", "sha256": h, "size": src.stat().st_size,
                         "category": ["maps", "icons", "diagrams"][i % 3], "family": f"fam-{split}-{i % 2}",
                         "creator_family": f"cf-{i}", "original": f"data/originals/{h}.svg"})
        for name, rs in ((f"{split}.csv", rows), (f"timing_{split}.csv", rows[:1])):
            with open(root / "data" / "manifests" / name, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
                w.writeheader()
                w.writerows(rs)
    return root


def make_freeze(root: Path, state: Path) -> dict:
    bound = ["data/manifests/pilot.csv", "data/manifests/confirmation.csv", "data/manifests/timing_pilot.csv",
             "data/manifests/timing_confirmation.csv"]
    fz = {"design_id": "SVGX-2026-11-A", "build_id": "build-synthetic", "format": "svgx-1",
          "manifests": {"pilot": "data/manifests/pilot.csv", "confirmation": "data/manifests/confirmation.csv"},
          "timing_samples": {"pilot": "data/manifests/timing_pilot.csv", "confirmation": "data/manifests/timing_confirmation.csv"},
          "corpus_files": [], "bound_files": {b: sha256_file(root / b) for b in bound}}
    state.mkdir(parents=True, exist_ok=True)
    (state / "freeze.json").write_text(canonical_json(fz), encoding="utf-8")
    return fz


class MockWorker:
    """Records launches; returns schema-complete fake results (G loses vs Brotli: pilot misses targets)."""

    def __init__(self, defect_on: str | None = None):
        self.launches = []
        self.defect_on = defect_on

    def factory(self, run, inputs):
        return self

    def __call__(self, job):
        self.launches.append((job.split, job.method, job.task, job.repeat))
        if self.defect_on and job.method == "svgx" and job.split == self.defect_on:
            raise DefectError("synthetic reproducible round-trip mismatch")
        if job.task == "timing":
            t = {"elapsed_s": 0.01, "peak_memory_bytes": 1000, "user_s": 0.0, "kernel_s": 0.0}
            return {"available": True, "warmup": job.repeat == 0, "stream_len": 10, "compress": t, "decompress": t}
        if job.method != "svgx":
            return {"available": True, "len": 900, "roundtrip_ok": True}
        B = 1000
        prof = {}
        for i, p in enumerate(PROFILES):
            C = B  # ties with raw Brotli: misses the size and breadth targets
            prof[p] = {"C": C, "invariants": {"O": 990, "forced_len": 1100 + i, "branch": "raw", "ok": True},
                       "verify_final": {"native_ok": True, "reference_ok": True}, "verify_forced": None}
        return {"stats": {"eligible": True, "file_reason": None, "blocks": 1, "profiles": {p: {"escape_count": 0} for p in PROFILES},
                          "roles": [], "common": {"mode_counts": [1, 0, 0, 0]}},
                "B": B, "codec_raw_equals_baseline": True, "profiles": prof}


def setup(tmp_path):
    root = make_root(tmp_path)
    state = tmp_path / "state"
    fz = make_freeze(root, state)
    return root, state, fz, tmp_path / "results"


def go(root, state, results, worker, **kw):
    return run_study(state_dir=state, results_root=results, root=root, worker_factory=worker.factory,
                     interactive=False, synthetic=True, package=False, **kw)


def test_missing_approval_zero_launches(tmp_path):
    root, state, fz, results = setup(tmp_path)
    w = MockWorker()
    for scope in (None, "pilot", "full"):
        assert go(root, state, results, w, scope_flag=scope) == EXIT_PENDING
    assert w.launches == []


def test_refusal_and_empty_reply_zero_launches(tmp_path):
    root, state, fz, results = setup(tmp_path)
    w = MockWorker()
    assert parse_reply("") == (None, None) and parse_reply("   ") == (None, None)
    rc = run_study(state_dir=state, results_root=results, root=root, worker_factory=w.factory, interactive=True,
                   input_fn=lambda _: "", synthetic=True, package=False)
    assert rc == EXIT_PENDING and not (state / "approval.json").exists()
    record_decision(state, decision="decline", scope=None, source="terminal", reply_text="yo'q", freeze=fz, test_mode=True)
    assert go(root, state, results, w) == EXIT_REFUSED
    assert w.launches == []


def test_hash_mismatch_zero_launches(tmp_path):
    root, state, fz, results = setup(tmp_path)
    record_decision(state, decision="approve", scope="full", source="chat", reply_text="ha", freeze=fz, test_mode=True)
    with open(root / "data" / "manifests" / "pilot.csv", "a", encoding="utf-8") as f:
        f.write("\n")
    w = MockWorker()
    assert go(root, state, results, w) == EXIT_REFUSED
    assert w.launches == []


def test_pilot_only_dispatches_only_pilot(tmp_path):
    root, state, fz, results = setup(tmp_path)
    record_decision(state, decision="approve", scope="pilot", source="chat", reply_text="faqat pilot", freeze=fz, test_mode=True)
    w = MockWorker()
    assert go(root, state, results, w, scope_flag="full") == EXIT_REFUSED
    assert w.launches == []
    assert go(root, state, results, w) == EXIT_OK
    assert w.launches and all(s == "pilot" for s, *_ in w.launches)


def test_full_approval_dispatches_confirmation_after_missed_pilot(tmp_path):
    root, state, fz, results = setup(tmp_path)
    record_decision(state, decision="approve", scope="full", source="chat", reply_text="Ha, to'liq", freeze=fz, test_mode=True)
    w = MockWorker()
    assert go(root, state, results, w, run_id="RUN_FULL") == EXIT_OK
    splits = {s for s, *_ in w.launches}
    assert splits == {"pilot", "confirmation"}
    import json
    pd = json.loads((results / "RUN_FULL" / "07_statistics" / "pilot_decision.json").read_text(encoding="utf-8"))
    assert pd["pilot_targets"]["size_target_met"] is False and pd["cstar"]["selected"] == "P"  # tie -> P
    # resume: every job already done -> zero new launches
    n = len(w.launches)
    assert go(root, state, results, w, resume=True, run_id="RUN_FULL") == EXIT_OK
    assert len(w.launches) == n


def test_default_and_explicit_pilot_commands(tmp_path):
    root, state, fz, results = setup(tmp_path)
    record_decision(state, decision="approve", scope="full", source="chat", reply_text="ha", freeze=fz, test_mode=True)
    w = MockWorker()
    assert go(root, state, results, w, scope_flag="pilot", run_id="RUN_P") == EXIT_OK
    assert {s for s, *_ in w.launches} == {"pilot"}


def test_primary_defect_pauses(tmp_path):
    root, state, fz, results = setup(tmp_path)
    record_decision(state, decision="approve", scope="full", source="chat", reply_text="ha", freeze=fz, test_mode=True)
    w = MockWorker(defect_on="pilot")
    assert go(root, state, results, w, run_id="RUN_D") == EXIT_PAUSED
    assert not any(s == "confirmation" for s, *_ in w.launches)
    from runner.jobs import Ledger
    led = Ledger(results / "RUN_D" / "ledger.sqlite")
    assert led.paused_scopes()
    led.close()
    n = len(w.launches)
    assert go(root, state, results, w, resume=True, run_id="RUN_D") == EXIT_PAUSED
    assert not any(m == "svgx" for _, m, *_ in w.launches[n:])  # paused comparisons are not relaunched


def test_test_approval_never_enters_live_state():
    fz = {"design_id": "X", "bound_files": {}}
    with pytest.raises(GateError):
        record_decision(STATE, decision="approve", scope="full", source="chat", reply_text="ha", freeze=fz, test_mode=True)


@pytest.mark.parametrize("text,expected", [
    ("Ha", ("approve", "full")), ("ha, ruxsat beraman", ("approve", "full")), ("Ha, faqat pilot", ("approve", "pilot")),
    ("faqat pilot", ("approve", "pilot")), ("to'liq tadqiqotni boshlang", ("approve", "full")), ("Yo'q", ("decline", None)),
    ("ruxsat bermayman", ("decline", None)), ("bilmayman", (None, None)), ("", (None, None)),
])
def test_parse_reply(text, expected):
    assert parse_reply(text) == expected


def test_live_state_has_no_test_approval():
    rec = approval.load_decision(STATE)
    assert rec is None or not rec.get("test_mode")
