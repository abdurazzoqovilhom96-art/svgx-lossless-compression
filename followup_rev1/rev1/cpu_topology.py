"""REV1 B3: identify a performance core (P-core) for pinned timing (docs/PROTOCOL_REV1.md §B3).

1. Windows GetSystemCpuSetInformation: every logical processor with its CoreIndex and EfficiencyClass
   (higher class = more performant core; on Intel hybrid CPUs P-cores have class 1, E-cores class 0).
2. Choice rule (fixed): among the cores of the highest efficiency class, skip the core that hosts logical
   processor 0 (interrupt/DPC traffic) and take the lowest logical processor of the next core.
3. Empirical confirmation on a SYNTHETIC fixture: `svgx bench --cpu K` on every logical processor; the chosen
   processor must be in the faster group (median encode time) and P-class processors must be faster than E-class.
Writes config/cpu_topology.json.
"""
from __future__ import annotations

import ctypes
import json
import statistics
import sys
from ctypes import wintypes as wt

sys.stdout.reconfigure(encoding="utf-8")
from common import REV1, SVGX, run, write_json  # noqa: E402

FIXTURE = REV1 / "fixtures" / "synthetic" / "svg" / "gen_structured_wins.svg"


def cpu_sets() -> list[dict]:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    f = k32.GetSystemCpuSetInformation
    f.argtypes = [ctypes.c_void_p, wt.ULONG, ctypes.POINTER(wt.ULONG), wt.HANDLE, wt.ULONG]
    f.restype = wt.BOOL
    need = wt.ULONG(0)
    f(None, 0, ctypes.byref(need), None, 0)
    buf = ctypes.create_string_buffer(need.value)
    if not f(buf, need, ctypes.byref(need), None, 0):
        raise OSError(ctypes.get_last_error(), "GetSystemCpuSetInformation")
    raw = buf.raw[:need.value]
    out, o = [], 0
    while o < len(raw):
        size = int.from_bytes(raw[o:o + 4], "little")
        typ = int.from_bytes(raw[o + 4:o + 8], "little")
        if typ == 0:  # CpuSetInformation
            out.append({"id": int.from_bytes(raw[o + 8:o + 12], "little"),
                        "group": int.from_bytes(raw[o + 12:o + 14], "little"),
                        "logical": raw[o + 14], "core": raw[o + 15], "llc": raw[o + 16], "numa": raw[o + 17],
                        "efficiency_class": raw[o + 18], "flags": raw[o + 19]})
        o += size
    return out


def choose(sets: list[dict]) -> int:
    top = max(s["efficiency_class"] for s in sets)
    core0 = next(s["core"] for s in sets if s["logical"] == 0 and s["group"] == 0)
    cores = sorted({s["core"] for s in sets if s["efficiency_class"] == top and s["core"] != core0 and s["group"] == 0})
    return min(s["logical"] for s in sets if s["core"] == cores[0] and s["group"] == 0)


def bench(cpu: int) -> float:
    r = run([SVGX, "bench", "--profile", "G", "--cpu", str(cpu), "--warmup", "3", "--repeats", "11", FIXTURE])
    j = json.loads(r.stdout)
    assert j["restored_ok"] and j["pinned"], j
    return statistics.median(j["encode_ns"]) / 1e6


def main() -> int:
    sets = cpu_sets()
    chosen = choose(sets)
    timing = {s["logical"]: bench(s["logical"]) for s in sets}
    top = max(s["efficiency_class"] for s in sets)
    p = [timing[s["logical"]] for s in sets if s["efficiency_class"] == top]
    e = [timing[s["logical"]] for s in sets if s["efficiency_class"] != top]
    confirmed = (not e or max(p) < min(e)) and timing[chosen] <= statistics.median(p) * 1.10
    res = {"cpu_sets": sets, "efficiency_classes": sorted({s["efficiency_class"] for s in sets}),
           "chosen_logical_processor": chosen, "fixture": FIXTURE.name,
           "median_encode_ms_by_logical": timing, "p_class_ms": [min(p), max(p)], "e_class_ms": [min(e), max(e)] if e else None,
           "confirmed": confirmed}
    write_json(REV1 / "config" / "cpu_topology.json", res)
    print(f"[cpu] logical processors {len(sets)}; classes {res['efficiency_classes']}; chosen {chosen}; "
          f"P {res['p_class_ms']} ms, E {res['e_class_ms']} ms; confirmed {confirmed}")
    return 0 if confirmed else 1


if __name__ == "__main__":
    sys.exit(main())
