#!/usr/bin/env python3
"""Sketch transfer v0: donor-proof hints for problems the baseline cannot solve.

Thin CLI over `overtone.agent.sketch`. See docs/SKETCH_LOOP.md for the design and
docs/FINDINGS.md for what it has and has not achieved.

    ./scripts/sketch_transfer.py MVA005-1 LCL054-10          # build bundles
    ./scripts/sketch_transfer.py MVA005-1 --run              # and run them
    ./scripts/sketch_transfer.py MVA005-1 --ablate           # specific vs generic
"""
import argparse
from pathlib import Path

from overtone.agent import hints as hintlib
from overtone.agent.sketch import ablate, make_example, run_example


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("problems", nargs="*", help="target problem names")
    ap.add_argument("--exclude", type=Path,
                    help="file of problems never to use as donors or targets")
    ap.add_argument("--run", action="store_true", help="run the hinted jobs")
    ap.add_argument("--ablate", action="store_true",
                    help="also run specific-only / generic-only / full arms")
    ap.add_argument("--budget", type=int, default=1000)
    ap.add_argument("--cap", type=int, default=hintlib.MAX_HINTS,
                    help=f"maximum hints per problem (default {hintlib.MAX_HINTS})")
    ap.add_argument("--rank-by", choices=("frequency", "specificity"),
                    default="frequency",
                    help="frequency reproduces v0 but favours generic terms; "
                         "specificity keeps structural hints above the cap")
    ap.add_argument("--outdir", type=Path,
                    help="where to write bundles (default examples/sketch_loop)")
    a = ap.parse_args()

    if not a.problems:
        ap.error("give at least one problem name")

    exclude = set()
    if a.exclude and a.exclude.exists():
        exclude = {ln.strip() for ln in a.exclude.read_text().splitlines()
                   if ln.strip()}

    made = [info for p in a.problems
            if (info := make_example(p, exclude, a.outdir, a.cap, a.rank_by))]
    for info in made if a.run else []:
        run_example(info["problem"], a.budget, a.outdir)
    for info in made if a.ablate else []:
        ablate(info["problem"], a.budget, a.outdir)


if __name__ == "__main__":
    main()
