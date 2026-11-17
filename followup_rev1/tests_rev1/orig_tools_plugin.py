"""pytest plugin for running the ORIGINAL test suite inside the REV1 copy.

The REV1 copy has no .tools directory; the pinned comparator binaries are used read-only from the original project.
Usage: python -m pytest tests -p tests_rev1.orig_tools_plugin
"""
from pathlib import Path

import runner.toolchain as tc
import runner.verify as rv

ORIG = Path(r"D:/13.11.2026/SVG_EXPERIMENT")
ORIG_TOOLS = ORIG / ".tools"
tc.TOOLS = ORIG_TOOLS
tc.BIN = ORIG_TOOLS / "bin"
tc.SRC = ORIG_TOOLS / "src"
tc.STAMPS = ORIG_TOOLS / "stamps"
rv.VENV_PY = ORIG / ".venv" / "Scripts" / "python.exe"   # REV1 has no venv of its own
