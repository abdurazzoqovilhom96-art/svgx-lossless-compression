"""Identical output digests at different worker counts; tested results-tree initializer."""
from __future__ import annotations

import hashlib
import subprocess
from concurrent.futures import ThreadPoolExecutor

from conftest import fixture_files
from runner.common import CODEC_BIN
from runner.results import SUBDIRS, init_run_tree


def _digest(args):
    src, out = args
    subprocess.run([str(CODEC_BIN), "encode", "--profile", "G", "--force-structured", str(src), str(out)], check=True)
    return src.name, hashlib.sha256(out.read_bytes()).hexdigest()


def test_digests_independent_of_worker_count(tmp_path):
    files = [f for f in fixture_files() if f.stat().st_size > 0][:20]
    res = {}
    for workers in (1, 8):
        jobs = [(f, tmp_path / f"{workers}_{f.stem}.svgx") for f in files]
        with ThreadPoolExecutor(max_workers=workers) as ex:
            res[workers] = dict(ex.map(_digest, jobs))
    assert res[1] == res[8]


def test_results_tree_initializer(tmp_path):
    run = init_run_tree(tmp_path, "SYNTHETIC_RUN", scope="pilot", synthetic=True)
    for name in SUBDIRS:
        assert (run / name / "STATUS.json").exists()
    import json
    st = json.loads((run / "07_statistics" / "STATUS.json").read_text(encoding="utf-8"))
    assert st["synthetic"] is True and st["status"] == "pending"
