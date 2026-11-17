"""Shared helpers for the SVG experiment controller (stdlib only, usable before the venv exists)."""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / ".tools"
DOWNLOADS = TOOLS / "downloads"
STATE = ROOT / "state"
READINESS = ROOT / "readiness"
RESULTS = ROOT / "results"
CONFIG = ROOT / "config"
FIXTURES = ROOT / "fixtures" / "synthetic"
VENV = ROOT / ".venv"
VENV_PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
EXE = ".exe" if os.name == "nt" else ""
CODEC_BIN = ROOT / "codec" / "target" / "release" / f"svgx{EXE}"
USER_AGENT = "svg-experiment-fetcher/0.1 (research tool; generic client)"


def say(msg: str) -> None:
    """Print a user-facing (Uzbek) status line immediately."""
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:  # legacy console code page
        sys.stdout.buffer.write((msg + "\n").encode("utf-8", "replace"))
        sys.stdout.flush()


def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path | str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def atomic_write_bytes(path: Path | str, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_text(path: Path | str, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def atomic_write_json(path: Path | str, obj) -> None:
    atomic_write_text(path, canonical_json(obj))


def read_json(path: Path | str, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def load_toml(path: Path | str) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def study_config() -> dict:
    return load_toml(CONFIG / "study.toml")


def baselines_config() -> dict:
    return load_toml(CONFIG / "baselines.toml")


def toolchain_config() -> dict:
    return load_toml(CONFIG / "toolchain.toml")


def tool_env() -> dict:
    """Environment with the project-local toolchain first on PATH."""
    env = dict(os.environ)
    env["RUSTUP_HOME"] = str(TOOLS / "rustup")
    env["CARGO_HOME"] = str(TOOLS / "cargo")
    gcc_bin = TOOLS / "winlibs" / "mingw64" / "bin"
    extra = [str(TOOLS / "cargo" / "bin"), str(gcc_bin)]
    env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "")])
    gcc = gcc_bin / f"gcc{EXE}"
    if gcc.exists():
        env["CC_x86_64_pc_windows_gnu"] = str(gcc)
        env["AR_x86_64_pc_windows_gnu"] = str(gcc_bin / f"ar{EXE}")
        env["CARGO_TARGET_X86_64_PC_WINDOWS_GNU_LINKER"] = str(gcc)
    env["BROTLI_SRC"] = str(ROOT / "codec" / "third_party" / "brotli")
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def run(cmd, *, cwd=None, env=None, check=True, capture=False, timeout=None):
    """Run a command list; return CompletedProcess. Never uses a shell."""
    res = subprocess.run(
        [str(c) for c in cmd],
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        timeout=timeout,
    )
    if check and res.returncode != 0:
        err = ""
        if capture and res.stderr:
            err = res.stderr.decode("utf-8", "replace")[-4000:]
        raise RuntimeError(f"Buyruq xato bilan tugadi ({res.returncode}): {' '.join(map(str, cmd))}\n{err}")
    return res


def rel(path: Path | str) -> str:
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)
