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
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LISTS = ROOT / "data" / "lists"

SPC_UEQ = re.compile(r"^%\s*SPC\s*:\s*CNF_(UNS|SAT|UNK|OPN)_\w*_UEQ\s*$")
RATING = re.compile(r"^%\s*Rating\s*:\s*([0-9.]+)")

# Only these carry a rating and status we can trust; the header block ends at the
# first non-comment line, so stop there rather than scanning whole problem files.
HEADER_END = re.compile(r"^\s*[^%\s]")


def tptp_root() -> Path:
    """TPTP_ROOT from the environment, else from .env, else the default layout."""
    env = os.environ.get("TPTP_ROOT")
    if not env:
        dotenv = ROOT / ".env"
        if dotenv.exists():
            for line in dotenv.read_text().splitlines():
                if line.startswith("TPTP_ROOT="):
                    env = line.split("=", 1)[1].strip()
                    break
    if not env:
        candidates = sorted((ROOT / "data").glob("TPTP-v*"))
        if candidates:
            env = str(candidates[-1])
    if not env:
        sys.exit("TPTP_ROOT is not set and no data/TPTP-v* directory exists. "
                 "Run ./bootstrap.sh first.")
    p = Path(env)
    if not (p / "Problems").is_dir():
        sys.exit(f"{p}/Problems does not exist -- is TPTP_ROOT correct?")
    return p


def scan(problems: Path):
    """Yield (name, domain, status, rating) for every UEQ problem."""
    for path in sorted(problems.rglob("*.p")):
        status = rating = None
        try:
            with open(path, "r", errors="replace") as f:
                for line in f:
                    if HEADER_END.match(line):
                        break
                    m = SPC_UEQ.match(line.rstrip())
                    if m:
                        status = m.group(1)
                        continue
                    m = RATING.match(line)
                    if m:
                        rating = float(m.group(1))
        except OSError as e:                                      # noqa: BLE001
            print(f"    skip {path.name}: {e}", file=sys.stderr)
            continue
        if status:
            yield path.stem, path.parent.name, status, rating


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=LISTS,
                    help="output directory (default data/lists)")
    ap.add_argument("--min-rating", type=float,
                    help="keep only problems rated >= this")
    a = ap.parse_args()

    root = tptp_root()
    print(f"scanning {root}/Problems ...")
    rows = list(scan(root / "Problems"))
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
