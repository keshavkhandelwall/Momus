"""Row-based genome shared by every domain.

A genome is an integer matrix of shape (rows, cols). Each column has an
inclusive [lo, hi] range. Rows are the natural unit of a workload: one page
reference, one process, one disk request, one allocator operation.

All operators keep genomes inside their bounds, so repair is a clamp.
"""
from __future__ import annotations

import numpy as np


class RowGenome:
    def __init__(self, rows: int, bounds: list[tuple[int, int]]):
        self.rows = rows
        self.bounds = bounds
        self.lo = np.array([b[0] for b in bounds], dtype=np.int64)
        self.hi = np.array([b[1] for b in bounds], dtype=np.int64)

    # ------------------------------------------------------------------ init
    def random(self, rng: np.random.Generator) -> np.ndarray:
        return rng.integers(self.lo, self.hi + 1, size=(self.rows, len(self.bounds)))

    def repair(self, g: np.ndarray) -> np.ndarray:
        return np.clip(g, self.lo, self.hi)

    # -------------------------------------------------------------- mutation
    def mutate(self, g: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        """Apply 1 + Poisson(0.5) randomly chosen edits."""
        g = g.copy()
        n_ops = 1 + rng.poisson(0.5)
        for _ in range(n_ops):
            op = rng.integers(6)
            if op == 0:
                self._point_reset(g, rng)
            elif op == 1:
                self._creep(g, rng)
            elif op == 2:
                self._swap_rows(g, rng)
            elif op == 3:
                self._segment_copy(g, rng)
            elif op == 4:
                self._segment_reverse(g, rng)
            else:
                self._insert_delete(g, rng)
        return self.repair(g)

    def _point_reset(self, g, rng):
        r = rng.integers(self.rows)
        c = rng.integers(g.shape[1])
        g[r, c] = rng.integers(self.lo[c], self.hi[c] + 1)

    def _creep(self, g, rng):
        r = rng.integers(self.rows)
        c = rng.integers(g.shape[1])
        span = max(1, int(0.1 * (self.hi[c] - self.lo[c])))
        g[r, c] += rng.integers(-span, span + 1)

    def _swap_rows(self, g, rng):
        i, j = rng.integers(self.rows, size=2)
        g[[i, j]] = g[[j, i]]

    def _segment(self, rng):
        length = rng.integers(2, max(3, self.rows // 4) + 1)
        start = rng.integers(0, self.rows - length + 1)
        return start, length

    def _segment_copy(self, g, rng):
        """Copy a run of rows elsewhere: creates loops, scans, repeated bursts."""
        start, length = self._segment(rng)
        dest = rng.integers(0, self.rows - length + 1)
        g[dest:dest + length] = g[start:start + length].copy()

    def _segment_reverse(self, g, rng):
        start, length = self._segment(rng)
        g[start:start + length] = g[start:start + length][::-1].copy()

    def _insert_delete(self, g, rng):
        """Insert a random row at i (dropping the last) or delete row i (duplicating the last)."""
        i = rng.integers(self.rows)
        if rng.random() < 0.5:
            g[i + 1:] = g[i:-1].copy()
            g[i] = rng.integers(self.lo, self.hi + 1)
        else:
            g[i:-1] = g[i + 1:].copy()

    # ------------------------------------------------------------- crossover
    def crossover(self, a: np.ndarray, b: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        """Two-point crossover on rows."""
        i, j = sorted(rng.integers(0, self.rows + 1, size=2))
        child = a.copy()
        child[i:j] = b[i:j]
        return child
