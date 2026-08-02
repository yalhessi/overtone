#!/usr/bin/env python3
"""Which derived rules ever appear in the proof twee finds?

twee --print-score logs every derived rule as "(score) N. lhs -> rhs", and the
proof it prints references those same numbers. The difference is wasted work,
and the question is whether anything cheap at derivation time separates them.

    ./scripts/rule_usefulness.py 'logs/screen/proofs/*.out'
    ./scripts/rule_usefulness.py 'logs/screen/proofs/ROB*.out' --label ROB

Replaces a __main__ block that hardcoded globs into log directories which no
longer exist. Note the derived-rule sets come from single runs and twee's search
is not reproducible (docs/FINDINGS.md), so treat the waste percentages as
approximate.
"""
import argparse
import glob as globlib
from pathlib import Path

from overtone.proofs import summarise


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("globs", nargs="+", help="glob(s) of saved twee output files")
    ap.add_argument("--label", help="name for the group (default: the glob)")
    ap.add_argument("--limit", type=int, help="cap files per glob")
    a = ap.parse_args()

    for g in a.globs:
        paths = sorted(Path(p) for p in globlib.glob(g))
        if a.limit:
            paths = paths[:a.limit]
        if not paths:
            print(f"{g}: no files matched")
            continue
        summarise(paths, a.label or g)


if __name__ == "__main__":
    main()
