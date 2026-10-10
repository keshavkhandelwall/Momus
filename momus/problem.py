"""The interface every attack target implements.

A Problem bundles a genome space with a fitness function. Fitness is always
"bigger is worse for the algorithm under attack", usually the empirical
competitive ratio cost_A(w) / cost_ref(w) on the same workload w.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from .genome import RowGenome


@dataclass
class Problem:
    name: str
    domain: str
    space: RowGenome
    # genome -> (fitness, (descriptor1, descriptor2), info dict)
    fn: Callable[[np.ndarray], tuple[float, tuple[float, float], dict]]
    descriptor_names: tuple[str, str] = ("d1", "d2")
    meta: dict = field(default_factory=dict)

    def evaluate(self, g: np.ndarray):
        return self.fn(g)
