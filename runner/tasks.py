"""Real job workers: size (with verification) and timing tasks."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from baselines.adapters import Method, methods as all_methods, run_plan_untimed
from .common import CODEC_BIN, atomic_write_json, sha256_bytes
from .jobs import DefectError, JobSpec, TransientError
from .measure import run_measured, run_plan
from . import verify

PROFILES = ["D", "P", "I", "U", "G"]


class RealWorker:
    """Executes size/timing jobs for a run directory. `inputs` maps input sha256 -> absolute path."""

    def __init__(self, run_dir: Path, inputs: dict[str, str], timeout: float = 1800.0):
        self.run_dir = Path(run_dir)
        self.inputs = inputs
        self.methods = all_methods()
        self.timeout = timeout

    def __call__(self, job: JobSpec) -> dict:
        src = self.inputs.get(job.input_sha256)
        if not src or not Path(src).exists():
            raise RuntimeError(f"kirish fayli topilmadi: {job.input_sha256}")
        if job.task == "size" and job.method == "svgx":
            return self.size_project(job, Path(src))
        if job.task == "size":
            return self.size_external(job, Path(src))
        if job.task == "timing":
            return self.timing(job, Path(src))
        raise RuntimeError(f"noma'lum topshiriq: {job.task}")

    def _dir(self, job: JobSpec, kind: str) -> Path:
        d = self.run_dir / kind / job.split / job.input_sha256[:16] / job.method
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ------------------------------------------------------------------ size: project codec
    def size_project(self, job: JobSpec, src: Path) -> dict:
        original = src.read_bytes()
        out = self._dir(job, "03_raw/streams")
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        r = run_measured([str(CODEC_BIN), "encode-all", str(src), str(out)], str(out), timeout=self.timeout)
        if r["timed_out"]:
            raise TransientError("svgx encode-all timeout")
        if r["returncode"] != 0:
            raise RuntimeError("svgx encode-all xato: " + r["stderr_tail"])
        stats = json.loads((out / "stats.json").read_text(encoding="utf-8"))
        # independent same-settings baseline stream (primary Brotli tool)
        bm = self.methods["brotli11"]
        bwork = out / "_baseline"
        plan = bm.compress_plan(str(src), str(out / "baseline.br"), str(bwork))
        run_plan_untimed(plan)
        baseline = Path(plan.produced).read_bytes()
        shutil.rmtree(bwork, ignore_errors=True)
        raw = (out / "raw.br").read_bytes()
        vwork = self._dir(job, "04_verification/work")
        result = {"stats": stats, "B": len(baseline), "baseline_sha256": sha256_bytes(baseline),
                  "codec_raw_equals_baseline": raw == baseline, "encode_all": {k: r[k] for k in ("elapsed_s", "peak_memory_bytes")},
                  "profiles": {}, "common_sections_equal": True, "escape_equal_IUG": True}
        defects = []
        if raw != baseline:
            defects.append("codec raw Brotli stream differs from the independent brotli.exe baseline")
        common_ref, esc_ref = None, None
        for p in PROFILES:
            final = (out / f"{p}.svgx").read_bytes()
            fpath = out / f"{p}.forced.svgx"
            forced = fpath.read_bytes() if fpath.exists() else None
            inv = verify.invariants(final, baseline, forced)
            vf = verify.verify_project_stream(out / f"{p}.svgx", original, vwork)
            if forced is None:
                vz = None
            elif forced == final:  # identical bytes: the same verified stream
                vz = dict(vf, stream=fpath.name)
            else:
                vz = verify.verify_project_stream(fpath, original, vwork)
            secs = verify.sections(forced) if forced is not None else {"structured": False}
            if secs.get("structured"):
                common = tuple(secs["sections"][n]["sha256"] for n in ("literals", "schedule", "geometry"))
                if common_ref is None:
                    common_ref = common
                elif common != common_ref:
                    result["common_sections_equal"] = False
                    defects.append("common sections differ across profiles")
                if p in ("I", "U", "G"):
                    e = secs["sections"]["escapes"]["sha256"]
                    if esc_ref is None:
                        esc_ref = e
                    elif e != esc_ref:
                        result["escape_equal_IUG"] = False
                        defects.append("escape section differs across I/U/G")
            result["profiles"][p] = {"C": len(final), "final_sha256": sha256_bytes(final), "invariants": inv,
                                     "verify_final": vf, "verify_forced": vz,
                                     "forced_sections": secs.get("sections"), "forced_sha256": sha256_bytes(forced) if forced else None}
            if not inv["ok"]:
                defects.append(f"{p}: accounting invariant violated: {inv}")
            for v in (vf, vz):
                if v is not None and not (v["native_ok"] and v["reference_ok"]):
                    defects.append(f"{p}: round-trip mismatch in {v['stream']} (native={v['native_ok']}, reference={v['reference_ok']})")
        # keep only final + forced streams of the project (raw.br equals the baseline when verified)
        result["stream_dir"] = str(out.relative_to(self.run_dir))
        if defects:
            ev = self.run_dir / "04_verification" / "defects" / f"{job.split}_{job.input_sha256[:16]}.json"
            atomic_write_json(ev, {"job": job.key, "defects": defects, "result": result})
            raise DefectError("; ".join(defects)[:2000])
        return result

    # ------------------------------------------------------------------ size: external comparator
    def size_external(self, job: JobSpec, src: Path) -> dict:
        m: Method = self.methods[job.method]
        ok, why = m.available()
        if not ok:
            return {"available": False, "reason": why}
        work = self._dir(job, "03_raw/streams")
        if work.exists():
            shutil.rmtree(work)
        cplan = m.compress_plan(str(src), "", str(work / "c"))
        cr = run_plan(cplan, self.timeout)
        if cr["returncode"] != 0:
            if any(s.get("timed_out") for s in cr["steps"]):
                raise TransientError(f"{m.name} compress timeout")
            raise RuntimeError(f"{m.name} compress failed: {cr.get('error', '')}")
        stream = work / f"{m.name}.stream"
        shutil.copyfile(cplan.produced, stream)
        shutil.rmtree(work / "c", ignore_errors=True)
        dplan = m.decompress_plan(str(stream), "", str(work / "d"))
        dr = run_plan(dplan, self.timeout)
        restored_ok = dr["returncode"] == 0 and Path(dplan.produced).read_bytes() == src.read_bytes()
        shutil.rmtree(work / "d", ignore_errors=True)
        data = stream.read_bytes()
        return {"available": True, "len": len(data), "sha256": sha256_bytes(data), "roundtrip_ok": restored_ok,
                "decoder": m.tool, "stream": str(stream.relative_to(self.run_dir))}

    # ------------------------------------------------------------------ timing
    def timing(self, job: JobSpec, src: Path) -> dict:
        m: Method = self.methods[job.method]
        ok, why = m.available()
        if not ok:
            return {"available": False, "reason": why}
        work = self._dir(job, f"06_performance/work/r{job.repeat}")
        if work.exists():
            shutil.rmtree(work)
        cplan = m.compress_plan(str(src), str(work / "stream.out"), str(work / "c"))
        cr = run_plan(cplan, self.timeout)
        if cr["returncode"] != 0:
            raise TransientError(f"timing compress failed: {cr.get('error', '')}")
        stream = work / "stream.bin"
        shutil.copyfile(cplan.produced, stream)
        dplan = m.decompress_plan(str(stream), str(work / "restored"), str(work / "d"))
        dr = run_plan(dplan, self.timeout)
        if dr["returncode"] != 0:
            raise TransientError(f"timing decompress failed: {dr.get('error', '')}")
        same = Path(dplan.produced).read_bytes() == src.read_bytes()  # post-decode verification (untimed)
        size = stream.stat().st_size
        shutil.rmtree(work, ignore_errors=True)
        if not same:
            raise DefectError(f"timing round-trip mismatch for {m.name}")
        keep = ("elapsed_s", "peak_memory_bytes", "user_s", "kernel_s")
        return {"available": True, "warmup": job.repeat == 0, "stream_len": size,
                "compress": {k: cr[k] for k in keep}, "decompress": {k: dr[k] for k in keep},
                "memory_metric": cr["memory_metric"]}
