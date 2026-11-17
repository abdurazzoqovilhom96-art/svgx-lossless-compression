"""Machine inventory (no personal machine identifiers) and SHA-256 file inventory of the delivery."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from runner.common import CODEC_BIN, atomic_write_text, sha256_file, tool_env, utc_now  # noqa: E402

INVENTORY_GLOBS = ["study.py", "*.cmd", "README_UZ.md", "requirements.in", "requirements.lock", "codec/Cargo.toml",
                   "codec/Cargo.lock", "codec/build.rs", "codec/rust-toolchain.toml", "codec/src/*.rs", "reference/*.py",
                   "config/*.toml", "docs/*.md", "datasets/*.py", "baselines/*.py", "runner/*.py", "reporting/*.py",
                   "tools/*.py", "tests/*.py", "fixtures/synthetic/expected.json"]


def _first_line(cmd) -> str:
    try:
        r = subprocess.run([str(c) for c in cmd], capture_output=True, timeout=60, env=tool_env())
        out = (r.stdout or b"") + (r.stderr or b"")
        return out.decode("utf-8", "replace").strip().splitlines()[0]
    except Exception as e:  # noqa: BLE001
        return f"unavailable ({e.__class__.__name__})"


def _cpu_name() -> str:
    if os.name == "nt":
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            return winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
        except OSError:
            pass
    return platform.processor() or "unknown"


def _gpus() -> list[str]:
    if os.name != "nt":
        return []
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "(Get-CimInstance Win32_VideoController).Name"], capture_output=True, timeout=60)
        return [x.strip() for x in r.stdout.decode("utf-8", "replace").splitlines() if x.strip()]
    except Exception:  # noqa: BLE001
        return []


def environment() -> dict:
    try:
        import psutil
        vm = psutil.virtual_memory()
        ram = {"total_bytes": vm.total, "available_bytes": vm.available}
        phys = psutil.cpu_count(logical=False)
    except ImportError:
        ram, phys = {}, None
    du = shutil.disk_usage(str(ROOT))
    from runner.toolchain import tool_paths
    tp = tool_paths()
    return {
        "generated_utc": utc_now(),
        "os": {"system": platform.system(), "release": platform.release(), "version": platform.version(),
               "machine": platform.machine()},
        "python": sys.version.split()[0], "python_implementation": platform.python_implementation(),
        "cpu": {"model": _cpu_name(), "logical": os.cpu_count(), "physical": phys},
        "ram": ram, "ram_limit": "none detected (no job/container memory limit)",
        "gpu": _gpus(), "gpu_used": False,
        "disk": {"project_drive_total_bytes": du.total, "project_drive_free_bytes": du.free},
        "toolchain": {
            "rustc": _first_line([ROOT / ".tools" / "cargo" / "bin" / "rustc", "--version"]),
            "cargo": _first_line([ROOT / ".tools" / "cargo" / "bin" / "cargo", "--version"]),
            "gcc": _first_line([tp["gcc"], "--version"]),
            "svgx": _first_line([CODEC_BIN, "--version"]),
        },
        "privacy": "no hostname, user name, serial numbers or machine IDs are recorded",
    }


def project_files(root: Path = ROOT) -> list[tuple[str, int, str]]:
    out = []
    seen = set()
    for g in INVENTORY_GLOBS:
        for p in sorted(root.glob(g)):
            if p.is_file() and p not in seen:
                seen.add(p)
                out.append((p.relative_to(root).as_posix(), p.stat().st_size, sha256_file(p)))
    return out


def write_project_files(path: Path) -> int:
    rows = project_files()
    text = "path\tbytes\tsha256\n" + "".join(f"{a}\t{b}\t{c}\n" for a, b, c in rows)
    atomic_write_text(path, text)
    return len(rows)
