"""Shared test helpers. Every artefact produced by tests is SYNTHETIC and lives in pytest tmp dirs."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "reference"))

from runner.common import CODEC_BIN, FIXTURES  # noqa: E402

SVG_DIR = FIXTURES / "svg"


def svgx(*args, check=True):
    r = subprocess.run([str(CODEC_BIN), *map(str, args)], capture_output=True)
    if check and r.returncode != 0:
        raise AssertionError(r.stderr.decode("utf-8", "replace"))
    return r


def fixture_files():
    return sorted(SVG_DIR.glob("*.svg"))


@pytest.fixture(scope="session")
def ref():
    import decode as reference
    return reference
