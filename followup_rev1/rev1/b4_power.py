"""REV1 B4 (optional) planning: number of new families by simulation from EXISTING frozen results (no new data).

Population model: confirmation files of the B4 stratum (illustrations and maps larger than 64 KiB), frozen G and
Brotli-11 sizes from the ledger. A simulated holdout of n families draws n stratum families with replacement and at
most 5 files from each (without replacement, the B4 concentration cap). Success: the lower Bonferroni bound (k = 2,
family coverage 99.5 %, tail 0.005/4) of the family-cluster percentile bootstrap of Gain(G vs Brotli) exceeds
delta = 1.0 %. Power = success rate. Chosen n = the smallest n with power >= 0.8, but at least 30.
Writes config/b4_power.json. B4 data collection itself needs a separate approval.
"""
from __future__ import annotations

import sys
from collections import defaultdict

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
from common import REV1, ledger_size_results, manifest, write_json  # noqa: E402

DELTA, SIMS, RES, SEED = 0.01, 400, 2000, 20261116
TAIL = 0.005 / 4


def main() -> int:
    rows = [r for r in manifest("confirmation") if r["category"] in ("illustrations", "maps") and int(r["size"]) > 65536]
    led = ledger_size_results({r["file_id"] for r in rows})
    fam = defaultdict(list)
    for r in rows:
        fam[r["family"]].append((led[r["file_id"]]["B"], led[r["file_id"]]["profiles"]["G"]["C"]))
    fams = [np.array(v, dtype=np.float64) for v in fam.values()]
    rng = np.random.Generator(np.random.PCG64(SEED))
    out = {"stratum_files": len(rows), "stratum_families": len(fams), "delta": DELTA, "sims": SIMS, "resamples": RES,
           "observed_gain": float(1 - sum(f[:, 1].sum() for f in fams) / sum(f[:, 0].sum() for f in fams)), "power": {}}
    chosen = None
    out["power_delta0"] = {}
    for n in range(10, 121, 10):
        ok = ok0 = 0
        for _ in range(SIMS):
            pick = rng.integers(0, len(fams), size=n)
            sums = []
            for j in pick:
                f = fams[j]
                sel = f[rng.permutation(len(f))[:5]]
                sums.append(sel.sum(axis=0))
            S = np.array(sums)                          # (n, 2): B, C
            idx = rng.integers(0, n, size=(RES, n))
            b = S[idx, 0].sum(axis=1)
            c = S[idx, 1].sum(axis=1)
            lo = np.quantile(1 - c / b, TAIL, method="linear")
            ok += lo > DELTA
            ok0 += lo > 0
        out["power"][n] = ok / SIMS
        out["power_delta0"][n] = ok0 / SIMS
        print(f"   n={n}: power {ok / SIMS:.3f} (delta=0: {ok0 / SIMS:.3f})", flush=True)
        if chosen is None and ok / SIMS >= 0.8:
            chosen = n
    out["chosen_families"] = max(30, chosen) if chosen else None
    out["note"] = "None means power 0.8 is not reached for n <= 120 under this population model"
    write_json(REV1 / "config" / "b4_power.json", out)
    print(f"[B4-power] stratum {len(rows)} files / {len(fams)} families; observed gain {out['observed_gain']:.4f}; chosen n {out['chosen_families']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
