"""Page replacement: FIFO, LRU, Clock, LFU against Belady's OPT (MIN).

A workload is a reference string over P pages; the cache holds k frames.
Every policy counts page faults, including compulsory (cold) faults.
"""
from __future__ import annotations

from collections import OrderedDict, deque

import numpy as np

from ..genome import RowGenome
from ..problem import Problem


def faults_fifo(ref, k):
    frames, order, faults = set(), deque(), 0
    for p in ref:
        if p in frames:
            continue
        faults += 1
        if len(frames) == k:
            frames.discard(order.popleft())
        frames.add(p)
        order.append(p)
    return faults


def faults_lru(ref, k):
    cache, faults = OrderedDict(), 0
    for p in ref:
        if p in cache:
            cache.move_to_end(p)
            continue
        faults += 1
        if len(cache) == k:
            cache.popitem(last=False)
        cache[p] = True
    return faults


def faults_clock(ref, k):
    """Second-chance clock: a hit sets the use bit; the hand clears bits until it finds 0."""
    frames = [None] * k
    used = [0] * k
    where = {}
    hand, faults = 0, 0
    for p in ref:
        slot = where.get(p)
        if slot is not None:
            used[slot] = 1
            continue
        faults += 1
        while used[hand]:
            used[hand] = 0
            hand = (hand + 1) % k
        old = frames[hand]
        if old is not None:
            del where[old]
        frames[hand] = p
        used[hand] = 1
        where[p] = hand
        hand = (hand + 1) % k
    return faults


def faults_lfu(ref, k):
    """In-cache LFU: evict the resident page with the fewest hits since it was loaded,
    breaking ties by least recent use. Counts reset on eviction."""
    count, last, faults = {}, {}, 0
    for t, p in enumerate(ref):
        if p in count:
            count[p] += 1
            last[p] = t
            continue
        faults += 1
        if len(count) == k:
            victim = min(count, key=lambda q: (count[q], last[q]))
            del count[victim]
            del last[victim]
        count[p] = 1
        last[p] = t
    return faults


def faults_opt(ref, k):
    """Belady's MIN: evict the resident page whose next use is furthest away."""
    n = len(ref)
    nxt = [0] * n
    seen = {}
    for i in range(n - 1, -1, -1):
        nxt[i] = seen.get(ref[i], n + i)  # never used again: distinct "infinity"
        seen[ref[i]] = i
    resident = {}  # page -> next use index
    faults = 0
    for i, p in enumerate(ref):
        if p in resident:
            resident[p] = nxt[i]
            continue
        faults += 1
        if len(resident) == k:
            victim = max(resident, key=resident.get)
            del resident[victim]
        resident[p] = nxt[i]
    return faults


POLICIES = {
    "FIFO": faults_fifo,
    "LRU": faults_lru,
    "Clock": faults_clock,
    "LFU": faults_lfu,
    "OPT": faults_opt,
}


def features(ref, k, n_pages):
    """Workload features used for MAP-Elites descriptors and for explanation."""
    n = len(ref)
    distinct = len(set(ref))
    last, dists, cold = {}, [], 0
    for i, p in enumerate(ref):
        if p in last:
            # reuse distance = number of distinct pages touched since the last use
            dists.append(len(set(ref[last[p] + 1:i])))
        else:
            cold += 1
        last[p] = i
    within_k = sum(1 for d in dists if d < k) / n
    mean_rd = float(np.mean(dists)) if dists else float(n_pages)
    return {
        "distinct_frac": distinct / n_pages,
        "locality": within_k,  # share of references a k-frame LRU would hit
        "mean_reuse_distance": mean_rd,
        "cold_frac": cold / n,
    }


def make_problem(target="LRU", k=4, n_pages=8, length=64, mode="ratio") -> Problem:
    """mode='ratio': faults_target / faults_OPT.
    mode='belady': faults_FIFO(k+1) - faults_FIFO(k); positive = Belady's anomaly."""
    space = RowGenome(length, [(0, n_pages - 1)])
    f_target = POLICIES[target]

    def fn(g):
        ref = g[:, 0].tolist()
        feats = features(ref, k, n_pages)
        if mode == "belady":
            a, b = faults_fifo(ref, k), faults_fifo(ref, k + 1)
            fit = float(b - a)
            info = {"faults_k": a, "faults_k1": b, "anomaly_ratio": b / a}
        else:
            fa, fo = f_target(ref, k), faults_opt(ref, k)
            fit = fa / fo
            info = {"faults": fa, "faults_opt": fo}
        desc = (feats["distinct_frac"], feats["locality"])
        info.update(feats)
        return fit, desc, info

    name = f"paging-{'belady' if mode == 'belady' else target}-k{k}"
    return Problem(name, "paging", space, fn, ("distinct pages used", "locality (LRU hit share)"),
                   {"target": target, "k": k, "n_pages": n_pages, "length": length, "mode": mode,
                    "reference": "FIFO(k)" if mode == "belady" else "OPT"})
