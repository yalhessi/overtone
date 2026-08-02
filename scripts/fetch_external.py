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

  veroff   Bob Veroff's proof-sketch archive. Otter/Prover9 inputs carrying
           hand-curated list(hints)/formulas(hints) blocks, with their proofs.
           The only source of human oracle hints that exists *at* the frontier,
           where TSTP is empty: AIM loops, lattice theory, Boolean algebra,
           condensed detachment, median algebra, GMV algebras, HBCK, Robbins.

  tstp     Solutions to TPTP problems from ~23 systems. E-family derivations are
           structured TPTP (cnf(...) steps) and harvest directly as hint terms;
           Waldmeister and Vampire entries are raw system output needing custom
           parsers. Dense on easy/medium problems, empty at the frontier.
"""
import argparse
import html
import json
import re
import sys
import time
import urllib.parse
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

VEROFF_BASE = "https://www.cs.unm.edu/~veroff"
# Each is a project directory with an index page listing its files.
VEROFF_DIRS = ["AIM_REDONE", "ROBBINS", "LT", "BA", "CD", "GMV", "HBCK",
               "MEDIAN_ALGEBRA", "LOOPS"]
# .in carries the hint blocks, .pf the proofs. .out is the full run log (~18MB
# each in AIM_REDONE, mostly search noise) and .xml a restatement of .pf, so
# both are opt-in via --veroff-outputs.
VEROFF_KEEP = (".in", ".pf", ".proof", ".proofs", ".goals", ".txt")
VEROFF_KEEP_EXTRA = (".out", ".xml")

TSTP_CGI = "https://tptp.org/cgi-bin/SeeTPTP?Category=Solutions&Domain={domain}&File={problem}&System={system}"
# E-family systems emit structured TPTP derivations; others need bespoke parsing.
TSTP_SYSTEMS = ["E---3.3.0", "CSE_E---1.7", "Etableau---0.67", "Toma---0.7", "MaedMax---1.4"]

DEFAULT_TSTP_PROBLEMS = ROOT / "data" / "lists" / "ueq_uns.txt"


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


def _strip_scheme(url: str) -> str:
    """Compare URLs without caring about http vs https; Veroff's pages mix them."""
    return re.sub(r"^https?://", "", url)


def _index_links(dir_url: str, page: str):
    """Links on `page`, as paths relative to `dir_url`, in order, deduplicated.

    Veroff's pages are hand-written HTML with no directory autoindex, so the
    listing is whatever he linked -- some pages use relative hrefs and some
    absolute ones for the same directory. Everything is resolved against the
    page and then kept only if it lands inside `dir_url`, which both normalises
    the two styles and prevents writing outside the destination directory.
    """
    url = urllib.parse.urljoin(dir_url, page)
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            body = r.read().decode("utf-8", "replace")
    except Exception as e:                                        # noqa: BLE001
        print(f"    FAIL index {url}: {e}", file=sys.stderr)
        return []
    prefix = _strip_scheme(dir_url)
    out, seen = [], set()
    for href in re.findall(r'href\s*=\s*"([^"]+)"', body, re.IGNORECASE):
        href = html.unescape(href).strip().split("#", 1)[0].split("?", 1)[0]
        if not href or href.startswith("mailto:"):
            continue
        target = _strip_scheme(urllib.parse.urljoin(url, href))
        if not target.startswith(prefix):
            continue
        rel = target[len(prefix):]
        if not rel or rel in seen:
            continue
        seen.add(rel)
        out.append(rel)
    return out


def fetch_veroff(force=False, want_outputs=False, delay=0.3):
    """Mirror the data files under each Veroff project directory.

    Follows relative subdirectory and .html links one level deep, because
    several projects (BA, LT, AIM_REDONE/NS) put their files on a linked page
    rather than the directory index.
    """
    print("Veroff (proof sketches / curated hints)")
    keep = VEROFF_KEEP + (VEROFF_KEEP_EXTRA if want_outputs else ())
    total = 0
    for d in VEROFF_DIRS:
        print(f"  {d}/")
        dir_url = f"{VEROFF_BASE}/{d}/"
        pages = [""]                       # page paths relative to dir_url
        visited, files = set(), []
        while pages:
            page = pages.pop(0)
            if page in visited:
                continue
            visited.add(page)
            for rel in _index_links(dir_url, page):
                if rel.lower().endswith(keep):
                    files.append(rel)
                elif len(visited) == 1 and (rel.endswith("/")
                                            or rel.lower().endswith(".html")):
                    pages.append(rel)
            time.sleep(delay)
        if not files:
            print("    no data files linked")
            continue
        for rel in dict.fromkeys(files):
            dest = EXT / "veroff" / d / rel
            if dest.exists() and not force and dest.stat().st_size > 0:
                continue
            if get(urllib.parse.urljoin(dir_url, rel), dest, force):
                total += 1
            time.sleep(delay)
    print(f"  {total} new files")


def fetch_tstp(problems_file=None, force=False, delay=0.5):
    """Harvest TSTP derivations. Needs a list of PROBLEM names, one per line.

    There is no bulk TSTP download, so this is one CGI request per
    problem-system pair -- ~5700 for the UEQ UNS list. Hence the delay: it is a
    shared server and this is a long crawl, not a burst.
    """
    print("TSTP (per-problem solutions)")
    problems_file = Path(problems_file) if problems_file else DEFAULT_TSTP_PROBLEMS
    if not problems_file.exists():
        print(f"    skipped: {problems_file} does not exist -- run "
              "./scripts/make_ueq_list.py, or pass --tstp-problems <file>")
        return
    names = [l.strip() for l in problems_file.read_text().splitlines()
             if l.strip() and not l.startswith("%")]
    print(f"    {len(names)} problems x {len(TSTP_SYSTEMS)} systems from {problems_file.name}")
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
            finally:
                time.sleep(delay)
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
    ap.add_argument("--veroff", action="store_true")
    ap.add_argument("--tstp", action="store_true")
    ap.add_argument("--veroff-outputs", action="store_true",
                    help="also fetch Veroff .out/.xml run logs (adds ~2GB)")
    ap.add_argument("--tstp-problems",
                    help=f"file listing TPTP problem names to harvest "
                         f"(default {DEFAULT_TSTP_PROBLEMS.relative_to(ROOT)})")
    ap.add_argument("--force", action="store_true", help="re-download existing files")
    a = ap.parse_args()
    if not any([a.all, a.etp, a.robbins, a.veroff, a.tstp]):
        ap.error("pick at least one source, or --all")
    if a.all or a.etp:
        fetch_etp(a.force)
    if a.all or a.robbins:
        fetch_robbins(a.force)
    if a.all or a.veroff:
        fetch_veroff(a.force, a.veroff_outputs)
    if a.all or a.tstp:
        fetch_tstp(a.tstp_problems, a.force)


if __name__ == "__main__":
    main()
