"""Every experiment configuration in one place.

A config is (domain, make_problem kwargs). Problems are rebuilt inside each
worker process from this spec, so the specs must stay plain data.
"""
from momus.domains import cpu, disk, memory, paging

BUILDERS = {
    "paging": paging.make_problem,
    "cpu": cpu.make_problem,
    "disk": disk.make_problem,
    "memory": memory.make_problem,
}

METHODS = ["random", "hillclimb", "ga", "mapelites"]


def build(spec):
    domain, kwargs = spec
    return BUILDERS[domain](**kwargs)


# Main study: every algorithm, every search method.
MAIN = (
    [("paging", {"target": t, "k": 4}) for t in ["FIFO", "LRU", "Clock", "LFU"]]
    + [("cpu", {"target": t, "metric": "mean"}) for t in ["FCFS", "SJF", "Priority", "RR-q2", "RR-q8", "MLFQ"]]
    + [("cpu", {"target": t, "metric": "max"}) for t in ["SJF", "Priority", "SRTF", "RR-q2", "RR-q8", "MLFQ"]]
    + [("disk", {"target": t, "mode": "seek"}) for t in ["FCFS", "SSTF", "SCAN", "C-SCAN", "LOOK", "C-LOOK"]]
    + [("disk", {"target": t, "mode": "wait"}) for t in ["SSTF", "SCAN", "C-SCAN", "LOOK", "C-LOOK"]]
    + [("memory", {"target": t}) for t in ["first", "next", "best", "worst", "buddy"]]
)

# Rediscovery of Belady's anomaly (FIFO with k=3 vs k+1=4 frames).
BELADY = [
    ("paging", {"mode": "belady", "k": 3, "n_pages": 6, "length": 24}),
    ("paging", {"mode": "belady", "k": 3, "n_pages": 8, "length": 64}),
]

# Bound tightness: competitive ratio against OPT as the cache grows.
BOUND = [("paging", {"target": t, "k": k, "n_pages": k + 4, "length": 64})
         for t in ["FIFO", "LRU", "Clock"] for k in [2, 3, 4, 5, 6]]
BOUND_METHODS = ["hillclimb", "ga"]
