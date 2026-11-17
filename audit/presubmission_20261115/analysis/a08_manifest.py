"""A14: ARTIFACT_MANIFEST.json linking inputs, frozen code, parameters, audit code and outputs by SHA-256. No codec jobs."""
from __future__ import annotations

import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

A = Path(__file__).resolve().parent.parent
ROOT = A.parents[1]
RUN = ROOT / "results" / "20261114_050438_SVGX-2026-11-A"


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def entry(p: Path, base: Path) -> dict:
    return {"path": str(p.relative_to(base)).replace("\\", "/"), "bytes": p.stat().st_size, "sha256": sha(p)}


frozen_inputs = [RUN / "ledger.sqlite", RUN / "11_reports" / "RESULTS_UZ.md", RUN / "11_reports" / "RESULTS_EN.md",
                 RUN / "11_reports" / "completeness_audit.json", RUN / "01_protocol" / "freeze.json",
                 RUN / "01_protocol" / "approval.json", RUN / "07_statistics" / "pilot_decision.json",
                 RUN / "02_corpus" / "pilot.csv", RUN / "02_corpus" / "confirmation.csv",
                 RUN / "10_tables" / "pilot_main_comparisons.csv", RUN / "10_tables" / "confirmation_main_comparisons.csv",
                 RUN.parent / (RUN.name + "__package.zip")]
frozen_code = ["codec/target/release/svgx.exe", "reference/decode.py", "reporting/build.py", "reporting/stats.py",
               "runner/controller.py", "config/study.toml", "config/baselines.toml", "docs/FORMAT.md", "docs/PROOF.md",
               "docs/PROTOCOL.md", ".tools/bin/xwrt.exe"]
fz = json.loads((RUN / "01_protocol" / "freeze.json").read_text(encoding="utf-8"))
man = {
    "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "run_id": RUN.name, "design_id": fz["design_id"], "build_id": fz["build_id"], "frozen_utc": fz["frozen_utc"],
    "primary_settings": fz["primary_settings"],
    "environment": {"python": sys.version.split()[0], "platform": platform.platform(), "numpy": __import__("numpy").__version__},
    "policy": {"original_results_modified": False, "full_campaign_rerun": False, "new_codec_jobs": 39,
               "distinct_new_inputs": 39, "codec_wall_time_s": 12.3},
    "frozen_inputs": [entry(p, ROOT) for p in frozen_inputs],
    "frozen_code_and_parameters": [dict(entry(ROOT / r, ROOT), bound_in_freeze=(r in fz["bound_files"]),
                                        equals_freeze=(fz["bound_files"].get(r) == sha(ROOT / r)) if r in fz["bound_files"] else None)
                                   for r in frozen_code],
    "audit_code": [entry(p, A) for p in sorted((A / "analysis").glob("*.py"))],
    "audit_outputs": [entry(p, A) for p in sorted((A / "derived").glob("*")) if p.is_file()]
                     + [entry(A / n, A) for n in ("TARGETED_JOB_PLAN.json", "TARGETED_JOBS.jsonl") if (A / n).exists()],
    "documents": [entry(A / n, A) for n in ("METHOD_SPEC.md", "RESULTS_AUDITED.md", "RELATED_WORK_VERIFIED.md",
                                             "ISSUE_LEDGER.tsv", "CLAIM_EVIDENCE_MAP.tsv", "PRE_WRITING_DECISION.md",
                                             "AUDIT_SUMMARY_UZ.md") if (A / n).exists()],
    "regenerate": ["python -I analysis/a02_recompute.py <SVG_EXPERIMENT>/results/20261114_050438_SVGX-2026-11-A",
                   "python -I analysis/a03_concentration_bootstrap.py",
                   "python -I analysis/a04_provenance_timing.py <SVG_EXPERIMENT>",
                   "python -I analysis/a06_stream_hashes.py",
                   "python -I analysis/a07_completeness.py",
                   "python -I -m pytest -q -p no:cacheprovider analysis/test_audit_regression.py",
                   "python -I analysis/a05_targeted_redecode.py run   (codec jobs; only within the recorded plan)"],
}
(A / "ARTIFACT_MANIFEST.json").write_text(json.dumps(man, indent=1), encoding="utf-8")
print(json.dumps({"inputs": len(man["frozen_inputs"]), "code": len(man["frozen_code_and_parameters"]),
                  "all_bound_equal": all(x["equals_freeze"] in (True, None) for x in man["frozen_code_and_parameters"]),
                  "audit_code": len(man["audit_code"]), "outputs": len(man["audit_outputs"])}, indent=1))
