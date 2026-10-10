"""Simulators checked against textbook examples and brute force."""
import itertools
import random

from momus.domains import cpu, disk, memory, paging

BELADY = [1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5]


def test_belady_classic_string():
    # Silberschatz: FIFO gives 9 faults with 3 frames and 10 with 4 frames
    assert paging.faults_fifo(BELADY, 3) == 9
    assert paging.faults_fifo(BELADY, 4) == 10


def test_silberschatz_reference_string():
    ref = [7, 0, 1, 2, 0, 3, 0, 4, 2, 3, 0, 3, 2, 1, 2, 0, 1, 7, 0, 1]
    assert paging.faults_fifo(ref, 3) == 15
    assert paging.faults_lru(ref, 3) == 12
    assert paging.faults_opt(ref, 3) == 9


def _brute_opt(ref, k):
    """Exhaustive search over eviction choices (small inputs only)."""
    best = [None]

    def go(i, cache, faults):
        if best[0] is not None and faults >= best[0]:
            return
        if i == len(ref):
            best[0] = faults
            return
        p = ref[i]
        if p in cache:
            go(i + 1, cache, faults)
        elif len(cache) < k:
            go(i + 1, cache | {p}, faults + 1)
        else:
            for v in cache:
                go(i + 1, (cache - {v}) | {p}, faults + 1)
    go(0, frozenset(), 0)
    return best[0]


def test_opt_matches_brute_force():
    rng = random.Random(0)
    for _ in range(200):
        ref = [rng.randrange(5) for _ in range(12)]
        k = rng.randint(1, 4)
        assert paging.faults_opt(ref, k) == _brute_opt(ref, k)
        for f in (paging.faults_fifo, paging.faults_lru, paging.faults_clock, paging.faults_lfu):
            assert f(ref, k) >= paging.faults_opt(ref, k)


def test_cpu_textbook_example():
    # Silberschatz: bursts 24, 3, 3 all at t=0. FCFS avg wait 17, SJF avg wait 3
    arr, burst, prio = [0, 0, 0], [24, 3, 3], [0, 0, 0]
    wait = lambda pol: sum(t - b for t, b in zip(cpu.turnaround(pol, arr, burst, prio), burst)) / 3
    assert wait("FCFS") == 17
    assert wait("SJF") == 3
    # RR q=4 on the same: P1 waits 6, P2 4, P3 7 -> 17/3
    assert abs(wait_rr4(arr, burst) - 17 / 3) < 1e-9


def wait_rr4(arr, burst):
    done = cpu.rr(4)(arr, burst, [0] * len(arr))
    return sum(d - a - b for d, a, b in zip(done, arr, burst)) / len(arr)


def test_srtf_example():
    # Silberschatz SRTF example: arrivals 0,1,2,3 bursts 8,4,9,5 -> avg wait 6.5
    arr, burst = [0, 1, 2, 3], [8, 4, 9, 5]
    ta = cpu.turnaround("SRTF", arr, burst, [0] * 4)
    assert sum(t - b for t, b in zip(ta, burst)) / 4 == 6.5


def _brute_mean_turnaround_nonpreemptive(arr, burst):
    best = None
    for perm in itertools.permutations(range(len(arr))):
        t, tot = 0, 0
        for i in perm:
            t = max(t, arr[i]) + burst[i]
            tot += t - arr[i]
        best = tot if best is None else min(best, tot)
    return best / len(arr)


def test_srtf_beats_every_nonpreemptive_order_and_fcfs_minimises_max():
    rng = random.Random(1)
    for _ in range(150):
        n = rng.randint(2, 6)
        arr = [rng.randint(0, 10) for _ in range(n)]
        burst = [rng.randint(1, 8) for _ in range(n)]
        prio = [rng.randint(0, 2) for _ in range(n)]
        mean = lambda pol: sum(cpu.turnaround(pol, arr, burst, prio)) / n
        assert mean("SRTF") <= _brute_mean_turnaround_nonpreemptive(arr, burst) + 1e-9
        for pol in cpu.POLICIES:
            assert mean(pol) >= mean("SRTF") - 1e-9
            assert max(cpu.turnaround(pol, arr, burst, prio)) >= max(cpu.turnaround("FCFS", arr, burst, prio))
            # every process finishes and receives exactly its burst
            assert all(t >= b for t, b in zip(cpu.turnaround(pol, arr, burst, prio), burst))


def test_disk_textbook_example():
    # Silberschatz queue 98,183,37,122,14,124,65,67 head at 53
    q = [98, 183, 37, 122, 14, 124, 65, 67]
    z = [0] * len(q)
    assert disk.simulate("FCFS", z, q, 200, 53)[0] == 640
    assert disk.simulate("SSTF", z, q, 200, 53)[0] == 236
    # head at 53 moving up: LOOK goes up to 183 then down to 14
    assert disk.simulate("LOOK", z, q, 200, 53)[0] == (183 - 53) + (183 - 14)
    assert disk.optimal_seek(q, 53) == 208  # down to 14 first, then up to 183


def _brute_seek(cyls, head):
    best = None
    for perm in itertools.permutations(cyls):
        pos, tot = head, 0
        for c in perm:
            tot += abs(c - pos)
            pos = c
        best = tot if best is None else min(best, tot)
    return best


def test_optimal_seek_brute_force():
    rng = random.Random(2)
    for _ in range(100):
        cyls = [rng.randrange(50) for _ in range(rng.randint(1, 6))]
        head = rng.randrange(50)
        assert disk.optimal_seek(cyls, head) == _brute_seek(cyls, head)
        for pol in disk.POLICIES:
            assert disk.simulate(pol, [0] * len(cyls), cyls, 50, head)[0] >= disk.optimal_seek(cyls, head)


def test_memory_invariants():
    rng = random.Random(3)
    for pol in memory.POLICIES:
        for _ in range(50):
            ops = [(rng.randint(0, 1), rng.randint(1, 64), rng.randint(0, 9999)) for _ in range(80)]
            foot, live, _ = memory.run(pol, ops)
            assert foot >= live


def test_memory_no_overlap():
    """Allocated blocks never overlap, for every allocator."""
    rng = random.Random(4)
    for pol in memory.POLICIES:
        heap = memory.BuddyHeap() if pol == "buddy" else memory.FreeListHeap(pol)
        live = []
        for _ in range(400):
            if live and rng.random() < 0.45:
                a, s = live.pop(rng.randrange(len(live)))
                heap.free(a, s)
            else:
                s = rng.randint(1, 64)
                live.append((heap.malloc(s), s))
            spans = sorted(live)
            for (a1, s1), (a2, _) in zip(spans, spans[1:]):
                assert a1 + s1 <= a2, pol


def test_first_fit_reuses_hole():
    h = memory.FreeListHeap("first")
    a = h.malloc(10); b = h.malloc(10); h.malloc(10)
    h.free(a, 10)
    assert h.malloc(5) == a
    h.free(b, 10)
