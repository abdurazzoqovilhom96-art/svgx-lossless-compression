"""REV1 preparation: build check, cargo test and pytest; writes state/prep_tests.json (required by freeze.py).

The project-local Rust toolchain and WinLibs GCC of the original project are used read-only.
"""
from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
from common import ORIG, PY, REV1, STATE, SVGX, sha256_file, write_json  # noqa: E402

TOOLS = ORIG / ".tools"


def env() -> dict:
    e = {k: v for k, v in os.environ.items() if k.upper() != "NODEFAULTCURRENTDIRECTORYINEXEPATH"}
    gcc_bin = TOOLS / "winlibs" / "mingw64" / "bin"
    e.update(RUSTUP_HOME=str(TOOLS / "rustup"), CARGO_HOME=str(TOOLS / "cargo"),
             PATH=os.pathsep.join([str(TOOLS / "cargo" / "bin"), str(gcc_bin), e.get("PATH", "")]),
             CC_x86_64_pc_windows_gnu=str(gcc_bin / "gcc.exe"), AR_x86_64_pc_windows_gnu=str(gcc_bin / "ar.exe"),
             CARGO_TARGET_X86_64_PC_WINDOWS_GNU_LINKER=str(gcc_bin / "gcc.exe"),
             BROTLI_SRC=str(REV1 / "codec" / "third_party" / "brotli"), PYTHONUTF8="1")
    return e


def tail(b: bytes, n=1500) -> str:
    return b.decode("utf-8", "replace")[-n:]


def main() -> int:
    cargo = TOOLS / "cargo" / "bin" / "cargo.exe"
    before = sha256_file(SVGX)
    b = subprocess.run([str(cargo), "build", "--release", "--locked"], cwd=REV1 / "codec", env=env(), capture_output=True)
    after = sha256_file(SVGX)
    t = subprocess.run([str(cargo), "test", "--release", "--locked"], cwd=REV1 / "codec", env=env(), capture_output=True)
    out = tail(t.stdout + t.stderr, 4000)
    p = subprocess.run([str(PY), "-m", "pytest", "-q", "tests", "tests_rev1", "-p", "tests_rev1.orig_tools_plugin",
                        "-p", "no:cacheprovider"], cwd=REV1, capture_output=True)
    rec = {"recorded_utc": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
           "cargo_build": {"returncode": b.returncode, "binary_unchanged": before == after, "svgx_sha256": after,
                           "tail": tail(b.stderr, 600)},
           "cargo_test": {"returncode": t.returncode, "passed": t.returncode == 0 and "test result: ok" in out,
                          "summary": [ln for ln in out.splitlines() if ln.startswith("test result")]},
           "pytest": {"returncode": p.returncode, "passed": p.returncode == 0, "summary": tail(p.stdout, 300).strip().splitlines()[-1:]}}
    write_json(STATE / "prep_tests.json", rec)
    print(f"[prep-tests] build rc {b.returncode} (binary unchanged {before == after}); cargo test {rec['cargo_test']['summary']}; "
          f"pytest {rec['pytest']['summary']}")
    return 0 if rec["cargo_test"]["passed"] and rec["pytest"]["passed"] and b.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
