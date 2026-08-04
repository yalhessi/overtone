#!/usr/bin/env python3
"""Plain baseline on the eight RNG problems TPTP records as unsolved.

Every RNG result in this project so far targets *known* theorems -- the Moufang
identities are classical (Bruck-Kleinfeld 1951) and carry `Status: Unsatisfiable`.
These eight carry `Status: Unknown`: no proof and no countermodel on record, all
rated 1.00.

    RNG010-5/6/7   the three Moufang identities imply skew symmetry of
                   s(w,x,y,z) = (wx,y,z) - x(w,y,z) - (x,y,z)w.
                   CADE-11 competition problem Eq-9. The Moufang hypotheses were
                   stated *wrongly* until the v2.3.0 bugfix, so pre-1993 results
                   do not transfer to the current file.
    RNG033-6/7/8/9 (xy,z,w) + (x,y,[z,w]) = x(y,z,w) + (x,z,w)y.
                   Stevens (1987) challenge problem.
    RNG036-7       x^5 = x implies commutative. Known true -- Jacobson's theorem
                   covers x^n = x for all n -- but the standard proof is
                   structural (subdirect decomposition, Wedderburn), not
                   equational. RNG009 (x^3) is rated 0.43 and RNG035-7 (x^4) is
                   solved at 0.65, so x^5 is the open top of a graded family.

No hints and no sketch, which is the point: the strongest RNG result here is
still the plain 4000s screen solving RNG027-10 at rating 1.00 (3271.1s). Budget
alone has beaten every sketch so far and has never been pointed at this set.

A `Satisfiable` result would be as publishable as a proof -- it would settle the
problem the other way -- so both outcomes are recorded and the full output kept.
Any non-timeout result here needs independent verification before it is claimed.
"""
import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from overtone import config, runner

os.environ.setdefault("TWEE_STEPS_PER_SECOND", "10000")
OUT = config.LOGS / "open_rng"
DIRS = ("--no-flatten-goal", "--flatten-goal")
BUDGET = 4000
PROBLEMS = ["RNG010-5", "RNG010-6", "RNG010-7",
            "RNG033-6", "RNG033-7", "RNG033-8", "RNG033-9",
            "RNG036-7"]


BIN = config.twee_path(deterministic=True)


def job(a):
    prob, direc, budget = a
    tag = f"{prob}.{direc[2:]}"
    p = runner.write_problem(prob, OUT / f"{tag}.p")
    r = runner.run(p, [*runner.BASE_FLAGS, direc], budget, problem=prob,
                   binary=BIN)
    if r.status != "Timeout":
        (OUT / f"{tag}.out").write_text(r.output)
    return {"problem": prob, "direction": direc, "result": r.status,
            "proved": r.proved, "cpu": round(r.cpu, 1)}


def main():
    # This script had no argument parsing, so any invocation -- `--help`
    # included -- immediately started a 16-job, 4000-second sweep. A script whose
    # only mode is "burn a CPU-hour" should at least say so first.
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--budget", type=int, default=BUDGET)
    ap.add_argument("--workers", type=int, default=len(PROBLEMS) * len(DIRS))
    ap.add_argument("--problems", nargs="*", default=PROBLEMS)
    ap.add_argument("--list", action="store_true",
                    help="print the targets and exit without proving")
    a = ap.parse_args()
    if a.list:
        for p in a.problems:
            print(f"  {p}")
        print(f"\n  {len(a.problems)} problems x {len(DIRS)} directions "
              f"at {a.budget}s = up to "
              f"{len(a.problems) * len(DIRS) * a.budget / 3600:.1f} CPU-hours")
        return

    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [(p, d, a.budget) for p in a.problems for d in DIRS]
    print(f"{len(jobs)} jobs, {a.budget}s, deterministic build, no hints",
          flush=True)
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=min(len(jobs), a.workers)) as pool:
        res = list(pool.map(job, jobs))
    for r in sorted(res, key=lambda x: (x["problem"], x["direction"])):
        print(f"  {r['problem']:<10} {r['direction']:<18} "
              f"{r['result']:<14} {r['cpu']:>8.1f}s", flush=True)
    settled = sorted({r["problem"] for r in res if r["result"] != "Timeout"})
    print(f"\n  NON-TIMEOUT: {len(settled)}/{len(a.problems)}  {settled}",
          flush=True)
    if settled:
        print("  -> verify independently before claiming anything", flush=True)
    (OUT / "open_rng.json").write_text(json.dumps(res, indent=2) + "\n")
    print(f"\ntotal {time.time() - t0:.0f}s wall", flush=True)


if __name__ == "__main__":
    main()
