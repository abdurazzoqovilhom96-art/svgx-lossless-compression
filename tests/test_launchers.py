"""The actual .cmd launchers, executed through PowerShell (Windows). Paths with spaces and Unicode,
argument forwarding and exit-code propagation; plus the real launchers in the project root."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LAUNCHERS = {"prepare.cmd": "prepare", "selftest.cmd": "selftest", "run_experiment.cmd": "run",
             "report.cmd": "report", "package.cmd": "package"}
STUB = '''import json, sys
from pathlib import Path
Path(__file__).with_name("stub_log.json").write_text(
    json.dumps({"argv": sys.argv[1:], "here": str(Path(__file__).resolve().parent)}, ensure_ascii=False), encoding="utf-8")
print("stub ✓ oʻzbekcha chiqish")
sys.exit(int(sys.argv[-1]) if sys.argv[-1].isdigit() else 0)
'''

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows launchers are verified on Windows hosts only")


def ps(command: str) -> subprocess.CompletedProcess:
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True)


def test_launchers_spaces_unicode_exit_codes(tmp_path):
    d = tmp_path / "svg sinov oʻzbek ✓"
    d.mkdir()
    for name in LAUNCHERS:
        shutil.copyfile(ROOT / name, d / name)
    (d / "study.py").write_text(STUB, encoding="utf-8")
    for name, sub in LAUNCHERS.items():
        for code in (0, 7):
            r = ps(f"& '{d / name}' 'arg with space' 'ü—ʻ' {code}; exit $LASTEXITCODE")
            assert r.returncode == code, (name, r.stdout, r.stderr)
            log = json.loads((d / "stub_log.json").read_text(encoding="utf-8"))
            assert log["argv"] == [sub, "arg with space", "ü—ʻ", str(code)], name
            assert Path(log["here"]) == d.resolve()


def test_real_launchers_in_project_root():
    for name in LAUNCHERS:
        r = ps(f"& '{ROOT / name}' --help; exit $LASTEXITCODE")
        assert r.returncode == 0, (name, r.stderr)
    r = ps(f"& '{ROOT / 'report.cmd'}' --run-id NO_SUCH_RUN_ID; exit $LASTEXITCODE")
    assert r.returncode == 2
    r = ps(f"& '{ROOT / 'package.cmd'}'; exit $LASTEXITCODE")
    assert r.returncode == 2  # missing required --run-id is propagated
