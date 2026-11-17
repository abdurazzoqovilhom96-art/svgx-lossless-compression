"""Project-local Python virtual environment with a hash-locked dependency set (stdlib only)."""
from __future__ import annotations

import subprocess
import sys

from .common import ROOT, VENV, VENV_PY, read_json, run, say, sha256_file, toolchain_config, atomic_write_json

LOCK = ROOT / "requirements.lock"
REQ_IN = ROOT / "requirements.in"
STAMP = ROOT / ".tools" / "stamps" / "venv.json"


def _cutoff() -> str:
    return toolchain_config()["python"]["uploaded_prior_to"]


def ensure_venv() -> None:
    if VENV_PY.exists():
        return
    say("  … Python virtual muhiti yaratilmoqda (.venv)")
    run([sys.executable, "-m", "venv", VENV], capture=True)


def ensure_lock() -> None:
    """Generate requirements.lock with pip-tools if it does not exist yet."""
    if LOCK.exists():
        return
    say("  … requirements.lock hosil qilinmoqda (pip-compile --generate-hashes)")
    cutoff = _cutoff()
    run([VENV_PY, "-m", "pip", "install", "--quiet", f"--uploaded-prior-to={cutoff}", "pip-tools"], capture=True)
    run([VENV_PY, "-m", "piptools", "compile", "--quiet", "--generate-hashes", "--allow-unsafe",
         "--strip-extras", "--no-emit-index-url", f"--pip-args=--uploaded-prior-to={cutoff}",
         "--output-file", LOCK, REQ_IN], cwd=ROOT, capture=True)


def install() -> None:
    token = sha256_file(LOCK)
    st = read_json(STAMP) or {}
    if st.get("lock") == token and VENV_PY.exists():
        return
    say("  … bog'liqliklar o'rnatilmoqda (pip install --require-hashes)")
    run([VENV_PY, "-m", "pip", "install", "--quiet", "--require-hashes", "--no-deps", "-r", LOCK], capture=True)
    res = subprocess.run([str(VENV_PY), "-m", "pip", "check"], capture_output=True)
    if res.returncode != 0:
        raise RuntimeError("pip check: " + res.stdout.decode("utf-8", "replace"))
    atomic_write_json(STAMP, {"lock": token})


def ensure() -> None:
    ensure_venv()
    ensure_lock()
    install()
