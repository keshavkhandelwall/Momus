"""Run every experiment and append one JSON line per run to results/runs.jsonl.

    python -m experiments.run_all               # full study
    python -m experiments.run_all --quick       # smoke test (tiny budget)

Runs already present in the output file are skipped, so the script can be
stopped and restarted.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import zlib
from multiprocessing import Pool

import numpy as np

from momus import search
from experiments import configs


def job_key(group, spec, method, seed):
    return json.dumps([group, spec, method, seed], sort_keys=True)


def run_job(args):
    group, spec, method, seed, budget = args
    problem = configs.build(spec)
    threshold = 0 if spec[1].get("mode") == "belady" else None
    rng = np.random.default_rng([seed, zlib.crc32(method.encode()), zlib.crc32(problem.name.encode())])
    t0 = time.time()
    res = search.METHODS[method](problem, budget, rng, threshold=threshold)
    res.update({
        "key": job_key(group, spec, method, seed),
        "group": group, "problem": problem.name, "domain": problem.domain,
        "meta": problem.meta, "descriptors": problem.descriptor_names,
        "method": method, "seed": seed, "budget": budget, "seconds": time.time() - t0,
    })
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--budget", type=int, default=10_000)
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    ap.add_argument("--out", default="results/runs.jsonl")
    a = ap.parse_args()
    if a.quick:
        a.budget, a.seeds, a.out = 300, 2, "results/quick.jsonl"

    jobs = []
    for spec in configs.MAIN:
        jobs += [("main", spec, m, s, a.budget) for m in configs.METHODS for s in range(a.seeds)]
    for spec in configs.BELADY:
        jobs += [("belady", spec, m, s, a.budget) for m in configs.METHODS for s in range(a.seeds)]
    for spec in configs.BOUND:
        jobs += [("bound", spec, m, s, a.budget) for m in configs.BOUND_METHODS for s in range(min(10, a.seeds))]

    done = set()
    if os.path.exists(a.out):
        with open(a.out) as f:
            for line in f:
                done.add(json.loads(line)["key"])
    todo = [j for j in jobs if job_key(*j[:4]) not in done]
    print(f"{len(jobs)} jobs, {len(done)} done, {len(todo)} to run", flush=True)

    t0 = time.time()
    with Pool(a.workers) as pool, open(a.out, "a") as out:
        for i, res in enumerate(pool.imap_unordered(run_job, todo, chunksize=2), 1):
            out.write(json.dumps(res) + "\n")
            out.flush()
            if i % 50 == 0 or i == len(todo):
                el = time.time() - t0
                print(f"{i}/{len(todo)} runs, {el/60:.1f} min, eta {el/i*(len(todo)-i)/60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
