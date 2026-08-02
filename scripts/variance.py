#!/usr/bin/env python3
"""Is a twee runtime reproducible enough to draw conclusions from?

Every research direction in docs/EXPECTATIONS.md has been motivated or dropped
on the strength of single timing measurements, several of which later moved.
This measures how much of that movement is real.

twee is deterministic with default flags (`cfg_random_mode = False`,
`Twee.hs:120`), so repeats of the same configuration must derive an *identical*
number of rules and reach an identical status. Only CPU time may vary, and only
from machine noise. A differing rule count means something other than twee
changed -- a contaminated input, the wrong binary, a stale file.

Two phases, because they answer different questions:

  solo      repeats run one at a time -- the intrinsic noise floor.
  loaded    repeats run while N background twee jobs compete -- the condition
            the screens actually ran under (16-24 workers), so this says whether
            screen timings are comparable to the near-serial timings used in the
            ablation and ladder experiments.
"""
import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from overtone.runner import Twee                                 # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = [
    ("REL029-1", "--no-flatten-goal", 60),
    ("LAT190-10", "--no-flatten-goal", 120),
    ("MVA006-1", "--no-flatten-goal", 400),
    ("GRP666-5", "--flatten-goal", 900),
]


def summarise(rs):
    cpus = [r.cpu for r in rs]
    walls = [r.wall for r in rs]
    mean = statistics.mean(cpus)
    sd = statistics.stdev(cpus) if len(cpus) > 1 else 0.0
    return {
        "n": len(rs),
        "status": sorted({r.status for r in rs}),
        "n_rules": sorted({r.n_rules for r in rs}),
        "cpu_mean": round(mean, 2),
        "cpu_sd": round(sd, 3),
        "cpu_cv_pct": round(100 * sd / mean, 2) if mean else 0.0,
        "cpu_min": round(min(cpus), 2),
        "cpu_max": round(max(cpus), 2),
        "cpu_spread_pct": round(100 * (max(cpus) - min(cpus)) / mean, 2) if mean else 0.0,
        "wall_mean": round(statistics.mean(walls), 2),
    }


def load_generators(n, problem, direction):
    """Background twee jobs to create CPU contention."""
    tw = Twee()
    src = tw.problem_path(problem)
    procs = []
    for _ in range(n):
        procs.append(subprocess.Popen(
            [tw.binary, str(src), "--root", str(tw.tptp_root),
             "--all-lemmas", "--show-peaks", direction,
             "--kbo-weight0-unary", "--print-score", "--max-time", "100000"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    return procs


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-n", "--repeats", type=int, default=5)
    ap.add_argument("--load", type=int, default=0,
                    help="background twee jobs to run concurrently (0 = solo)")
    ap.add_argument("--label", default=None)
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "VARIANCE.md")
    a = ap.parse_args()

    phase = f"load{a.load}" if a.load else "solo"
    label = a.label or f"variance-{phase}"
    tw = Twee()

    gens = []
    if a.load:
        # A hard problem so the generators never finish and load stays constant.
        gens = load_generators(a.load, "ROB001-1", "--no-flatten-goal")
        time.sleep(5)
        print(f"{a.load} background jobs running")

    rows = {}
    try:
        for problem, direction, budget in DEFAULT:
            rs = tw.repeat(problem, a.repeats, budget=budget, label=label,
                           direction=direction)
            s = summarise(rs)
            rows[problem] = s
            flag = "" if len(s["n_rules"]) == 1 else "  <-- RULE COUNT VARIES"
            print(f"  {problem:<12} {s['cpu_mean']:8.2f}s  sd {s['cpu_sd']:6.2f}  "
                  f"cv {s['cpu_cv_pct']:5.2f}%  spread {s['cpu_spread_pct']:5.2f}%  "
                  f"rules {s['n_rules']}{flag}", flush=True)
    finally:
        for p in gens:
            p.kill()

    out = ROOT / "logs" / f"variance_{phase}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"phase": phase, "repeats": a.repeats,
                               "load": a.load, "rows": rows}, indent=2))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
