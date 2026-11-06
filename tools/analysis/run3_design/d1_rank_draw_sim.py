#!/usr/bin/env python3
"""DECISIVE 1 (selection inside a level): the within-group cell weight, simulated (no lab files read).

    python -B tools/analysis/run3_design/d1_rank_draw_sim.py [--out logs/run3_design]

One night of draws in a group of N eligible cells ranked by arrival tick, weight (1 + rank)^-alpha x max(nu, 1 / (1 + draws of
the cell)); no new cells. Group sizes are the eligible counts at run 3's start (d1_census.py); draws per night assume run 2's
volume (39,309 dispatches), 80 % exploitation, level weights 0.53 / 0.27 and the normalised-then-floored shares of
d1_group_shares.py. Prints the 10 earliest cells' share, cells never drawn, and the first five ranks' draw counts, for the
approved alpha = 1, nu = 0.05 against alpha = 0.5 and nu = 0.2.
"""
import bisect
import random
from itertools import accumulate

import _common as C

a = C.parse(__doc__)


def sim(N, D, alpha=1.0, nu=0.05, seed=1):
    rng = random.Random(seed)
    fresh = [0] * N
    cnt = [0] * N
    for _ in range(D):
        w = [(1 + r) ** -alpha * max(nu, 1 / (1 + fresh[r])) for r in range(N)]
        cum = list(accumulate(w))
        i = min(bisect.bisect_right(cum, rng.random() * cum[-1]), N - 1)
        cnt[i] += 1
        fresh[i] += 1
    return sum(cnt[:10]) / D, sum(1 for c in cnt if c == 0), cnt[:5]


out = {}
for name, N, D in (("(9,2)", 433, int(39309 * .8 * .53 * .51)), ("(9,256)", 53, int(39309 * .8 * .53 * .42)),
                   ("(9,64)", 1054, int(39309 * .8 * .53 * .08)), ("(8,258)", 1742, int(39309 * .8 * .27 * .60)),
                   ("(8,66)", 2519, int(39309 * .8 * .27 * .32))):
    for al, nu in ((1.0, 0.05), (0.5, 0.05), (1.0, 0.2)):
        t, nv, head = sim(N, D, al, nu)
        print(f"{name} N={N} D={D} alpha={al} nu={nu}: top-10 share {t:.2f}, never dispatched {nv} of {N} ({nv / N:.0%}), first 5 ranks {head}")
        out[f"{name}|{al}|{nu}"] = {"N": N, "D": D, "top10": t, "never": nv, "first5": head}
C.dump(a, "d1_rank_draw_sim.json", out)
