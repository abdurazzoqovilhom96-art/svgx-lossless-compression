"""Synthetic self-test: codec unit tests, CLI help, golden fixtures with both decoders, pytest suite
(round trips, conformance, authorization with mocked workers, synthetic end-to-end reports and ZIP,
launchers in PowerShell) and synthetic throughput for the pre-approval estimate."""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from .common import CODEC_BIN, FIXTURES, READINESS, ROOT, VENV_PY, atomic_write_json, say, sha256_file, tool_env, utc_now


def _run(cmd, timeout=3600):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, cwd=str(ROOT), env=tool_env(), timeout=timeout)
    return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")


def throughput() -> dict:
    """MiB/s of compress+decompress per method on synthetic fixtures (cold processes)."""
    from baselines.adapters import methods
    from .measure import run_plan
    from .verify import reference_decode
    files = [FIXTURES / "svg" / "gen_large_window_rescale.svg", FIXTURES / "svg" / "gen_structured_wins.svg"]
    mib = sum(f.stat().st_size for f in files) / (1 << 20)
    out = {}
    with tempfile.TemporaryDirectory(prefix="svgx_tp_") as td:
        for name, m in methods().items():
            if not m.available()[0]:
                continue
            secs = 0.0
            for i, f in enumerate(files):
                w = Path(td) / name / str(i)
                cp = m.compress_plan(str(f), str(w / "s"), str(w / "c"))
                r1 = run_plan(cp)
                dp = m.decompress_plan(cp.produced, str(w / "r"), str(w / "d"))
                r2 = run_plan(dp)
                secs += r1["elapsed_s"] + r2["elapsed_s"]
            out[name] = mib / secs if secs else None
        secs = 0.0
        for i, f in enumerate(files):
            s = Path(td) / f"g{i}.svgx"
            subprocess.run([str(CODEC_BIN), "encode", "--profile", "G", "--force-structured", str(f), str(s)], check=True)
            secs += reference_decode(s, Path(td) / f"g{i}.out")["elapsed_s"]
        out["svgx_ref_decode"] = mib / secs if secs else None
    return out


def run_selftest(codec: dict | None = None) -> dict:
    res = {"generated_utc": utc_now(), "synthetic": True}
    if codec is None:
        cargo = ROOT / ".tools" / "cargo" / "bin" / "cargo.exe"
        rc, out = _run([cargo, "test", "--release", "--locked", "--manifest-path", ROOT / "codec" / "Cargo.toml"])
        passed = sum(int(m) for m in re.findall(r"test result: ok\. (\d+) passed", out))
        codec = {"cargo_test_returncode": rc, "cargo_tests_passed": passed, "binary_sha256": sha256_file(CODEC_BIN)}
    res.update({k: codec.get(k) for k in ("cargo_test_returncode", "cargo_tests_passed", "binary_sha256")})
    rc, out = _run([CODEC_BIN, "--help"])
    res["svgx_help"] = rc == 0 and "encode" in out and "decode" in out
    say("  … golden fixture'lar va ikkala dekoder")
    rc, out = _run([VENV_PY, ROOT / "tools" / "fixtures.py", "check"])
    res["fixtures"] = "muvaffaqiyatli" if rc == 0 else "xato: " + out[-500:]
    say("  … pytest (round-trip, format, ruxsat, sintetik end-to-end, launcherlar)")
    rc, out = _run([VENV_PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(ROOT / "tests")], timeout=7200)
    m = re.findall(r"(\d+ passed[^\n]*)", out)
    res["pytest_returncode"] = rc
    res["pytest_summary"] = m[-1].strip() if m else out[-300:]
    res["pytest_tail"] = out[-3000:] if rc else ""
    res["launchers"] = "PowerShell orqali tekshirildi (tests/test_launchers.py)" if rc == 0 else "pytest bilan birga xato"
    say("  … sintetik o'tkazuvchanlik (vaqt bahosi uchun)")
    try:
        res["throughput_MiB_s"] = throughput()
    except Exception as e:  # noqa: BLE001
        res["throughput_MiB_s"] = {}
        res["throughput_error"] = str(e)
    res["ok"] = (res["cargo_test_returncode"] == 0 and res["svgx_help"] and res["fixtures"] == "muvaffaqiyatli"
                 and res["pytest_returncode"] == 0)
    atomic_write_json(READINESS / "selftest.json", res)
    return res
