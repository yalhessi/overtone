"""How many hints match the same subterm? The number that decides best-match.

Modifying twee so `Index.matches` returns the BEST match rather than the first
is only worth doing if several hints routinely match one subterm. If the typical
subterm matches zero or one, selection is a no-op by construction and the patch
cannot change any score.

Note what selection could and could not do even then. `hint_cost` is computed in
`addHint` from the hint alone -- `(len - |vars|) * factor + skel_cost + dup`
(Twee.hs:618) -- and never from the subterm matched. So choosing among matches
changes WHICH precomputed number is charged, never HOW MANY subterms have their
structure elided, and the dilution recorded in FINDINGS (43 hints neutral, 227
2.1x slower than none) is the latter. This script measures the elision directly:
`covered` is the fraction of scorable subterms that any hint flattens.

Matching here is twee's: the hint is the pattern, matched one-way against the
subterm, variables binding to arbitrary terms. `--resonance` additionally
requires every binding to be variable-headed, so both are reported.

    python scripts/hint_multiplicity.py
"""
import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from overtone import terms                                        # noqa: E402


def is_var(t):
    """TPTP: a variable is an uppercase-initial atom."""
    return isinstance(t, str) and t[:1].isupper()


def match(pattern, t, sub=None):
    """One-way match, pattern -> t. Returns the binding or None."""
    sub = {} if sub is None else sub
    if is_var(pattern):
        if pattern in sub:
            return sub if sub[pattern] == t else None
        sub = dict(sub)
        sub[pattern] = t
        return sub
    if isinstance(pattern, str) or isinstance(t, str):
        return sub if pattern == t else None
    if pattern[0] != t[0] or len(pattern) != len(t):
        return None
    for p, a in zip(pattern[1:], t[1:]):
        sub = match(p, a, sub)
        if sub is None:
            return None
    return sub


def resonant(sub):
    """twee's --resonance test: every binding maps to a variable-headed term."""
    return all(is_var(v) for v in sub.values())


def main():
    argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    from scripts.hint_dose import pool
    eqs, goal = pool()
    hints = []
    for name, (l, r) in eqs.items():
        for side in (l, r):
            t = terms.safe_term(side)
            # twee only consults hints for subterms with len > 1 (CP.hs:257).
            if t is not None and not isinstance(t, str):
                hints.append((name, t))

    # Score the goal and every pool lemma: these are the terms whose critical
    # pairs the search actually ranks.
    targets = [("goal", goal[0]), ("goal", goal[1])]
    targets += [(n, s) for n, (l, r) in eqs.items() for s in (l, r)]

    counts, res_counts, covered, res_covered, total = [], [], 0, 0, 0
    for _, text in targets:
        t = terms.safe_term(text)
        if t is None:
            continue
        for sub_t in terms.subtrees(t):
            if isinstance(sub_t, str):
                continue                       # len 1: twee does not consult hints
            total += 1
            subs = [s for _, h in hints if (s := match(h, sub_t)) is not None]
            counts.append(len(subs))
            res = [s for s in subs if resonant(s)]
            res_counts.append(len(res))
            covered += bool(subs)
            res_covered += bool(res)

    def line(tag, cs, cov):
        multi = sum(1 for c in cs if c > 1)
        print(f"  {tag:<12} covered {cov}/{total} ({cov/total:5.1%})  "
              f"mean {statistics.mean(cs):4.2f}  max {max(cs)}  "
              f">1 match: {multi}/{total} ({multi/total:5.1%})")

    print(f"{len(hints)} hint terms from {len(eqs)} lemmas; "
          f"{total} scorable subterms\n")
    line("default", counts, covered)
    line("--resonance", res_counts, res_covered)

    multi = sum(1 for c in counts if c > 1)
    print("\n--- what this says about patching twee ---")
    if multi / total < 0.05:
        print("  <5% of subterms match more than one hint: best-match is a")
        print("  no-op by construction. Do not patch.")
    else:
        print(f"  {multi/total:.0%} of subterms match several hints, so selection")
        print("  is not vacuous -- but see the docstring: selection still cannot")
        print(f"  reduce the {covered/total:.0%} coverage, which is the dilution.")
    # MEASURED, and it retired the guess this script was written on:
    # --resonance barely moves coverage on this pool (87% -> 85%), because ring
    # identities mostly DO bind variables to variables. It is a selection knob
    # here, not a dilution one. And the dose curve says dilution is not the
    # problem at this scale anyway -- coverage rises monotonically 0 -> 84%
    # while CPU goes 102.9 -> 81.3 -> 211.5 -> 33.4s. Content decides.
    print(f"  --resonance moves coverage {covered/total:.0%} -> "
          f"{res_covered/total:.0%} and multiplicity "
          f"{statistics.mean(counts):.2f} -> {statistics.mean(res_counts):.2f}: "
          f"a selection knob, not a dilution one.")


if __name__ == "__main__":
    main()
