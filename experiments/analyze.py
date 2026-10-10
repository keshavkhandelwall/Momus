"""Turn results/runs.jsonl into tables (results/*.csv, results/summary.json) and figures/*.png.

    python -m experiments.analyze
"""
from __future__ import annotations

import csv
import json
import os
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from scipy.stats import mannwhitneyu, spearmanr  # noqa: E402

from experiments import configs  # noqa: E402
from momus.domains import cpu, disk, memory, paging  # noqa: E402

RES, FIG = "results", "figures"
METHODS = configs.METHODS
LABEL = {"random": "Random search", "hillclimb": "Hill climbing", "ga": "Genetic algorithm",
         "mapelites": "MAP-Elites"}
# Reference categorical palette, slots 1-4 in fixed order (dataviz skill)
COLOR = {"random": "#2a78d6", "hillclimb": "#eb6834", "ga": "#1baf7a", "mapelites": "#eda100"}
MARK = {"random": "o", "hillclimb": "s", "ga": "^", "mapelites": "D"}
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"

plt.rcParams.update({
    "font.size": 9, "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2,
    "ytick.color": INK2, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 150,
    "savefig.bbox": "tight", "legend.frameon": False, "lines.linewidth": 2,
})


def load(path=f"{RES}/runs.jsonl"):
    with open(path) as f:
        return [json.loads(line) for line in f]


def a12(x, y):
    """Vargha-Delaney A12: probability a value from x beats one from y (0.5 = no difference)."""
    x, y = np.asarray(x), np.asarray(y)
    gt = (x[:, None] > y[None, :]).sum()
    eq = (x[:, None] == y[None, :]).sum()
    return (gt + 0.5 * eq) / (len(x) * len(y))


def boot_ci(x, n=2000, seed=0):
    rng = np.random.default_rng(seed)
    x = np.asarray(x)
    meds = np.median(rng.choice(x, size=(n, len(x))), axis=1)
    return float(np.percentile(meds, 2.5)), float(np.percentile(meds, 97.5))


def write_csv(name, rows):
    if not rows:
        return
    with open(f"{RES}/{name}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


# --------------------------------------------------------------------------- tables
def main_table(runs):
    by = defaultdict(list)
    for r in runs:
        if r["group"] == "main":
            by[(r["problem"], r["method"])].append(r)
    problems = sorted({p for p, _ in by}, key=lambda p: [s["problem"] for s in runs].index(p))
    rows, stats = [], []
    for p in problems:
        vals = {m: [r["best_fit"] for r in by[(p, m)]] for m in METHODS if by[(p, m)]}
        meta = by[(p, METHODS[0])][0]["meta"]
        row = {"problem": p, "domain": p.split("-")[0], "target": meta["target"],
               "reference": meta["reference"]}
        for m, v in vals.items():
            row[f"{m}_median"] = round(float(np.median(v)), 4)
        for m, v in vals.items():
            lo, hi = boot_ci(v)
            row[f"{m}_ci"] = f"[{lo:.3f}, {hi:.3f}]"
        best_m = max(vals, key=lambda m: np.median(vals[m]))
        row["best_method"] = best_m
        row["worst_found"] = round(max(max(v) for v in vals.values()), 4)
        rows.append(row)
        for m in ("hillclimb", "ga", "mapelites"):
            if m in vals:
                pval = mannwhitneyu(vals[m], vals["random"], alternative="two-sided").pvalue
                stats.append({"problem": p, "method": m, "vs": "random",
                              "A12": round(float(a12(vals[m], vals["random"])), 3), "p": float(pval)})
    write_csv("main_results", rows)
    write_csv("method_vs_random", stats)
    return rows, stats, by


def robustness(rows):
    """Rank algorithms in each attack setting by the worst ratio any search found."""
    out = []
    groups = defaultdict(list)
    for r in rows:
        setting = "-".join(r["problem"].split("-")[:2]) if r["domain"] in ("cpu", "disk") else r["domain"]
        groups[setting].append(r)
    for setting, rs in groups.items():
        for rank, r in enumerate(sorted(rs, key=lambda r: r["worst_found"]), 1):
            out.append({"setting": setting, "rank_most_robust": rank, "target": r["target"],
                        "reference": r["reference"], "worst_ratio": r["worst_found"],
                        "best_method": r["best_method"]})
    write_csv("robustness_ranking", out)
    return groups


def belady(runs):
    by = defaultdict(list)
    for r in runs:
        if r["group"] == "belady":
            by[(r["problem"], r["meta"]["length"], r["meta"]["n_pages"], r["method"])].append(r)
    rows, best = [], {}
    for (p, L, P, m), rs in sorted(by.items(), key=lambda kv: (kv[0][1], METHODS.index(kv[0][3]))):
        hits = [r["first_hit"] for r in rs if r["first_hit"] is not None]
        top = max(rs, key=lambda r: (r["best_fit"], r["best_info"]["anomaly_ratio"]))
        rows.append({"length": L, "pages": P, "method": m, "runs": len(rs),
                     "success_rate": round(len(hits) / len(rs), 3),
                     "median_evals_to_first_anomaly": int(np.median(hits)) if hits else None,
                     "median_extra_faults": float(np.median([r["best_fit"] for r in rs])),
                     "max_extra_faults": top["best_fit"],
                     "max_anomaly_ratio": round(top["best_info"]["anomaly_ratio"], 3)})
        key = (L, P)
        if key not in best or top["best_fit"] > best[key]["best_fit"]:
            best[key] = top
    write_csv("belady", rows)
    return rows, best


def cyclic_adversary(k, length, policy):
    """Textbook adversary: cycle through k+1 pages."""
    ref = [i % (k + 1) for i in range(length)]
    return paging.POLICIES[policy](ref, k) / paging.faults_opt(ref, k)


def bound(runs):
    by = defaultdict(list)
    for r in runs:
        if r["group"] == "bound":
            by[(r["meta"]["target"], r["meta"]["k"])].append(r["best_fit"])
    rows = []
    for (t, k), v in sorted(by.items()):
        rows.append({"target": t, "k": k, "evolved_max": round(max(v), 4),
                     "evolved_median": round(float(np.median(v)), 4),
                     "cyclic_adversary": round(cyclic_adversary(k, 64, t), 4),
                     "theoretical_bound_k": k})
    write_csv("bound_tightness", rows)
    return rows


# --------------------------------------------------------------- transfer & features
def setting_of(problem_name):
    parts = problem_name.split("-")
    return "-".join(parts[:2]) if parts[0] in ("cpu", "disk") else parts[0]


def transfer(by):
    """Evaluate each algorithm's single worst workload against every algorithm in the same setting."""
    worst = {}
    for (p, m), rs in by.items():
        top = max(rs, key=lambda r: r["best_fit"])
        if p not in worst or top["best_fit"] > worst[p]["best_fit"]:
            worst[p] = top
    settings = defaultdict(list)
    for p in worst:
        settings[setting_of(p)].append(p)
    mats = {}
    for s, plist in settings.items():
        specs = {p: next(sp for sp in configs.MAIN if configs.build(sp).name == p) for p in plist}
        probs = {p: configs.build(specs[p]) for p in plist}
        names = [probs[p].meta["target"] for p in plist]
        M = np.zeros((len(plist), len(plist)))
        for i, src in enumerate(plist):
            g = np.array(worst[src]["best_genome"])
            for j, dst in enumerate(plist):
                M[i, j] = probs[dst].evaluate(g)[0]
        mats[s] = (names, M)
    out = [{"setting": s, "workload_from": names[i], "evaluated_on": names[j], "ratio": round(M[i, j], 4)}
           for s, (names, M) in mats.items() for i in range(len(names)) for j in range(len(names))]
    write_csv("transfer", out)
    return worst, mats


def feature_contrast(worst_by_run, n_random=1000):
    """Compare features of evolved worst cases with random workloads of the same size."""
    rng = np.random.default_rng(0)
    rows = []
    for p, rs in worst_by_run.items():
        spec = next(sp for sp in configs.MAIN if configs.build(sp).name == p)
        prob = configs.build(spec)
        evolved = [r["best_info"] for r in rs]
        rand = [prob.evaluate(prob.space.random(rng))[2] for _ in range(n_random)]
        evo_fit = [r["best_fit"] for r in rs]
        rand_fit = [prob.evaluate(prob.space.random(np.random.default_rng(i)))[0] for i in range(200)]
        row = {"problem": p, "random_median_ratio": round(float(np.median(rand_fit)), 3),
               "evolved_median_ratio": round(float(np.median(evo_fit)), 3)}
        skip = {"faults", "faults_opt", "target_cost", "ref_cost", "n_alloc"}
        for f in evolved[0]:
            if f in skip or not isinstance(evolved[0][f], (int, float)):
                continue
            row[f"{f}_random"] = round(float(np.median([x[f] for x in rand])), 3)
            row[f"{f}_evolved"] = round(float(np.median([x[f] for x in evolved])), 3)
        rows.append(row)
    return rows


def archive_correlations(by):
    """Spearman correlation between each descriptor and worst-case severity across MAP-Elites cells."""
    out = []
    for (p, m), rs in by.items():
        if m != "mapelites":
            continue
        grid = merged_archive(rs)
        bins = grid.shape[0]
        ii, jj = np.where(~np.isnan(grid))
        vals = grid[ii, jj]
        d = rs[0]["descriptors"]
        for axis, idx in ((d[0], ii), (d[1], jj)):
            rho, pv = spearmanr(idx / bins, vals)
            out.append({"problem": p, "descriptor": axis, "spearman_rho": round(float(rho), 3),
                        "p": float(pv), "cells": len(vals)})
    write_csv("descriptor_correlation", out)
    return out


def merged_archive(rs):
    grids = [np.array([[np.nan if v is None else v for v in row] for row in r["archive_grid"]], dtype=float)
             for r in rs]
    return np.fmax.reduce(grids)


# --------------------------------------------------------------------------- figures
SHOW = ["paging-LRU-k4", "paging-LFU-k4", "cpu-mean-FCFS", "cpu-max-SJF", "disk-seek-SSTF", "memory-best"]
TITLES = {
    "paging-LRU-k4": "LRU vs OPT (4 frames)", "paging-LFU-k4": "LFU vs OPT (4 frames)",
    "cpu-mean-FCFS": "FCFS vs SRTF, mean turnaround", "cpu-max-SJF": "SJF vs FCFS, max turnaround",
    "disk-seek-SSTF": "SSTF vs optimal seek", "memory-best": "Best fit vs ideal footprint",
}


def fig_convergence(by):
    fig, axes = plt.subplots(2, 3, figsize=(10, 5.6))
    for ax, p in zip(axes.flat, SHOW):
        for m in METHODS:
            rs = by.get((p, m))
            if not rs:
                continue
            x = np.array(rs[0]["checkpoints"])
            C = np.array([r["curve"] for r in rs])
            med = np.median(C, axis=0)
            ax.plot(x, med, color=COLOR[m], label=LABEL[m])
            ax.fill_between(x, np.percentile(C, 25, axis=0), np.percentile(C, 75, axis=0),
                            color=COLOR[m], alpha=0.15, linewidth=0)
        ax.set_title(TITLES[p], fontsize=9, color=INK, loc="left")
        ax.set_xscale("log")
        ax.set_xlabel("Evaluations")
        ax.set_ylabel("Worst ratio found")
    h, l = axes.flat[0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", ncol=4, bbox_to_anchor=(0.5, 1.03))
    fig.suptitle("Best-so-far worst-case ratio (median of 30 runs, band = interquartile range)",
                 y=1.08, fontsize=10, color=INK)
    fig.tight_layout()
    fig.savefig(f"{FIG}/convergence.png")
    plt.close(fig)


def fig_robustness(groups):
    order = ["paging", "cpu-mean", "cpu-max", "disk-seek", "disk-wait", "memory"]
    titles = {"paging": "Page replacement\nfaults / OPT faults", "cpu-mean": "CPU, mean turnaround\n/ SRTF",
              "cpu-max": "CPU, max turnaround\n/ FCFS", "disk-seek": "Disk, head movement\n/ offline optimum",
              "disk-wait": "Disk, max wait\n/ FCFS max wait", "memory": "Memory, peak footprint\n/ peak live bytes"}
    fig, axes = plt.subplots(2, 3, figsize=(10, 5.8))
    for ax, s in zip(axes.flat, order):
        rs = sorted(groups[s], key=lambda r: r["worst_found"])
        names = [r["target"] for r in rs]
        vals = [r["worst_found"] for r in rs]
        meds = [max(r[f"{m}_median"] for m in METHODS if f"{m}_median" in r) for r in rs]
        y = np.arange(len(rs))
        ax.barh(y, vals, color="#2a78d6", height=0.55, label="Worst found (any run)")
        ax.scatter(meds, y, color=INK, s=14, zorder=3, label="Median of best method")
        for yi, v in zip(y, vals):
            ax.text(v, yi, f" {v:.2f}", va="center", fontsize=8, color=INK)
        ax.axvline(1, color=INK2, linewidth=1, linestyle="--")
        ax.set_yticks(y, names)
        if max(vals) > 50:  # disk sweeps span two orders of magnitude
            ax.set_xscale("log")
            ax.set_xlim(0.8, max(vals) * 3)
        else:
            ax.set_xlim(0, max(vals) * 1.22)
        ax.set_title(titles[s], fontsize=9, loc="left", color=INK)
        ax.grid(axis="y", visible=False)
    h, l = axes.flat[0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", ncol=2, bbox_to_anchor=(0.5, 1.06))
    fig.tight_layout()
    fig.savefig(f"{FIG}/robustness.png")
    plt.close(fig)


def fig_bound(rows):
    fig, ax = plt.subplots(figsize=(5.2, 3.6))
    pal = {"FIFO": "#2a78d6", "LRU": "#eb6834", "Clock": "#1baf7a"}
    for t, mk in (("FIFO", "o"), ("LRU", "s"), ("Clock", "^")):
        rs = [r for r in rows if r["target"] == t]
        ks = [r["k"] for r in rs]
        ax.plot(ks, [r["evolved_max"] for r in rs], marker=mk, color=pal[t], label=f"{t}, evolved")
    rs = [r for r in rows if r["target"] == "LRU"]
    ax.plot([r["k"] for r in rs], [r["cyclic_adversary"] for r in rs], color=INK2, linestyle=":",
            marker="x", label="Textbook cyclic adversary (64 refs)")
    ks = sorted({r["k"] for r in rows})
    ax.plot(ks, ks, color=INK, linestyle="--", linewidth=1, label="Theoretical bound k")
    ax.set_xlabel("Cache size k (frames)")
    ax.set_ylabel("Faults / OPT faults")
    ax.set_xticks(ks)
    ax.legend(fontsize=8)
    ax.set_title("Evolved ratios approach the competitive bound", fontsize=10, loc="left", color=INK)
    fig.savefig(f"{FIG}/bound_tightness.png")
    plt.close(fig)


def fig_archives(by):
    pick = ["paging-LRU-k4", "cpu-mean-RR-q2", "disk-seek-SSTF", "memory-first"]
    fig, axes = plt.subplots(1, 4, figsize=(12, 3.2))
    for ax, p in zip(axes, pick):
        rs = by.get((p, "mapelites"))
        if not rs:
            continue
        g = merged_archive(rs)
        im = ax.imshow(g.T, origin="lower", cmap="Blues", extent=(0, 1, 0, 1), aspect="auto")
        d = rs[0]["descriptors"]
        ax.set_xlabel(d[0])
        ax.set_ylabel(d[1])
        ax.set_title(p, fontsize=9, loc="left", color=INK)
        ax.grid(False)
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="worst ratio")
    fig.suptitle("MAP-Elites maps: worst ratio found in each workload region (max over 30 runs)",
                 fontsize=10, color=INK, y=1.03)
    fig.tight_layout()
    fig.savefig(f"{FIG}/archives.png")
    plt.close(fig)


def fig_transfer(mats):
    order = ["paging", "cpu-mean", "disk-seek", "memory"]
    fig, axes = plt.subplots(1, 4, figsize=(13, 3.4))
    for ax, s in zip(axes, order):
        names, M = mats[s]
        im = ax.imshow(M, cmap="Blues")
        ax.set_xticks(range(len(names)), names, rotation=45, ha="right")
        ax.set_yticks(range(len(names)), names)
        ax.set_xlabel("evaluated on")
        ax.set_ylabel("worst workload of")
        ax.set_title(s, fontsize=9, loc="left", color=INK)
        ax.grid(False)
        for i in range(len(names)):
            for j in range(len(names)):
                v = M[i, j]
                ax.text(j, i, f"{v:.1f}", ha="center", va="center", fontsize=7,
                        color="white" if v > M.max() * 0.6 else INK)
    fig.suptitle("Do worst cases transfer? Ratio of each algorithm on another algorithm's worst workload",
                 fontsize=10, color=INK, y=1.04)
    fig.tight_layout()
    fig.savefig(f"{FIG}/transfer.png")
    plt.close(fig)


def fig_belady(runs):
    fig, ax = plt.subplots(figsize=(5.2, 3.4))
    for (L, P), mk in (((24, 6), "-"), ((64, 8), "--")):
        for m in METHODS:
            rs = [r for r in runs if r["group"] == "belady" and r["meta"]["length"] == L and r["method"] == m]
            if not rs:
                continue
            hits = np.array([r["first_hit"] if r["first_hit"] else np.inf for r in rs])
            xs = np.logspace(1, np.log10(rs[0]["budget"]), 60)
            ax.plot(xs, [(hits <= x).mean() for x in xs], linestyle=mk, color=COLOR[m],
                    label=f"{LABEL[m]}, {L} refs")
    ax.set_xscale("log")
    ax.set_xlabel("Evaluations")
    ax.set_ylabel("Share of runs that found an anomaly")
    ax.set_ylim(0, 1.02)
    ax.legend(fontsize=7, ncol=2)
    ax.set_title("Rediscovering Belady's anomaly (FIFO, 3 vs 4 frames)", fontsize=10, loc="left", color=INK)
    fig.savefig(f"{FIG}/belady.png")
    plt.close(fig)


def fig_gallery(worst):
    """Draw three evolved worst cases so a reader can see the pattern."""
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.2))
    # CPU convoy: FCFS worst workload as a Gantt-like arrival/burst plot
    g = np.array(worst["cpu-mean-FCFS"]["best_genome"])
    ax = axes[0]
    order = np.argsort(g[:, 0], kind="stable")
    done = cpu.fcfs(g[:, 0].tolist(), g[:, 1].tolist(), g[:, 2].tolist())
    for row, i in enumerate(order):
        ax.barh(row, g[i, 1], left=done[i] - g[i, 1], color="#2a78d6", height=0.6)
        ax.plot([g[i, 0]], [row], marker="|", color="#eb6834", markersize=8)
    ax.set_xlabel("Time (bars = when FCFS runs it, tick = arrival)")
    ax.set_ylabel("Process (by arrival)")
    ax.set_title("FCFS worst case: the convoy", fontsize=9, loc="left", color=INK)
    # Paging: LRU worst reference string
    ax = axes[1]
    ref = np.array(worst["paging-LRU-k4"]["best_genome"])[:, 0]
    ax.scatter(np.arange(len(ref)), ref, s=10, color="#2a78d6")
    ax.set_xlabel("Reference position")
    ax.set_ylabel("Page")
    ax.set_title("LRU worst case reference string (4 frames)", fontsize=9, loc="left", color=INK)
    # Disk: SSTF worst request set
    ax = axes[2]
    c = np.sort(np.array(worst["disk-seek-SSTF"]["best_genome"])[:, 1])
    ax.scatter(c, np.zeros_like(c), s=14, color="#2a78d6")
    ax.axvline(100, color="#eb6834", linewidth=1.5, label="head start")
    ax.set_yticks([])
    ax.set_xlim(0, 199)
    ax.set_xlabel("Cylinder")
    ax.legend(fontsize=8)
    ax.set_title("SSTF worst case request positions", fontsize=9, loc="left", color=INK)
    fig.tight_layout()
    fig.savefig(f"{FIG}/gallery.png")
    plt.close(fig)


def main():
    os.makedirs(FIG, exist_ok=True)
    runs = load()
    rows, stats, by = main_table(runs)
    groups = robustness(rows)
    bel_rows, bel_best = belady(runs)
    bnd = bound(runs)
    worst, mats = transfer(by)
    best_method_runs = {}
    for r in rows:
        best_method_runs[r["problem"]] = by[(r["problem"], r["best_method"])]
    feats = feature_contrast(best_method_runs)
    with open(f"{RES}/features.json", "w") as f:
        json.dump(feats, f, indent=1)
    corr = archive_correlations(by)
    fig_convergence(by)
    fig_robustness(groups)
    fig_bound(bnd)
    fig_archives(by)
    fig_transfer(mats)
    fig_belady(runs)
    fig_gallery(worst)
    gallery = {p: {"ratio": w["best_fit"], "genome": w["best_genome"], "info": w["best_info"],
                   "method": w["method"]} for p, w in worst.items()}
    gallery.update({f"belady-L{L}": {"extra_faults": w["best_fit"], "genome": w["best_genome"],
                                     "info": w["best_info"]} for (L, P), w in bel_best.items()})
    with open(f"{RES}/worst_cases.json", "w") as f:
        json.dump(gallery, f)
    summary = {
        "n_runs": len(runs),
        "share_ga_beats_random": float(np.mean([s["A12"] > 0.5 for s in stats if s["method"] == "ga"])),
        "share_any_evolutionary_best": float(np.mean([r["best_method"] != "random" for r in rows])),
        "best_method_counts": {m: sum(r["best_method"] == m for r in rows) for m in METHODS},
        "belady": bel_rows, "bound": bnd,
        "sig_better_than_random": {m: sum(1 for s in stats if s["method"] == m and s["A12"] > 0.5 and s["p"] < 0.05)
                                   for m in ("hillclimb", "ga", "mapelites")},
        "n_problems": len(rows),
    }
    with open(f"{RES}/summary.json", "w") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps({k: v for k, v in summary.items() if k not in ("belady", "bound")}, indent=1))


if __name__ == "__main__":
    main()
