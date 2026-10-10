# Momus, explained from the basics

This guide assumes you know what an operating system is and not much more. Read it top to bottom once and you will be able to explain every part of the project, answer viva or interview questions about it, and run it yourself.

## 1. The one-paragraph idea

Operating systems make the same small decisions millions of times a second: which process gets the CPU next, which page to throw out of memory, which disk request to serve next, where to put a new block of memory. Each decision is made by a simple rule (an *algorithm* or *policy*) such as "first come, first served" or "evict the least recently used page". Textbooks tell you these rules are good *on average* and give a few hand-made examples where they behave badly. **Momus automatically searches for the inputs that make each rule behave as badly as possible**, using evolution (mutate, select, repeat). The name comes from Momus, the Greek god of criticism and mockery: the framework's job is to find fault.

## 2. The four OS problems we attack

### 2.1 CPU scheduling

Several processes want the single CPU. Each process has an **arrival time** (when it shows up), a **burst** (how much CPU time it needs) and sometimes a **priority**.

| Policy | Rule | Known weakness |
| --- | --- | --- |
| FCFS (first come, first served) | Run processes in arrival order, each to completion | **Convoy effect**: one long job arriving first makes many short jobs wait |
| SJF (shortest job first) | When the CPU is free, pick the shortest waiting job | **Starvation**: a long job can wait forever if short ones keep arriving |
| Priority | Pick the most important waiting job | Starvation of low-priority jobs |
| SRTF (shortest remaining time first) | Like SJF, but a newly arrived shorter job can interrupt (preempt) the running one | Same starvation risk |
| Round Robin, quantum q | Everyone takes turns for q time units | Small q: lots of switching; large q: behaves like FCFS |
| MLFQ (multi-level feedback queue) | Several queues; jobs that use their full time slice drop to a lower queue | Long jobs can starve; can be "gamed" |

How we measure: **turnaround time** = finish time − arrival time. We look at the **mean** (average experience) and the **maximum** (the unluckiest process).

Why the references are fair: it is a proven fact that **SRTF gives the lowest possible mean turnaround** of any scheduler, and **FCFS gives the lowest possible maximum turnaround**. So "FCFS mean turnaround ÷ SRTF mean turnaround = 6" means FCFS was six times worse than the best possible on that exact workload.

### 2.2 Page replacement

Memory holds only **k frames** (slots). Programs touch **pages**; the order of touches is the **reference string**, e.g. `1 2 3 4 1 2 5 1 2 3 4 5`. If a page is not in memory, that is a **page fault** (slow). When memory is full we must evict one page.

| Policy | Evicts |
| --- | --- |
| FIFO | the page that was loaded earliest |
| LRU | the page not used for the longest time |
| Clock (second chance) | a cheap approximation of LRU using one "used" bit per frame |
| LFU | the page used the fewest times since it was loaded |
| OPT (Belady's MIN) | the page whose next use is furthest in the future |

OPT needs to see the future, so a real OS cannot use it, but on a recorded string it is **provably optimal**, which makes it the perfect yardstick. The theory says LRU and FIFO can be at most about **k times** worse than OPT (their *competitive ratio* is k). **Belady's anomaly**: with FIFO, giving the program *more* memory can cause *more* faults. The classic string above gives 9 faults with 3 frames but 10 with 4.

### 2.3 Disk scheduling

A hard disk arm moves across **cylinders** 0 to 199. Requests sit at various cylinders; moving the arm is slow, so we want to minimise **total head movement**.

| Policy | Rule |
| --- | --- |
| FCFS | serve requests in arrival order |
| SSTF | serve the closest request next |
| SCAN (elevator) | sweep in one direction to the edge, then reverse |
| C-SCAN | sweep up to the edge, jump back to 0, sweep up again |
| LOOK / C-LOOK | like SCAN / C-SCAN but turn around at the last request instead of the edge |

When all requests are already waiting, the best possible order is easy to compute: go to the nearer end first, then sweep to the other end. That is our reference. When requests arrive over time we also measure the **longest any request waited**, compared with FCFS (which never makes anyone jump the queue).

### 2.4 Memory allocation

Programs call `malloc(size)` and `free(block)`. The allocator must choose an address for each new block in a heap that only grows.

| Policy | Puts a new block in |
| --- | --- |
| First fit | the first hole that is big enough |
| Next fit | the first big-enough hole after the last allocation |
| Best fit | the smallest hole that is big enough |
| Worst fit | the largest hole |
| Buddy | rounds every request up to a power of two and splits/merges blocks in pairs ("buddies") |

Freed blocks leave **holes**. If holes are too small or in the wrong place, the heap must grow even though there is enough free memory in total: that is **fragmentation**. Our yardstick is a perfect allocator that could always pack live data tightly, so its footprint equals the peak amount of live data. Ratio 2 means the real allocator needed twice the memory.

## 3. How the search works

### 3.1 The "genome"

Evolutionary algorithms work on a **genome**: a description of one candidate. In Momus a genome is simply **one workload**, stored as a table of integers:

| Domain | One row of the table | Rows |
| --- | --- | --- |
| Paging | a page number | 64 references |
| CPU | (arrival, burst, priority) | 16 processes |
| Disk | (arrival, cylinder) | 24 requests |
| Memory | (malloc or free, size, which block to free) | 120 operations |

Every value is kept inside a valid range, so the search can never cheat with impossible inputs (negative bursts, a free of nothing, and so on).

### 3.2 Fitness: "how badly did the algorithm do?"

For each workload we run the algorithm under attack **and** the reference on the same input and divide:

```
fitness = cost of the algorithm / cost of the reference
```

Fitness 1 means "as good as the best possible". Bigger is worse for the algorithm, and the search tries to make it as big as possible. Dividing by the reference matters: a workload that is hard for *everyone* (say, one enormous process) scores about 1, so the search is pushed towards inputs that are bad *specifically for this algorithm*.

### 3.3 The four search methods

1. **Random search**: generate random workloads and keep the worst one. This is the baseline any smarter method must beat.
2. **Hill climbing**: take the current worst workload, change it slightly (mutate), and keep the change if it is at least as bad. Restart from scratch if stuck.
3. **Genetic algorithm (GA)**: keep a population of 50 workloads. Pick parents by small tournaments (the worse workload wins), combine two parents (**crossover**: take rows 1–a from one and the rest from the other), mutate, and repeat. The two worst workloads always survive (**elitism**).
4. **MAP-Elites**: keep a 10 × 10 grid. Each workload is placed in a cell according to two features (for example "how many distinct pages" and "how much locality"). Each cell remembers only its worst workload. Output: not one worst case but a *map* of the worst cases in every kind of workload.

Mutations available: change one value, nudge a value up or down, swap two rows, **copy a block of rows elsewhere** (this creates loops and repeated bursts, which turn out to be what breaks many algorithms), reverse a block, insert or delete a row.

### 3.4 Experimental design in one breath

34 attack targets × 4 methods × 30 independent runs, each run allowed 10,000 fitness evaluations; plus a cache-size sweep for the bound experiment. Comparisons use the median over runs, 95% bootstrap confidence intervals, the Mann-Whitney U test and the Vargha-Delaney A12 effect size (A12 = 0.5: no difference; A12 = 1: method always beats random search).

## 4. How to run it

```bash
pip install numpy scipy matplotlib pytest
python -m pytest -q tests                  # simulators vs textbook answers
python -m experiments.run_all --quick      # 10-second smoke test
python -m experiments.run_all              # full study (~20 min on 4 cores)
python -m experiments.analyze              # tables in results/, figures in figures/
```

Try a single attack in Python:

```python
import numpy as np
from momus.domains import cpu
from momus.search import ga
p = cpu.make_problem("FCFS", metric="mean")     # attack FCFS, compare with SRTF
r = ga(p, budget=5000, rng=np.random.default_rng(0))
print(r["best_fit"])                            # how many times worse than optimal
```

## 5. Where things are

| Path | What it is |
| --- | --- |
| `momus/genome.py` | the workload table and the mutation and crossover operators |
| `momus/domains/*.py` | one simulator file per OS problem, with all policies and the reference |
| `momus/search.py` | random search, hill climbing, GA, MAP-Elites |
| `tests/test_textbook.py` | checks the simulators against textbook answers and brute force |
| `experiments/configs.py` | every experiment in the study |
| `experiments/run_all.py`, `analyze.py` | run the study, build tables and figures |
| `results/` | raw runs and every table |
| `figures/` | every figure used in the paper |
| `paper/` | the write-up |

## 6. Questions you will likely be asked

**Why not just prove the worst case mathematically?** Proofs give bounds for idealised, often infinitely long inputs. They do not tell you how bad things get for a realistic size, or what the bad inputs look like. Momus is the empirical complement, and where a proof exists (LRU's bound of k) we check that the search gets close to it.

**Why evolution and not brute force?** Even 64 page references over 8 pages give 8^64 ≈ 6 × 10^57 possible strings. You cannot try them all.

**Why compare with an optimal reference instead of raw cost?** Raw cost rewards inputs that are hard for every algorithm. The ratio isolates the algorithm's own weakness.

**Is a high ratio a bug in the algorithm?** No. Every online algorithm has bad inputs; the question is how bad, how common, and what they look like. That is what helps choose a policy.

**What are the limits?** Simulators are simplified (no context-switch cost, integer time, one CPU, one disk arm with no rotational delay), workloads are small, and the search is only as good as its budget: it can show a bad case exists, never prove that nothing worse exists.
