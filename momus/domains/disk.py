"""Disk-arm scheduling: FCFS, SSTF, SCAN, C-SCAN, LOOK, C-LOOK.

The disk has C cylinders and the head starts at cylinder C // 2 moving up.
Moving one cylinder takes one time unit; service time is otherwise zero.

Two attack modes:
* 'seek'  - all requests are queued at time 0. Cost = total head movement.
            Reference = the offline optimum, which on a line is
            min(|h - lo|, |h - hi|) + (hi - lo): sweep to the nearer end first.
* 'wait'  - requests arrive over time. Cost = maximum waiting time
            (completion - arrival). Reference = FCFS on the same workload,
            so the fitness reads "how much worse is the worst-off request
            than under first-come first-served" (starvation).
"""
from __future__ import annotations

import numpy as np

from ..genome import RowGenome
from ..problem import Problem


def simulate(policy, arrivals, cyls, n_cyl, head=None):
    """Return (total head movement, list of waits)."""
    n = len(cyls)
    pos = n_cyl // 2 if head is None else head
    order = sorted(range(n), key=lambda i: (arrivals[i], i))
    pending = []
    t, nxt, moved = 0, 0, 0
    up = True
    waits = [0] * n
    top = n_cyl - 1

    def admit():
        nonlocal nxt
        while nxt < n and arrivals[order[nxt]] <= t:
            pending.append(order[nxt])
            nxt += 1

    served = 0
    while served < n:
        admit()
        if not pending:
            t = arrivals[order[nxt]]
            continue
        if policy == "FCFS":
            j = min(pending, key=lambda i: (arrivals[i], i))
        elif policy == "SSTF":
            j = min(pending, key=lambda i: (abs(cyls[i] - pos), arrivals[i], i))
        elif policy in ("SCAN", "LOOK"):
            ahead = [i for i in pending if (cyls[i] >= pos if up else cyls[i] <= pos)]
            if not ahead:
                if policy == "SCAN":  # travel to the edge before reversing
                    edge = top if up else 0
                    moved += abs(edge - pos)
                    t += abs(edge - pos)
                    pos = edge
                up = not up
                continue
            j = min(ahead, key=lambda i: (abs(cyls[i] - pos), arrivals[i], i))
        elif policy in ("C-SCAN", "C-LOOK"):
            ahead = [i for i in pending if cyls[i] >= pos]
            if not ahead:
                if policy == "C-SCAN":  # to the top edge, then return sweep to 0
                    d = (top - pos) + top
                    pos = 0
                else:  # jump straight to the lowest pending request
                    low = min(cyls[i] for i in pending)
                    d = pos - low
                    pos = low
                moved += d
                t += d
                continue
            j = min(ahead, key=lambda i: (cyls[i] - pos, arrivals[i], i))
        else:
            raise ValueError(policy)
        d = abs(cyls[j] - pos)
        moved += d
        t += d
        pos = cyls[j]
        pending.remove(j)
        waits[j] = t - arrivals[j]
        served += 1
    return moved, waits


POLICIES = ["FCFS", "SSTF", "SCAN", "C-SCAN", "LOOK", "C-LOOK"]


def optimal_seek(cyls, head):
    lo, hi = min(cyls), max(cyls)
    return min(abs(head - lo), abs(head - hi)) + (hi - lo)


def features(arrivals, cyls, n_cyl, max_arrival):
    c = np.asarray(cyls, dtype=float)
    head = n_cyl // 2
    return {
        "cyl_spread": float(min(1.0, 2 * c.std() / n_cyl)),
        "near_head_frac": float((np.abs(c - head) <= n_cyl * 0.1).mean()),
        "edge_frac": float(((c < n_cyl * 0.1) | (c >= n_cyl * 0.9)).mean()),
        "arrival_span": float((max(arrivals) - min(arrivals)) / max_arrival) if max_arrival else 0.0,
    }


def make_problem(target="SSTF", n_req=24, n_cyl=200, max_arrival=400, mode="seek") -> Problem:
    space = RowGenome(n_req, [(0, max_arrival), (0, n_cyl - 1)])
    head = n_cyl // 2

    def fn(g):
        arr, cyl = g[:, 0].tolist(), g[:, 1].tolist()
        feats = features(arr, cyl, n_cyl, max_arrival)
        if mode == "seek":
            zeros = [0] * len(cyl)
            moved, _ = simulate(target, zeros, cyl, n_cyl, head)
            opt = optimal_seek(cyl, head)
            fit = (moved + 1) / (opt + 1)
            info = {"target_cost": moved, "ref_cost": opt}
            desc = (feats["cyl_spread"], feats["near_head_frac"])
        else:
            _, wa = simulate(target, arr, cyl, n_cyl, head)
            _, wf = simulate("FCFS", arr, cyl, n_cyl, head)
            fit = (max(wa) + 1) / (max(wf) + 1)
            info = {"target_cost": max(wa), "ref_cost": max(wf)}
            desc = (feats["cyl_spread"], feats["arrival_span"])
        info.update(feats)
        return fit, desc, info

    d2 = "requests near head" if mode == "seek" else "arrival spread"
    return Problem(f"disk-{mode}-{target}", "disk", space, fn, ("cylinder spread", d2),
                   {"target": target, "mode": mode,
                    "reference": "offline optimum" if mode == "seek" else "FCFS"})
