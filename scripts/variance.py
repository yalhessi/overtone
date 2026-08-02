#!/usr/bin/env python3
"""Is a twee runtime reproducible enough to draw conclusions from?

Every research direction in docs/EXPECTATIONS.md has been motivated or dropped
on the strength of single timing measurements, several of which later moved.
This measures how much of that movement is real.

`cfg_random_mode` is off by default (`Twee.hs:120`), so the search looked like
it should be reproducible. It is not: twee schedules interreduction and queue
simplification by elapsed CPU time (`Twee.hs:824-848` via `Twee/Task.hs`), so
*when* they fire depends on machine load, and they change what the search does
next. Measured over 5 repeats of identical input: cv 0.5% on REL029-1 and
LAT190-10, but 67.7% on MVA006-1 and 26.4% on GRP666-5, with a different derived
rule count on essentially every repeat.

So a differing rule count is expected, not a bug signal, and single-run timings
on the high-variance problems are close to meaningless.

Two phases, because they answer different questions:

  solo      repeats run one at a time -- the intrinsic noise floor.
  loaded    repeats run while N background twee jobs compete -- the condition
            the screens actually ran under (16-24 workers), so this says whether
            screen timings are comparable to the near-serial timings used in the
            ablation and ladder experiments.
"""
import argparse
import json
import subprocess
import time
from pathlib import Path

from overtone.runner import ALWAYS, BASE_FLAGS, Twee, summarise  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = [
    ("REL029-1", "--no-flatten-goal", 60),
    ("LAT190-10", "--no-flatten-goal", 120),
    ("MVA006-1", "--no-flatten-goal", 400),
    ("GRP666-5", "--flatten-goal", 900),
]


def load_generators(n, problem, direction):
    """Background twee jobs to create CPU contention."""
    tw = Twee()
    src = tw.problem_path(problem)
    procs = []
    for _ in range(n):
        procs.append(subprocess.Popen(
            [tw.binary, str(src), "--root", str(tw.tptp_root),
             *BASE_FLAGS, direction, *ALWAYS, "--max-time", "100000"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    return procs


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-n", "--repeats", type=int, default=5)
    ap.add_argument("--load", type=int, default=0,
                    help="background twee jobs to run concurrently (0 = solo)")
    ap.add_argument("--label", default=None)
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
