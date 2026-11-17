"""Uniform compress/decompress adapters for external comparators and the project codec.

Each method produces a single-input stream and is decoded by its own pinned tool. A plan is a
list of steps executed by runner.measure (timed) with untimed staging (copy to a fixed member
name) and finalisation (move the produced file) around it.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from runner.common import CODEC_BIN, baselines_config, sha256_file
from runner.toolchain import tool_paths

MEMBER = "input.svg"


@dataclass
class Step:
    argv: list[str]
    cwd: str
    stdout_path: str | None = None


@dataclass
class Plan:
    steps: list[Step]
    produced: str                      # file holding the result after the steps
    staging: list[tuple[str, str]] = field(default_factory=list)  # (src, dst) copies before timing


def tool_exe(tool: str) -> str:
    if tool == "svgx":
        return str(CODEC_BIN)
    return tool_paths()[tool]


class Method:
    def __init__(self, name: str, spec: dict):
        self.name = name
        self.spec = spec
        self.tool = spec["tool"]
        self.project = bool(spec.get("project"))
        self.profile = spec.get("profile")
        self.primary = bool(spec.get("primary"))
        self.speed_only = bool(spec.get("speed_only"))
        self.container = spec.get("container")
        self.stdout = bool(spec.get("stdout"))

    @property
    def exe(self) -> str:
        return tool_exe(self.tool)

    def available(self) -> tuple[bool, str]:
        exe = self.exe
        if not exe or not Path(exe).exists():
            return False, f"dastur topilmadi: {exe or self.tool}"
        return True, ""

    def _fill(self, template: list[str], src: str, out: str) -> list[str]:
        return [t.replace("{in}", src).replace("{out}", out).replace("{name}", MEMBER) for t in template]

    def compress_plan(self, src: str, out: str, work: str) -> Plan:
        os.makedirs(work, exist_ok=True)
        if self.container == "workdir":       # XWRT writes <name>.xwrt next to the input
            staged = os.path.join(work, MEMBER)
            argv = [self.exe, *self._fill(self.spec["compress"], staged, out)]
            return Plan([Step(argv, work)], os.path.join(work, MEMBER + ".xwrt"), [(src, staged)])
        if self.container == "7z":
            staged = os.path.join(work, MEMBER)
            arc = os.path.join(work, "stream.7z")
            argv = [self.exe, *self._fill(self.spec["compress"], staged, arc)]
            return Plan([Step(argv, work)], arc, [(src, staged)])
        if self.stdout:
            tmp = os.path.join(work, "stream.out")
            return Plan([Step([self.exe, *self._fill(self.spec["compress"], src, "")], work, tmp)], tmp)
        tmp = os.path.join(work, "stream.out")
        return Plan([Step([self.exe, *self._fill(self.spec["compress"], src, tmp)], work)], tmp)

    def decompress_plan(self, stream: str, out: str, work: str) -> Plan:
        os.makedirs(work, exist_ok=True)
        if self.container == "workdir":
            staged = os.path.join(work, MEMBER + ".xwrt")
            argv = [self.exe, *self._fill(self.spec["decompress"], staged, out)]
            argv[-1] = staged
            return Plan([Step(argv, work)], os.path.join(work, MEMBER), [(stream, staged)])
        tmp = os.path.join(work, "restored.out")
        if self.container == "7z" or self.stdout:
            return Plan([Step([self.exe, *self._fill(self.spec["decompress"], stream, "")], work, tmp)], tmp)
        return Plan([Step([self.exe, *self._fill(self.spec["decompress"], stream, tmp)], work)], tmp)

    def describe(self) -> dict:
        ok, why = self.available()
        d = {
            "method": self.name, "label": self.spec.get("label", self.name), "tool": self.tool,
            "available": ok, "reason": why, "settings": self.spec.get("settings", ""),
            "limitations": self.spec.get("limitations", ""),
            "compress_template": self.spec["compress"], "decompress_template": self.spec["decompress"],
            "project": self.project, "primary": self.primary, "speed_only": self.speed_only,
        }
        if ok:
            d["exe_sha256"] = sha256_file(self.exe)
            d["exe"] = os.path.relpath(self.exe, start=str(Path(__file__).resolve().parent.parent))
        return d


def methods(include_speed_only: bool = True) -> dict[str, Method]:
    cfg = baselines_config()["method"]
    out = {n: Method(n, s) for n, s in cfg.items()}
    if not include_speed_only:
        out = {n: m for n, m in out.items() if not m.speed_only}
    return out


def run_plan_untimed(plan: Plan) -> None:
    """Execute a plan without measurement (used by tests and verification)."""
    import subprocess
    for s, d in plan.staging:
        shutil.copyfile(s, d)
    for st in plan.steps:
        if st.stdout_path:
            with open(st.stdout_path, "wb") as fh:
                r = subprocess.run(st.argv, cwd=st.cwd, stdout=fh, stderr=subprocess.PIPE)
        else:
            r = subprocess.run(st.argv, cwd=st.cwd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if r.returncode != 0:
            raise RuntimeError(f"{st.argv[0]} kod {r.returncode}: {r.stderr.decode('utf-8', 'replace')[-500:]}")


def roundtrip(method: Method, src: str, work: str) -> dict:
    """Compress and decompress `src` with the method's own tools; compare bytes."""
    w1, w2 = os.path.join(work, "c"), os.path.join(work, "d")
    for w in (w1, w2):
        shutil.rmtree(w, ignore_errors=True)
    cp = method.compress_plan(src, os.path.join(work, "stream"), w1)
    run_plan_untimed(cp)
    stream = os.path.join(work, f"{method.name}.stream")
    shutil.copyfile(cp.produced, stream)
    dp = method.decompress_plan(stream, os.path.join(work, "restored"), w2)
    run_plan_untimed(dp)
    with open(src, "rb") as a, open(dp.produced, "rb") as b:
        same = a.read() == b.read()
    return {"method": method.name, "stream_len": os.path.getsize(stream), "stream_sha256": sha256_file(stream),
            "roundtrip_ok": same}
