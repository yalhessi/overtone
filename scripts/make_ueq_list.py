#!/usr/bin/env python3
"""Enumerate the TPTP UEQ problems from the local distribution.

Writes data/lists/ueq.tsv (every UEQ problem with its domain, status and rating)
plus one plain problem-name list per status, which is the input format
fetch_external.py --tstp expects.

The source of truth is the `% SPC :` header of each problem file rather than
TPTP's tptp2T tool, so this runs offline and cannot drift from the distribution
actually on disk. Cross-check: v9.2.1 yields 1455 UEQ problems, matching the
count in docs/FINDINGS.md.
"""
import argparse
import sys
from pathlib import Path

from overtone import config
from overtone.problems import ueq_scan

ROOT = config.ROOT
LISTS = config.LISTS

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=LISTS,
                    help="output directory (default data/lists)")
    ap.add_argument("--min-rating", type=float,
                    help="keep only problems rated >= this")
    a = ap.parse_args()

    root = config.tptp_root()
    print(f"scanning {root}/Problems ...")
    rows = list(ueq_scan(root / "Problems"))
    if a.min_rating is not None:
        rows = [r for r in rows if r[3] is not None and r[3] >= a.min_rating]
    if not rows:
        sys.exit("no UEQ problems found -- check the distribution is complete")

    a.out.mkdir(parents=True, exist_ok=True)
    tsv = a.out / "ueq.tsv"
    with open(tsv, "w") as f:
        f.write("problem\tdomain\tstatus\trating\n")
        for name, domain, status, rating in rows:
            f.write(f"{name}\t{domain}\t{status}\t"
                    f"{'' if rating is None else f'{rating:.2f}'}\n")
    print(f"  wrote {tsv} ({len(rows)} problems)")

    for status in ("UNS", "SAT", "UNK", "OPN"):
        names = [r[0] for r in rows if r[2] == status]
        dest = a.out / f"ueq_{status.lower()}.txt"
        dest.write_text("".join(n + "\n" for n in names))
        print(f"  wrote {dest.name} ({len(names)})")

    by_domain = {}
    for _, domain, _, _ in rows:
        by_domain[domain] = by_domain.get(domain, 0) + 1
    print("  domains: " + ", ".join(f"{d} {n}" for d, n in sorted(by_domain.items())))


if __name__ == "__main__":
    main()
