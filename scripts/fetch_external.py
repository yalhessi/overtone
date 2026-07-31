#!/usr/bin/env python3
"""Fetch the external corpora Overtone trains and evaluates on.

Each source is here for a specific reason:

  etp      Tao's Equational Theories Project. 4694 magma laws over one binary
           operator, ~22M implication pairs with Vampire timings. The uniform
           signature means transfer needs no symbol bridge. Note 99.97% of its
           proven implications take under a second, so the useful slice is the
           ~2400 non-trivial ones plus the ~1000 Vampire could not resolve.

  robbins  McCune's EQP/Otter inputs and proofs for the Winker/McCune ladder,
           including list(hints) blocks for Lemma 2 (56), Lemma 3 (42) and the
           theorem (93). These are the only oracle hints available for the ROB
           frontier -- TSTP has no proof of ROB001-1/ROB007-1 from any system,
           because it runs at competition time limits and EQP needed 7.8 days.

  tstp     Solutions to TPTP problems from ~23 systems. E-family derivations are
           structured TPTP (cnf(...) steps) and harvest directly as hint terms;
           Waldmeister and Vampire entries are raw system output needing custom
           parsers. Dense on easy/medium problems, empty at the frontier.
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "data" / "external"

ETP_BASE = "https://raw.githubusercontent.com/teorth/equational_theories/main/data"
ETP_FILES = [
    "equations.txt",              # the 4694 laws
    "README.md",
    "most_wanted.md",
    "duals.json",
    "Austin_implications.txt",
    "2024-11-10-outcomes.json.zip",   # full implication matrix (498MB unzipped)
    "2025-08-11-vampire.json.gz",     # per-implication result + time + config
]

ROBBINS_BASE = "https://www.cs.unm.edu/~mccune/papers/robbins"
ROBBINS_FILES = (
    ["eqp-theorem.in.txt", "eqp-theorem.proof.txt",
     "otter-theorem.in.txt", "otter-theorem.proof.txt",
     "lemmas.html", "jar.html", "eqp-hunt.proof.txt"]
    + [f"{p}-lemma{n}.{k}.txt"
       for n in range(4) for p in ("eqp", "otter") for k in ("in", "proof")]
)

TSTP_CGI = "https://tptp.org/cgi-bin/SeeTPTP?Category=Solutions&Domain={domain}&File={problem}&System={system}"
# E-family systems emit structured TPTP derivations; others need bespoke parsing.
TSTP_SYSTEMS = ["E---3.3.0", "CSE_E---1.7", "Etableau---0.67", "Toma---0.7", "MaedMax---1.4"]


def get(url: str, dest: Path, force: bool = False) -> bool:
    if dest.exists() and not force and dest.stat().st_size > 0:
        print(f"    have {dest.name}")
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=300) as r, open(dest, "wb") as f:
            f.write(r.read())
        print(f"    got  {dest.name} ({dest.stat().st_size:,} bytes)")
        return True
    except Exception as e:                                    # noqa: BLE001
        print(f"    FAIL {dest.name}: {e}", file=sys.stderr)
        dest.unlink(missing_ok=True)
        return False


def fetch_etp(force=False):
    print("ETP (Equational Theories Project)")
    for f in ETP_FILES:
        get(f"{ETP_BASE}/{f}", EXT / "etp" / f, force)


def fetch_robbins(force=False):
    print("Robbins (McCune EQP/Otter)")
    for f in ROBBINS_FILES:
        get(f"{ROBBINS_BASE}/{f}", EXT / "robbins" / f, force)


def fetch_tstp(problems_file=None, force=False):
    """Harvest TSTP derivations. Needs a list of PROBLEM names, one per line."""
    print("TSTP (per-problem solutions)")
    if not problems_file:
        print("    skipped: pass --tstp-problems <file> with one problem name per line")
        return
    import html
    import re
    names = [l.strip() for l in Path(problems_file).read_text().splitlines() if l.strip()]
    for name in names:
        domain = re.match(r"([A-Z]+)", name).group(1)
        for system in TSTP_SYSTEMS:
            dest = EXT / "tstp" / domain / f"{name}__{system.replace('---', '-')}.txt"
            if dest.exists() and not force:
                continue
            url = TSTP_CGI.format(domain=domain, problem=name, system=system)
            try:
                with urllib.request.urlopen(url, timeout=120) as r:
                    raw = r.read().decode("utf-8", "replace")
            except Exception:                                  # noqa: BLE001
                continue
            body = html.unescape(re.sub(r"<[^>]*>", "", raw))
            # Only keep entries that actually carry a structured derivation.
            if body.count("cnf(") < 3:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(body)
            print(f"    got  {dest.name} ({body.count('cnf(')} steps)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--etp", action="store_true")
    ap.add_argument("--robbins", action="store_true")
    ap.add_argument("--tstp", action="store_true")
    ap.add_argument("--tstp-problems", help="file listing TPTP problem names to harvest")
    ap.add_argument("--force", action="store_true", help="re-download existing files")
    a = ap.parse_args()
    if not any([a.all, a.etp, a.robbins, a.tstp]):
        ap.error("pick at least one source, or --all")
    if a.all or a.etp:
        fetch_etp(a.force)
    if a.all or a.robbins:
        fetch_robbins(a.force)
    if a.all or a.tstp:
        fetch_tstp(a.tstp_problems, a.force)


if __name__ == "__main__":
    main()
