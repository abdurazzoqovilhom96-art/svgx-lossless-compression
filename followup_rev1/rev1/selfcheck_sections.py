"""REV1 preparation check (synthetic fixtures only): T/Z sections and restricted-mode codec streams.

For every synthetic fixture with at least one modelled block:
  * forced G streams for the four nested mode sets are decoded by both decoders;
  * literal, schedule, spelling and escape sections are byte-identical across mode sets;
  * forced lengths are monotone (00 >= 00,01 >= 00,01,10 >= all);
  * the T and Z sections round-trip exactly.
Writes results_rev1/prep/selfcheck_sections.json; exit 1 on any failure.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
from common import OUT, REV1, encode_all, svgx_raw_bytes, verify_stream, write_json  # noqa: E402
import sections  # noqa: E402

MODESETS = [("D0", "00"), ("M01", "00,01"), ("M010", "00,01,10"), ("F", None)]


def main() -> int:
    fx = sorted((REV1 / "fixtures" / "synthetic" / "svg").glob("*.svg"))
    work = OUT / "prep" / "_work_selfcheck"
    rows, fails = [], []
    for f in fx:
        original = f.read_bytes()
        arms = {}
        for name, modes in MODESETS:
            arms[name] = encode_all(f, work / name, modes)
        if arms["F"]["forced"]["G"] is None:
            rows.append({"fixture": f.name, "modelled": False})
            continue
        row = {"fixture": f.name, "modelled": True}
        secs = {}
        for name, _ in MODESETS:
            s = arms[name]["forced"]["G"]
            h = sections.parse_header(s)
            secs[name] = h
            row[f"forced_{name}"] = len(s)
            row[f"final_{name}"] = len(arms[name]["final"]["G"])
            v = verify_stream(s, original, work / "v")
            if not (v["native_ok"] and v["reference_ok"]):
                fails.append(f"{f.name} {name}: decode failed {v}")
        for name in ("D0", "M01", "M010"):
            for sec in ("literal_bytes", "schedule_bytes", "spelling_bytes", "escape_bytes"):
                if secs[name][sec] != secs["F"][sec]:
                    fails.append(f"{f.name} {name}: {sec} differs from F")
        chain = [row["forced_D0"], row["forced_M01"], row["forced_M010"], row["forced_F"]]
        if any(a < b for a, b in zip(chain, chain[1:])):
            fails.append(f"{f.name}: forced lengths not monotone {chain}")
        tz = sections.tz_arms(arms["F"]["forced"]["G"], original, lambda b: svgx_raw_bytes(b, work / "br"))
        row.update(tz)
        if not (tz["T_roundtrip_ok"] and tz["Z_roundtrip_ok"]):
            fails.append(f"{f.name}: T/Z round trip failed")
        rows.append(row)
    res = {"fixtures": len(fx), "modelled": sum(r["modelled"] for r in rows), "failures": fails, "rows": rows}
    write_json(OUT / "prep" / "selfcheck_sections.json", res)
    print(f"fixtures {len(fx)}, modelled {res['modelled']}, failures {len(fails)}")
    for x in fails:
        print("  FAIL", x)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
