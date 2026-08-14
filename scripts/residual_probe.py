#!/usr/bin/env python3
"""Derive a waypoint from a problem's goal, with no prover and no model.

    ./scripts/residual_probe.py RNG029-5
    ./scripts/residual_probe.py RNG029-5 --theory      # also try the axioms

Two questions, both answered by exact integer linear algebra over the free
non-associative ring:

**Can the goal be written as a short combination of associator terms?** Those
terms are universal -- true of any ring -- so the answer assumes nothing about
the theory and cannot smuggle in the axioms that are meant to discharge it. On
RNG029-5 the answer is two terms, which reduces the conjecture to the single
obligation `associator(x,y,zx) = x * associator(y,z,x)`. Supplying that one
equation takes the target from a 4000s timeout in both directions to **6.7s**.

**Is the goal an integer combination of the theory's own identities?** Polarize
the problem's axioms, close under bounded consequence, and solve. A certificate
here is an algebraic derivation, but a long one is not a decomposition: RNG029-5
comes back with 52 terms and coefficients past 100, which certifies the target
and suggests no route through it.

The integer part is not a formality. Solving the same system over the rationals
returns coefficients of 1/2, and dividing by 2 is only valid in a ring without
2-torsion -- which the alternative-ring axioms do not give.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from overtone import freering as F, problems


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("problem")
    ap.add_argument("--theory", action="store_true",
                    help="also certify the residual over the problem's own "
                         "polarized axioms (slower, and usually long)")
    ap.add_argument("--max-terms", type=int, default=12,
                    help="report a decomposition only if it is at most this "
                         "long; longer ones are identities, not routes")
    a = ap.parse_args()

    path = problems.problem_path(a.problem)
    conj = problems.conjecture(path)
    if conj is None:
        print(f"{a.problem}: no conjecture to read")
        return 2
    print(f"{a.problem}: {conj[0]} = {conj[1]}")

    d = F.decompose(conj[0], conj[1])
    if d["terms"] is None:
        print(f"\nno associator decomposition: {d['note']}")
        for m in d.get("outside", [])[:5]:
            print(f"    unreachable monomial {m}")
    else:
        n = len(d["terms"])
        print(f"\nassociator decomposition over {d['basis']} universal terms: "
              f"{n} term(s)")
        for label, coeff in d["terms"]:
            print(f"    {coeff:+3}  {label}")
        if n == 2:
            (l1, c1), (l2, c2) = d["terms"]
            print(f"\n  two terms, so the conjecture is equivalent to a single "
                  f"obligation:\n    {l1} = {l2}   (up to sign)")
        if n > a.max_terms:
            print(f"\n  {n} terms is an identity, not a route -- nothing here "
                  f"decomposes the goal")

    if a.theory:
        ids = F.theory_identities(a.problem)
        print(f"\ntheory identities the normal form does not already encode: "
              f"{len(ids)}")
        for name, res in ids:
            print(f"    {name} (degree {F.degree(res)})")
        target = F.expand(F.parse(conj[0]), F.parse(conj[1]))
        cons = F.consequences(ids, sorted(F.variables(target)),
                              F.degree(target), limit=20000)
        print(f"bounded consequences at degree <= {F.degree(target)}: {len(cons)}")
        cert = F.certificate(target, cons)
        if cert.get("coefficients"):
            n = len(cert["coefficients"])
            big = max(abs(v) for v in cert["coefficients"].values())
            print(f"INTEGER certificate: {n} terms, largest coefficient {big}")
            if n > a.max_terms:
                print("  -- long, so this is a derivation and not a "
                      "decomposition: it proves the target without suggesting "
                      "an intermediate to prove first")
        else:
            print(f"no integer certificate: {cert.get('reason', '')}")
            print(f"  in the rational span: {cert.get('rational')}"
                  "  (rational-only means it follows after dividing, i.e. only "
                  "in a torsion-free ring)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
