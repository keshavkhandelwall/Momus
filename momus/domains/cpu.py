"""CPU scheduling on one core: FCFS, SJF, Priority, SRTF, Round Robin, MLFQ.

A workload is N processes, each (arrival time, CPU burst, priority). Time is
integer and context switches are free. Every simulator returns the completion
time of each process; turnaround = completion - arrival.

References with known optimality on one machine:
* SRTF minimises mean turnaround (and mean waiting) among all schedulers,
  preemptive or not (Schrage 1968).
* FCFS minimises the maximum turnaround (max flow time) among all schedulers.
"""
from __future__ import annotations

import heapq
from collections import deque

import numpy as np

from ..genome import RowGenome
from ..problem import Problem


def _nonpreemptive(arr, burst, key):
    n = len(arr)
    order = sorted(range(n), key=lambda i: (arr[i], i))
    done = [0] * n
    t, nxt, ready = 0, 0, []
    for _ in range(n):
        while nxt < n and arr[order[nxt]] <= t:
            i = order[nxt]
            heapq.heappush(ready, (key(i), arr[i], i))
            nxt += 1
        if not ready:
            t = arr[order[nxt]]
            while nxt < n and arr[order[nxt]] <= t:
                i = order[nxt]
                heapq.heappush(ready, (key(i), arr[i], i))
                nxt += 1
        _, _, i = heapq.heappop(ready)
        t += burst[i]
        done[i] = t
    return done


def fcfs(arr, burst, prio):
    return _nonpreemptive(arr, burst, lambda i: 0)


def sjf(arr, burst, prio):
    return _nonpreemptive(arr, burst, lambda i: burst[i])


def priority(arr, burst, prio):
    """Non-preemptive priority; lower number = higher priority."""
    return _nonpreemptive(arr, burst, lambda i: prio[i])


def srtf(arr, burst, prio):
    n = len(arr)
    order = sorted(range(n), key=lambda i: (arr[i], i))
    rem = list(burst)
    done = [0] * n
    t, nxt, ready, finished = 0, 0, [], 0
    while finished < n:
        while nxt < n and arr[order[nxt]] <= t:
            i = order[nxt]
            heapq.heappush(ready, (rem[i], arr[i], i))
            nxt += 1
        if not ready:
            t = arr[order[nxt]]
            continue
        r, a, i = heapq.heappop(ready)
        horizon = arr[order[nxt]] if nxt < n else None
        run = r if horizon is None else min(r, horizon - t)
        t += run
        rem[i] -= run
        if rem[i] == 0:
            done[i] = t
            finished += 1
        else:
            heapq.heappush(ready, (rem[i], a, i))
    return done


def _rr_levels(arr, burst, quanta):
    """Multi-level feedback queue; one level with quantum q is plain Round Robin.
    New arrivals enter level 0 and are queued before a preempted process.
    A process that uses its full quantum drops one level. No priority boost."""
    n = len(arr)
    order = sorted(range(n), key=lambda i: (arr[i], i))
    rem = list(burst)
    done = [0] * n
    queues = [deque() for _ in quanta]
    level = [0] * n
    t, nxt, finished = 0, 0, 0

    def admit(upto):
        nonlocal nxt
        while nxt < n and arr[order[nxt]] <= upto:
            queues[0].append(order[nxt])
            nxt += 1

    while finished < n:
        admit(t)
        lv = next((L for L, q in enumerate(queues) if q), None)
        if lv is None:
            t = arr[order[nxt]]
            continue
        i = queues[lv].popleft()
        run = min(quanta[lv], rem[i])
        t += run
        rem[i] -= run
        admit(t)
        if rem[i] == 0:
            done[i] = t
            finished += 1
        else:
            if run == quanta[lv]:
                level[i] = min(lv + 1, len(quanta) - 1)
            queues[level[i]].append(i)
    return done


def rr(q):
    def f(arr, burst, prio):
        return _rr_levels(arr, burst, [q])
    return f


def mlfq(arr, burst, prio):
    return _rr_levels(arr, burst, [2, 4, 8])


POLICIES = {
    "FCFS": fcfs,
    "SJF": sjf,
    "Priority": priority,
    "SRTF": srtf,
    "RR-q2": rr(2),
    "RR-q8": rr(8),
    "MLFQ": mlfq,
}


def turnaround(policy, arr, burst, prio):
    done = POLICIES[policy](arr, burst, prio)
    return [d - a for d, a in zip(done, arr)]


def features(arr, burst, max_arrival):
    b = np.asarray(burst, dtype=float)
    a = np.asarray(arr, dtype=float)
    span = (a.max() - a.min()) / max_arrival if max_arrival else 0.0
    gaps = np.diff(np.sort(a))
    load = b.sum() / max(1.0, a.max() - a.min() + b.mean())
    return {
        "burst_cv": float(b.std() / b.mean()),
        "arrival_span": float(span),
        "arrival_clustering": float((gaps == 0).mean()) if len(gaps) else 0.0,
        "offered_load": float(load),
        "longest_burst_share": float(b.max() / b.sum()),
    }


def make_problem(target="FCFS", n_procs=16, max_arrival=100, max_burst=40, n_prio=5,
                 metric="mean") -> Problem:
    """metric='mean': mean turnaround of target / mean turnaround of SRTF (optimal).
    metric='max':  max turnaround of target / max turnaround of FCFS (optimal)."""
    space = RowGenome(n_procs, [(0, max_arrival), (1, max_burst), (0, n_prio - 1)])
    ref_policy = "SRTF" if metric == "mean" else "FCFS"
    agg = (lambda x: sum(x) / len(x)) if metric == "mean" else max

    def fn(g):
        arr, burst, prio = g[:, 0].tolist(), g[:, 1].tolist(), g[:, 2].tolist()
        ta = agg(turnaround(target, arr, burst, prio))
        tr = agg(turnaround(ref_policy, arr, burst, prio))
        feats = features(arr, burst, max_arrival)
        desc = (min(1.0, feats["burst_cv"] / 1.5), feats["arrival_span"])
        info = {"target_cost": ta, "ref_cost": tr, **feats}
        return ta / tr, desc, info

    return Problem(f"cpu-{metric}-{target}", "cpu", space, fn,
                   ("burst variability (CV)", "arrival spread"),
                   {"target": target, "metric": metric, "reference": ref_policy,
                    "n_procs": n_procs})
