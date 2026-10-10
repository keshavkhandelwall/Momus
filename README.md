# Momus

[![tests](https://github.com/keshavkhandelwall/momus/actions/workflows/tests.yml/badge.svg)](https://github.com/keshavkhandelwall/momus/actions/workflows/tests.yml) ![python](https://img.shields.io/badge/python-3.10%2B-blue) ![license](https://img.shields.io/badge/license-MIT-green)

**An evolutionary adversarial framework for empirical worst-case analysis of classical operating system algorithms.**

Momus searches automatically for the workloads that make classical OS policies behave as badly as possible. Each workload is scored by its *empirical competitive ratio*: the policy's cost divided by the cost of a provably optimal (or clearly stated reference) policy on the same input.

New to the topic? Start with [docs/GUIDE.md](docs/GUIDE.md). The full write-up is in [paper/momus_paper.pdf](paper/momus_paper.pdf) (also `.docx`, `.html`, `.md`).

## What it attacks

| Domain | Policies | Reference |
| --- | --- | --- |
| CPU scheduling | FCFS, SJF, Priority, SRTF, Round Robin (q=2, q=8), MLFQ | SRTF (optimal mean turnaround), FCFS (optimal max turnaround) |
| Page replacement | FIFO, LRU, Clock, LFU | Belady's OPT |
| Disk scheduling | FCFS, SSTF, SCAN, C-SCAN, LOOK, C-LOOK | offline optimal sweep; FCFS for max wait |
| Memory allocation | first, next, best, worst fit; buddy | ideal allocator (peak live bytes) |

Search methods: random search, hill climbing, a genetic algorithm, and MAP-Elites.

## Headline results (4,380 runs, 30 seeds per setting)

- All three evolutionary methods beat random search in **32 of 32** settings (A12 >= 0.99, p < 0.05). A restarting hill climber is the strongest single method in 21 of 32.
- The search rediscovers the **FCFS convoy effect**, the **cyclic LRU adversary**, the **LFU stale-frequency trap**, **SCAN/C-SCAN edge travel** and **Belady's anomaly**. It finds the anomaly in 100% of hill-climbing runs, up to 37 vs 25 faults (3 vs 4 frames).
- Worst ratios found: LRU 3.37, LFU 12.0 (vs OPT); FCFS 9.36, RR q=2 3.69 (mean turnaround vs SRTF); LOOK 1.96 vs C-SCAN 199 (seek vs optimum); best fit 2.39 vs buddy 5.22 (memory vs live bytes).

![Worst ratio found per policy](figures/robustness.png)

![Evolved worst cases: FCFS convoy, LRU cyclic adversary, SSTF](figures/gallery.png)

## Quick start

```bash
pip install -r requirements.txt
python -m pytest -q tests                # 11 checks against textbook answers and brute force
python -m experiments.run_all --quick    # smoke test, a few seconds
python -m experiments.run_all            # full study, about 30 minutes on 4 cores
python -m experiments.analyze            # tables -> results/, figures -> figures/
```

```python
import numpy as np
from momus.domains import paging
from momus.search import hillclimb
p = paging.make_problem("LRU", k=4)               # attack LRU with 4 frames, compare with OPT
r = hillclimb(p, budget=5000, rng=np.random.default_rng(0))
print(r["best_fit"], r["best_genome"])            # worst ratio found and the reference string
```

## Layout

```
momus/genome.py          workload matrix + mutation/crossover operators
momus/problem.py         the Problem interface (genome -> fitness, descriptors)
momus/domains/           cpu.py, paging.py, disk.py, memory.py (simulators + references)
momus/search.py          random search, hill climbing, GA, MAP-Elites
experiments/configs.py   every experiment in the study
experiments/run_all.py   runs everything in parallel, resumable
experiments/analyze.py   statistics, tables and figures
tests/                   simulator correctness tests
results/                 runs.jsonl (every run, with its worst workload) and CSV tables
figures/                 all figures in the paper
paper/                   the paper (md, pdf, docx, html)
docs/GUIDE.md            beginner's guide and likely viva questions
```

## Adding a new policy

Add a function to the right file in `momus/domains/`, register it in that file's `POLICIES`, add a line to `experiments/configs.py`, and rerun. To add a new domain, write a `make_problem()` that returns a `Problem` with a `RowGenome` and a fitness function.
