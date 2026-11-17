"""Real subprocess measurements: wall time, process-tree peak memory and CPU time.

On Windows each command runs suspended inside a Job Object, is resumed, and the job's
PeakJobMemoryUsed (peak committed bytes of the whole process tree) plus the accounting user/kernel
times are read after exit. Elsewhere the getrusage(RUSAGE_CHILDREN) maximum RSS is used and the
metric name says so.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time

from baselines.adapters import Plan

IS_WIN = os.name == "nt"
MEMORY_METRIC = ("job.PeakJobMemoryUsed (bytes, peak committed memory of the process tree)" if IS_WIN
                 else "getrusage(RUSAGE_CHILDREN).ru_maxrss (max resident set)")

if IS_WIN:
    import ctypes
    from ctypes import wintypes as wt

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll")

    class _IO(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

    class _BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wt.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wt.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wt.DWORD), ("SchedulingClass", wt.DWORD)]

    class _EXT(ctypes.Structure):
        _fields_ = [("Basic", _BASIC), ("Io", _IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    class _ACCT(ctypes.Structure):
        _fields_ = [("TotalUserTime", ctypes.c_longlong), ("TotalKernelTime", ctypes.c_longlong),
                    ("ThisPeriodTotalUserTime", ctypes.c_longlong), ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
                    ("TotalPageFaultCount", wt.DWORD), ("TotalProcesses", wt.DWORD),
                    ("ActiveProcesses", wt.DWORD), ("TotalTerminatedProcesses", wt.DWORD)]

    _k32.CreateJobObjectW.restype = wt.HANDLE
    _k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wt.LPCWSTR]
    _k32.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
    _k32.QueryInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p]
    _k32.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
    _k32.TerminateJobObject.argtypes = [wt.HANDLE, wt.UINT]
    _k32.CloseHandle.argtypes = [wt.HANDLE]
    _ntdll.NtResumeProcess.argtypes = [wt.HANDLE]
    CREATE_SUSPENDED = 0x00000004
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000


def _thread_env() -> dict:
    env = dict(os.environ)
    for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "RAYON_NUM_THREADS"):
        env[k] = "1"
    return env


def run_measured(argv: list[str], cwd: str, stdout_path: str | None = None, timeout: float | None = None) -> dict:
    """Run one command and return its measurements (never raises for non-zero exit)."""
    out_fh = open(stdout_path, "wb") if stdout_path else subprocess.DEVNULL
    try:
        if IS_WIN:
            job = _k32.CreateJobObjectW(None, None)
            ext = _EXT()
            ext.Basic.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            _k32.SetInformationJobObject(job, 9, ctypes.byref(ext), ctypes.sizeof(ext))
            proc = subprocess.Popen(argv, cwd=cwd, stdout=out_fh, stderr=subprocess.PIPE,
                                    creationflags=CREATE_SUSPENDED, env=_thread_env())
            try:
                if not _k32.AssignProcessToJobObject(job, int(proc._handle)):  # noqa: SLF001
                    raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject")
                t0 = time.perf_counter_ns()
                _ntdll.NtResumeProcess(int(proc._handle))  # noqa: SLF001
                try:
                    _, err = proc.communicate(timeout=timeout)
                    timed_out = False
                except subprocess.TimeoutExpired:
                    _k32.TerminateJobObject(job, 1)
                    _, err = proc.communicate()
                    timed_out = True
                t1 = time.perf_counter_ns()
                q = _EXT()
                _k32.QueryInformationJobObject(job, 9, ctypes.byref(q), ctypes.sizeof(q), None)
                a = _ACCT()
                _k32.QueryInformationJobObject(job, 1, ctypes.byref(a), ctypes.sizeof(a), None)
                res = {"returncode": proc.returncode, "elapsed_s": (t1 - t0) / 1e9,
                       "peak_memory_bytes": int(q.PeakJobMemoryUsed),
                       "peak_process_memory_bytes": int(q.PeakProcessMemoryUsed),
                       "user_s": a.TotalUserTime / 1e7, "kernel_s": a.TotalKernelTime / 1e7,
                       "processes": int(a.TotalProcesses), "timed_out": timed_out}
            finally:
                _k32.CloseHandle(job)
        else:
            import resource
            before = resource.getrusage(resource.RUSAGE_CHILDREN)
            t0 = time.perf_counter_ns()
            proc = subprocess.Popen(argv, cwd=cwd, stdout=out_fh, stderr=subprocess.PIPE, env=_thread_env())
            try:
                _, err = proc.communicate(timeout=timeout)
                timed_out = False
            except subprocess.TimeoutExpired:
                proc.kill()
                _, err = proc.communicate()
                timed_out = True
            t1 = time.perf_counter_ns()
            after = resource.getrusage(resource.RUSAGE_CHILDREN)
            res = {"returncode": proc.returncode, "elapsed_s": (t1 - t0) / 1e9,
                   "peak_memory_bytes": int(after.ru_maxrss) * 1024, "peak_process_memory_bytes": None,
                   "user_s": after.ru_utime - before.ru_utime, "kernel_s": after.ru_stime - before.ru_stime,
                   "processes": 1, "timed_out": timed_out}
    finally:
        if stdout_path:
            out_fh.close()
    res["stderr_tail"] = (err or b"").decode("utf-8", "replace")[-400:]
    res["memory_metric"] = MEMORY_METRIC
    return res


def run_plan(plan: Plan, timeout: float | None = None) -> dict:
    """Stage inputs (untimed), run every step measured, return summed time and max memory."""
    for s, d in plan.staging:
        shutil.copyfile(s, d)
    total = {"returncode": 0, "elapsed_s": 0.0, "peak_memory_bytes": 0, "user_s": 0.0, "kernel_s": 0.0,
             "steps": []}
    for st in plan.steps:
        r = run_measured(st.argv, st.cwd, st.stdout_path, timeout)
        total["steps"].append(r)
        total["elapsed_s"] += r["elapsed_s"]
        total["user_s"] += r["user_s"] or 0.0
        total["kernel_s"] += r["kernel_s"] or 0.0
        total["peak_memory_bytes"] = max(total["peak_memory_bytes"], r["peak_memory_bytes"] or 0)
        if r["returncode"] != 0 or r["timed_out"]:
            total["returncode"] = r["returncode"] if r["returncode"] != 0 else -1
            total["error"] = r["stderr_tail"]
            break
    total["memory_metric"] = MEMORY_METRIC
    return total
