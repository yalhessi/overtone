"""Open a proof of a hard node and ask what would have made it easy.

The manual sketch is the human's scaffold, not the proof. When twee proves
`right_moufang` in 192.6s it derives 131 lemmas on the way, 26 deep, and THAT is
the real decomposition. The scaffold names three of them.

So the question a sketching loop should be answering, and the one this asks: of
the lemmas inside a hard node's own proof, which would collapse it if they were
named as nodes -- and is the loop already deriving them elsewhere?

On RNG029-5 the answer is uncomfortable. `right_moufang` is the one route step
no run ever derives, and **23 of the 27 steps on its critical path are already in
every run's evidence bank**. The lemma immediately beneath it,

    associator(Y, Z, multiply(X, Y)) = associator(X, Y, multiply(Z, Y))

is in 6 of 6 banks, and supplying it takes `right_moufang` from 192.6s to 0.0s.
The loop derives nearly the whole derivation and never assembles it.

Two cautions the same experiment produced, both worth keeping:

**A depth heuristic is not a subdivision.** Naming that lemma and handing it the
two critical-path steps below it left it unproved at 300s -- it cites EIGHT
lemmas, spanning depths 1 to 24, and the proof says exactly which. Wrong parents
cost more than missing ones, and a cut through a proof DAG has to follow the
citations rather than the depth ordering.

**A contiguous gap means something different from a scattered one.** For
`middle_moufang` the missing block is d8-d12 and it is unbroken -- the
product-of-products manipulation, which no run's search produces at all. That is
not an attention failure the evidence bank can fix; it is a region the searches
never enter.

    python scripts/proof_mine.py logs/rng_dag/right_moufang.no-flatten-goal.out
    python scripts/proof_mine.py ... --cites L146
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from overtone.agent import evidence as evidencelib        # noqa: E402
from overtone.agent.dag import sketch_from_proof          # noqa: E402
from overtone.terms import eq_key                         # noqa: E402


def load_banks(patterns):
    """{run name: set of eq_key} for every evidence bank matching."""
    out = {}
    for pat in patterns:
        for d in sorted(Path().glob(pat)):
            if (d / "evidence.jsonl").exists():
                out[d.name] = {eq_key(e.lhs, e.rhs)
                               for e in evidencelib.load(d).all()}
    return out


def critical_path(sk, depth):
    """Deepest-parent chain from the conclusion back to an axiom.

    A readable spine, not the proof: every node off it still matters, which is
    why `--cites` exists and why a subdivision must take the citation set.
    """
    cur = max(sk.nodes, key=lambda n: depth[n])
    path = [cur]
    while sk.nodes[cur][2]:
        cur = max(sk.nodes[cur][2], key=lambda p: depth.get(p, 0))
        path.append(cur)
    return list(reversed(path))


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("artifact", type=Path, help="a twee .out that PROVED")
    ap.add_argument("--banks", nargs="*",
                    default=["logs/loop/RNG029-5-told-0*",
                             "logs/loop/RNG029-5-sched-0*",
                             "logs/loop/RNG029-5-bank-0*"],
                    help="run dirs whose evidence to cross-reference")
    ap.add_argument("--cites", metavar="LEMMA",
                    help="print what this lemma actually cites -- the parent "
                         "set a subdivision would have to supply")
    ap.add_argument("--max-nodes", type=int, default=400)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    text = a.artifact.read_text(errors="replace")
    sk, depth = sketch_from_proof(text, max_nodes=a.max_nodes, prefix="L")
    banks = load_banks(a.banks)

    if a.cites:
        n = a.cites if a.cites.startswith("L") else f"L{a.cites}"
        if n not in sk.nodes:
            print(f"{n} is not in this proof")
            return
        lhs, rhs, ps = sk.nodes[n]
        print(f"\n{n} (depth {depth[n]})\n   {lhs} = {rhs}")
        print(f"\ncites {len(ps)} lemma(s) -- ALL of these are the parent set, "
              f"not just the deepest:")
        for p in sorted(ps, key=lambda x: -depth.get(x, 0)):
            pl, pr, _ = sk.nodes[p]
            k = eq_key(pl, pr)
            where = sum(1 for ks in banks.values() if k in ks)
            print(f"   {p:<6} d{depth[p]:<3} in {where}/{len(banks)} banks  "
                  f"{pl} = {pr}"[:110])
        return

    path = critical_path(sk, depth)
    lem = len(sk.nodes)
    print(f"\n{a.artifact.name}")
    print(f"  {lem} lemmas derived, {max(depth.values())} deep; "
          f"critical path {len(path)} steps")
    print(f"  cross-referenced against {len(banks)} evidence bank(s)\n")

    rows, hits, gap = [], 0, []
    for n in path:
        lhs, rhs, _ = sk.nodes[n]
        k = eq_key(lhs, rhs)
        where = [r for r, ks in banks.items() if k in ks]
        if where:
            hits += 1
        else:
            gap.append(depth[n])
        rows.append({"lemma": n, "depth": depth[n], "eq": f"{lhs} = {rhs}",
                     "in_banks": len(where)})
        mark = f"in {len(where)}/{len(banks)}" if where else "-- NOT DERIVED"
        print(f"  d{depth[n]:>2} {mark:<16} {lhs} = {rhs}"[:112])

    print(f"\n  {hits}/{len(path)} of the critical path is already in the "
          f"loop's own evidence")
    if gap:
        runs = []
        for d in sorted(gap):
            if runs and d == runs[-1][-1] + 1:
                runs[-1].append(d)
            else:
                runs.append([d])
        for r in runs:
            span = f"d{r[0]}" if len(r) == 1 else f"d{r[0]}-d{r[-1]}"
            kind = ("a CONTIGUOUS block the searches never enter"
                    if len(r) > 2 else "isolated -- the rest of the chain is held")
            print(f"     missing {span}: {kind}")
    print("\n  A subdivision must take a lemma's CITED parents, not its deepest "
          "one: naming the step below right_moufang and giving it the two "
          "critical-path lemmas beneath left it unproved at 300s, because it "
          "cites eight.")
    if a.json:
        print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
