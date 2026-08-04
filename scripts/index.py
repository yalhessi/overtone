#!/usr/bin/env python3
"""Index every run's blueprint on one page, so problems can be compared.

    ./scripts/index.py                  # logs/index.html over prove/theory/loop
    ./scripts/index.py --open           # print a file:// URL to paste

Runs write their own blueprint when they finish, but a directory per problem is
only browsable if something enumerates it. This is that.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from overtone import config
from overtone.agent import blueprint

DEFAULT_ROOTS = ("prove", "theory", "loop", "transfer_dag")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--roots", nargs="*", default=DEFAULT_ROOTS,
                    help=f"log subdirectories to scan (default: {' '.join(DEFAULT_ROOTS)})")
    ap.add_argument("--out", type=Path, default=config.LOGS / "index.html")
    ap.add_argument("--title", default="Overtone runs")
    ap.add_argument("--open", action="store_true", help="print a file:// URL")
    a = ap.parse_args()

    dest = blueprint.write_index([config.LOGS / r for r in a.roots], a.out,
                                 title=a.title)
    print(dest)
    if a.open:
        print(f"file://{dest.resolve()}")


if __name__ == "__main__":
    main()
