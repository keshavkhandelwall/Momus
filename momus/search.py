"""Search strategies, all on a fixed budget of fitness evaluations.

* random      - sample fresh random workloads
* hillclimb   - (1+1) evolutionary algorithm: mutate the incumbent, keep if not worse
* ga          - generational genetic algorithm, tournament selection, elitism
* mapelites   - MAP-Elites: keep the worst-case workload in each cell of a
                2-D grid of workload descriptors (quality-diversity search)
"""
from __future__ import annotations

import numpy as np

from .problem import Problem


class Tracker:
    """Counts evaluations and records the best-so-far curve."""

    def __init__(self, problem: Problem, budget: int, threshold=None, n_points=100):
        self.p = problem
        self.budget = budget
        self.used = 0
        self.best_fit = -np.inf
        self.best_g = None
        self.best_info = None
        self.threshold = threshold
        self.first_hit = None
        self.checkpoints = np.unique(np.linspace(1, budget, n_points).astype(int))
        self.curve = []
        self._ci = 0

    def done(self):
        return self.used >= self.budget

    def eval(self, g):
        fit, desc, info = self.p.evaluate(g)
        self.used += 1
        if fit > self.best_fit:
            self.best_fit, self.best_g, self.best_info = fit, g.copy(), info
        if self.threshold is not None and self.first_hit is None and fit > self.threshold:
            self.first_hit = self.used
        while self._ci < len(self.checkpoints) and self.used >= self.checkpoints[self._ci]:
            self.curve.append(self.best_fit)
            self._ci += 1
        return fit, desc, info

    def result(self, **extra):
        return {
            "best_fit": float(self.best_fit),
            "best_genome": self.best_g.tolist(),
            "best_info": self.best_info,
            "curve": [float(c) for c in self.curve],
            "checkpoints": self.checkpoints.tolist(),
            "first_hit": self.first_hit,
            "evals": self.used,
            **extra,
        }


def random_search(p: Problem, budget, rng, threshold=None):
    tr = Tracker(p, budget, threshold)
    while not tr.done():
        tr.eval(p.space.random(rng))
    return tr.result()


def hillclimb(p: Problem, budget, rng, threshold=None, restart_after=500):
    """(1+1)-EA with restarts after `restart_after` evaluations without improvement."""
    tr = Tracker(p, budget, threshold)
    cur = p.space.random(rng)
    cur_fit, _, _ = tr.eval(cur)
    stale = 0
    while not tr.done():
        child = p.space.mutate(cur, rng)
        f, _, _ = tr.eval(child)
        if f >= cur_fit:
            stale = 0 if f > cur_fit else stale + 1
            cur, cur_fit = child, f
        else:
            stale += 1
        if stale >= restart_after and not tr.done():
            cur = p.space.random(rng)
            cur_fit, _, _ = tr.eval(cur)
            stale = 0
    return tr.result()


def ga(p: Problem, budget, rng, threshold=None, pop_size=50, tournament=3,
       p_cx=0.7, elites=2):
    tr = Tracker(p, budget, threshold)
    pop = [p.space.random(rng) for _ in range(pop_size)]
    fits = []
    for g in pop:
        if tr.done():
            break
        fits.append(tr.eval(g)[0])
    pop = pop[:len(fits)]

    def pick():
        idx = rng.integers(len(pop), size=tournament)
        return pop[max(idx, key=lambda i: fits[i])]

    while not tr.done():
        order = np.argsort(fits)[::-1]
        new_pop = [pop[i] for i in order[:elites]]
        new_fits = [fits[i] for i in order[:elites]]
        while len(new_pop) < pop_size and not tr.done():
            a = pick()
            child = p.space.crossover(a, pick(), rng) if rng.random() < p_cx else a
            child = p.space.mutate(child, rng)
            new_pop.append(child)
            new_fits.append(tr.eval(child)[0])
        pop, fits = new_pop, new_fits
    return tr.result()


def mapelites(p: Problem, budget, rng, threshold=None, bins=10, n_init=200, p_cx=0.3):
    tr = Tracker(p, budget, threshold)
    fit_grid = np.full((bins, bins), np.nan)
    archive = {}

    def cell(desc):
        return tuple(min(bins - 1, max(0, int(d * bins))) for d in desc)

    def insert(g, f, desc):
        c = cell(desc)
        if np.isnan(fit_grid[c]) or f > fit_grid[c]:
            fit_grid[c] = f
            archive[c] = g

    while not tr.done():
        if len(archive) == 0 or tr.used < n_init:
            g = p.space.random(rng)
        else:
            keys = list(archive)
            parent = archive[keys[rng.integers(len(keys))]]
            if rng.random() < p_cx:
                other = archive[keys[rng.integers(len(keys))]]
                parent = p.space.crossover(parent, other, rng)
            g = p.space.mutate(parent, rng)
        f, desc, _ = tr.eval(g)
        insert(g, f, desc)
    filled = ~np.isnan(fit_grid)
    return tr.result(
        archive_grid=np.where(filled, fit_grid, None).tolist(),
        coverage=float(filled.mean()),
        qd_score=float(np.nansum(fit_grid - 1.0)),  # fitness above the "as good as reference" floor of 1
    )


METHODS = {
    "random": random_search,
    "hillclimb": hillclimb,
    "ga": ga,
    "mapelites": mapelites,
}
