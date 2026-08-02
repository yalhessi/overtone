#!/usr/bin/env python3
"""Run a sketch as a ladder of goals instead of a bag of hints.

Thin CLI over `overtone.agent.ladder`. See docs/SKETCH_LOOP.md for the design.

    ./scripts/ladder.py MVA005-1 \\
        --donor-proof logs/screen/proofs/MVA001-1_flatten-goal.out \\
        --waypoints examples/sketch_loop/MVA005-1/hints.tptp

`--promote hints` (the default) carries proven rungs into the final run as
hints; `--promote axioms` reproduces the first implementation, which timed out
where hints proved in 173.6s.
"""
import argparse
import re
import sys
from pathlib import Path

from overtone import config
from overtone.agent.ladder import run_ladder


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("problem")
    ap.add_argument("--donor-proof", type=Path, required=True)
    ap.add_argument("--waypoints", type=Path, required=True,
                    help="hints.tptp whose $hint terms name the rungs")
    ap.add_argument("--rung-budget", type=int, default=120)
    ap.add_argument("--final-budget", type=int, default=1000)
    ap.add_argument("--direction", default="--no-flatten-goal")
    ap.add_argument("--promote", choices=("hints", "axioms"), default="hints",
                    help="how proven rungs reach the final run (default hints)")
    ap.add_argument("--verify", choices=("standalone", "chained"),
                    default="standalone",
                    help="standalone (default) proves each rung from the "
                         "problem's own axioms; chained also carries the "
                         "previously proven lemmas, which is 3.4x slower")
    ap.add_argument("--workers", type=int, default=1,
                    help="parallel rung verification (standalone only)")
    ap.add_argument("--binary", help="twee build to use (default: TWEE_PATH)")
    ap.add_argument("--outdir", type=Path)
    a = ap.parse_args()

    outdir = a.outdir or (config.ROOT / "examples" / "sketch_loop" / a.problem
                          / "ladder")
    waypoints = re.findall(r"\$hint\(\s*(.*?)\s*\)\)\.",
                           a.waypoints.read_text(), re.S)
    try:
        run_ladder(a.problem, a.donor_proof, waypoints,
                   rung_budget=a.rung_budget, final_budget=a.final_budget,
                   direction=a.direction, promote=a.promote,
                   verify=a.verify, workers=a.workers,
                   outdir=outdir, binary=a.binary)
    except (ValueError, FileNotFoundError) as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
