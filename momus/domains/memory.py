"""Dynamic memory allocation: first fit, next fit, best fit, worst fit, buddy.

A workload is a sequence of M operations. Each row is (kind, size, pick):
kind 1 = malloc(size), kind 0 = free one live block chosen by pick.
A free with nothing live is a no-op, so every genome is a valid program.

The heap grows upward from address 0 and never compacts. Footprint is the
highest address ever in use. The reference is an ideal compacting allocator
whose footprint equals the peak number of live bytes requested, so
fitness = peak footprint / peak live bytes >= 1. The gap is fragmentation
(external for the fit policies, internal plus external for buddy).
"""
from __future__ import annotations

import bisect

import numpy as np

from ..genome import RowGenome
from ..problem import Problem


class FreeListHeap:
    """Address-ordered free list with coalescing; holes at the top shrink the heap."""

    def __init__(self, policy):
        self.policy = policy
        self.holes = []  # sorted list of [start, size]
        self.top = 0
        self.peak = 0
        self.rover = 0  # next-fit position (address)

    def malloc(self, size):
        holes = self.holes
        idx = None
        if self.policy == "first":
            for k, (s, z) in enumerate(holes):
                if z >= size:
                    idx = k
                    break
        elif self.policy == "next":
            n = len(holes)
            if n:
                start = bisect.bisect_left(holes, [self.rover, -1])
                for off in range(n):
                    k = (start + off) % n
                    if holes[k][1] >= size:
                        idx = k
                        break
        elif self.policy == "best":
            best = None
            for k, (s, z) in enumerate(holes):
                if z >= size and (best is None or z < best):
                    best, idx = z, k
        elif self.policy == "worst":
            worst = None
            for k, (s, z) in enumerate(holes):
                if z >= size and (worst is None or z > worst):
                    worst, idx = z, k
        else:
            raise ValueError(self.policy)
        if idx is None:
            addr = self.top
            self.top += size
            self.peak = max(self.peak, self.top)
        else:
            s, z = holes[idx]
            addr = s
            if z == size:
                holes.pop(idx)
            else:
                holes[idx] = [s + size, z - size]
        self.rover = addr + size
        return addr

    def free(self, addr, size):
        holes = self.holes
        k = bisect.bisect_left(holes, [addr, -1])
        holes.insert(k, [addr, size])
        # merge with next
        if k + 1 < len(holes) and holes[k][0] + holes[k][1] == holes[k + 1][0]:
            holes[k][1] += holes[k + 1][1]
            holes.pop(k + 1)
        # merge with previous
        if k > 0 and holes[k - 1][0] + holes[k - 1][1] == holes[k][0]:
            holes[k - 1][1] += holes[k][1]
            holes.pop(k)
            k -= 1
        # a hole touching the top gives memory back
        if holes and holes[-1][0] + holes[-1][1] == self.top:
            self.top = holes[-1][0]
            holes.pop()


class BuddyHeap:
    """Binary buddy allocator over a large power-of-two arena.
    Requests are rounded up to a power of two; the lowest-address free block
    of the smallest sufficient order is used, which keeps the footprint low."""

    def __init__(self, max_order=20):
        self.max_order = max_order
        self.free_lists = [set() for _ in range(max_order + 1)]
        self.free_lists[max_order].add(0)
        self.peak = 0
        self.live = {}  # addr -> order
        self.ends = []  # sorted block end addresses currently in use

    def malloc(self, size):
        order = max(0, (size - 1).bit_length())
        o = order
        while o <= self.max_order and not self.free_lists[o]:
            o += 1
        if o > self.max_order:
            raise MemoryError
        addr = min(self.free_lists[o])
        self.free_lists[o].remove(addr)
        while o > order:
            o -= 1
            self.free_lists[o].add(addr + (1 << o))
        self.live[addr] = order
        end = addr + (1 << order)
        bisect.insort(self.ends, end)
        self.peak = max(self.peak, end)
        return addr

    def free(self, addr, size):
        order = self.live.pop(addr)
        self.ends.remove(addr + (1 << order))
        while order < self.max_order:
            buddy = addr ^ (1 << order)
            if buddy in self.free_lists[order]:
                self.free_lists[order].remove(buddy)
                addr = min(addr, buddy)
                order += 1
            else:
                break
        self.free_lists[order].add(addr)


POLICIES = ["first", "next", "best", "worst", "buddy"]


def run(policy, ops):
    """Execute ops = list of (kind, size, pick). Returns (peak footprint, peak live, info)."""
    heap = BuddyHeap() if policy == "buddy" else FreeListHeap(policy)
    live = []  # list of (addr, size)
    live_bytes = peak_live = 0
    n_alloc = 0
    for kind, size, pick in ops:
        if kind == 1:
            addr = heap.malloc(size)
            live.append((addr, size))
            live_bytes += size
            peak_live = max(peak_live, live_bytes)
            n_alloc += 1
        elif live:
            addr, sz = live.pop(pick % len(live))
            heap.free(addr, sz)
            live_bytes -= sz
    return heap.peak, peak_live, {"n_alloc": n_alloc}


def features(ops, max_size):
    kinds = np.array([o[0] for o in ops])
    sizes = np.array([o[1] for o in ops if o[0] == 1] or [0], dtype=float)
    return {
        "alloc_frac": float(kinds.mean()),
        "mean_size": float(sizes.mean() / max_size),
        "size_cv": float(sizes.std() / sizes.mean()) if sizes.mean() > 0 else 0.0,
        "size_log_range": float(np.log2(sizes.max() / max(1.0, sizes.min()))) if sizes.max() > 0 else 0.0,
    }


def make_problem(target="first", n_ops=120, max_size=64) -> Problem:
    space = RowGenome(n_ops, [(0, 1), (1, max_size), (0, 9999)])

    def fn(g):
        ops = [tuple(r) for r in g.tolist()]
        foot, peak_live, info = run(target, ops)
        feats = features(ops, max_size)
        if peak_live == 0:
            return 1.0, (feats["alloc_frac"], feats["mean_size"]), {"target_cost": 0, "ref_cost": 0, **feats}
        fit = foot / peak_live
        info.update({"target_cost": foot, "ref_cost": peak_live, **feats})
        return fit, (feats["alloc_frac"], feats["mean_size"]), info

    return Problem(f"memory-{target}", "memory", space, fn, ("share of mallocs", "mean request size"),
                   {"target": target, "reference": "ideal (peak live bytes)", "max_size": max_size})
