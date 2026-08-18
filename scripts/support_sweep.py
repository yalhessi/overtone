"""Race a node against many assumption sets at once, stopping at the first proof.

Which lemmas a node is given decides whether it proves at all, and nothing about
a lemma predicts which way it will cut. Measured on RNG029-5 (FINDINGS):

    right_moufang    197.8s from exactly {assoc_cyclic, assoc_def_246,
                     assoc_def_247}; drop any one -> timeout; ADD assoc_def_add,
                     which is universal and proves in 0.0s -> timeout
    middle_moufang   124.2s from its four recorded parents, 97.0s WITHOUT
                     assoc_cyclic, 233.1s with assoc_def_add added, and timeout
                     with `flexible` added

So each node has a small core, some tolerated ballast, and specific poisons, and
the three are not distinguishable by looking at the lemmas. Worse, the proof
certificate cannot steer the choice: the parent worth dropping from
`middle_moufang` is one its proof CITES, so `unused_support` cannot see it.

The space is combinatorial and the signal is nearly binary, so the only way
through is to measure -- and the only affordable way to measure is at once. This
is what the loop cannot do: it tests roughly one configuration per iteration,
about ten per run, against 2^15 subsets of a scaffold. A sweep of 39 sets over
the derived bridge took about fifteen minutes of wall time here.

Every arm stops the moment one proves, including arms still queued behind a full
pool -- see `dag.race_support`. A losing arm is answering a question with no
value left, which is the same argument the goal-direction race already makes.

    python scripts/support_sweep.py RNG029-5 --node bridge --sizes 1,2
    python scripts/support_sweep.py RNG029-5 --node bridge --pool def_add,flex
"""
import argparse
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from overtone import config                                       # noqa: E402
from overtone.agent.dag import (grounding, race_support,          # noqa: E402
                                unproved_ancestors, verify)

# How many combinations to materialise before sampling. A pool of 19 at sizes
# 3 and 4 is 4,845; the ceiling only matters for a pool large enough that even
# listing the space is the wrong move.
_CEILING = 200_000


def _seed(problem):
    from overtone.agent.derive import derive_sketch
    return derive_sketch(problem)[0]


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("problem")
    ap.add_argument("--node", default=None,
                    help="which node of the derived seed to race; default is "
                         "the obligation (nearest ungrounded node to the goal)")
    ap.add_argument("--pool", default=None,
                    help="comma-separated node names to draw sets from; "
                         "default is every proved claim in the seed")
    ap.add_argument("--sizes", default="0,1,2",
                    help="set sizes to enumerate, e.g. 0,1,2 for standalone, "
                         "singletons and pairs")
    ap.add_argument("--max-sets", type=int, default=60,
                    help="cap, so a careless --sizes cannot queue thousands")
    ap.add_argument("--channel", choices=("axioms", "hints"), default="axioms",
                    help="how the set is supplied. An axiom joins the rewrite "
                         "system and forms critical pairs with every rule, "
                         "which is what poisons a large set; a hint only "
                         "reweights scoring. Measured to invert on MVA005-1: "
                         "20 lemmas as axioms timed out, the same set as hints "
                         "proved in 173.6s.")
    ap.add_argument("--order", choices=("lex", "random"), default="lex",
                    help="`lex` takes the alphabetically first sets, which at "
                         "sizes 3,4 over 19 lemmas searches one corner of 4,845; "
                         "`random` samples the space instead.")
    ap.add_argument("--seed", type=int, default=0,
                    help="for --order random, so a sweep is repeatable")
    ap.add_argument("--budget", type=int, default=300)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--binary")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    binary = a.binary or config.twee_path(deterministic=True)
    sketch = _seed(a.problem)
    outdir = Path(config.LOGS) / "support_sweep" / a.problem

    # Everything in the pool has to be PROVED, or a winning set would be a
    # conditional result -- an implication, not a licence to supply it.
    v = verify(a.problem, sketch, outdir=outdir / "scaffold", budget=a.budget,
               workers=a.workers, binary=binary)
    ground, _ = grounding(sketch, v["results"])

    node = a.node
    if node is None:
        goal = next((n for n in sketch.nodes if n.endswith("goal")), None)
        chain = unproved_ancestors(sketch, goal, ground) if goal else []
        node = chain[0] if chain else goal
    lhs, rhs, _ = sketch.nodes[node]

    pool = ([p.strip() for p in a.pool.split(",") if p.strip()] if a.pool
            else sorted(n for n in sketch.claims()
                        if n in ground and n != node))
    missing = [p for p in pool if p not in sketch.nodes]
    if missing:
        ap.error(f"pool names no such node: {missing}")
    ungrounded = [p for p in pool if p not in ground]
    if ungrounded:
        print(f"  dropping {len(ungrounded)} ungrounded pool member(s): "
              f"{ungrounded}", flush=True)
        pool = [p for p in pool if p in ground]

    sizes = sorted({int(x) for x in a.sizes.split(",") if x.strip()})
    combos = []
    for k in sizes:
        for combo in itertools.combinations(pool, k):
            combos.append(combo)
            if len(combos) >= _CEILING:
                break
        if len(combos) >= _CEILING:
            break
    total = len(combos)
    if a.order == "random":
        # Taking the first `max_sets` in lexicographic order is not a sample of
        # the space, it is one corner of it: at sizes 3,4 over 19 lemmas that is
        # 60 of 4,845, all beginning with the alphabetically earliest lemma.
        # Seeded, so a sweep can be repeated exactly.
        import random
        random.Random(a.seed).shuffle(combos)
    combos = combos[:a.max_sets]
    if total > len(combos):
        print(f"  {len(combos)} of {total} set(s), {a.order} order"
              + (f" (seed {a.seed})" if a.order == "random" else ""), flush=True)
    cands = [("+".join(c) or "none", list(c), sketch.equations(list(c)))
             for c in combos]

    print(f"\n{a.problem}: racing `{node}` over {len(cands)} assumption set(s) "
          f"from a pool of {len(pool)} as {a.channel}, {a.budget}s each")
    print(f"  {lhs} = {rhs}\n", flush=True)
    won, rows = race_support(a.problem, lhs, rhs, cands, outdir=outdir / node,
                             budget=a.budget, workers=a.workers, binary=binary,
                             node=node, channel=a.channel)

    best = {}
    for r in rows:
        if r.get("proved"):
            lab = r["label"]
            if lab not in best or r["cpu"] < best[lab]:
                best[lab] = r["cpu"]
    # What the sweep COST is the result, not just which set won. Arms run in
    # parallel and every one is cancelled the moment another proves, so
    # "attempts before the winner" is not well defined -- the honest numbers are
    # how many sets reached a verdict at all and what that took. Together they
    # turn "the space is 4,845 sets" into a measured density.
    verdicts = {r["label"] for r in rows}
    cpu = sum(r.get("cpu") or 0.0 for r in rows)
    # An arm that CRASHED is not an arm that failed to prove, and reporting the
    # two the same way is how a harness fault becomes a mathematical
    # conclusion. An eighteen-lemma set joins into a 359-character label, the
    # artifact name went past NAME_MAX, `_job` raised, and this printed "none
    # proved" -- a clean negative from a run that never reached the prover.
    errors = [r for r in rows if str(r.get("result", "")).startswith("Error")]
    print(f"\n=== {len(best)} of {len(cands)} set(s) proved `{node}`")
    print(f"    {len(verdicts)} set(s) reached a verdict, {cpu:.1f}s CPU "
          f"({a.channel})")
    if errors:
        print(f"    !! {len(errors)} arm(s) ERRORED and proved nothing about "
              f"anything -- this run is not a measurement:")
        for r in errors[:3]:
            print(f"       {r['result'][:110]}")
    for lab, cpu in sorted(best.items(), key=lambda x: x[1]):
        print(f"   {cpu:>8.1f}s  {lab}")
    if not best:
        # The negative is the common case and has to be trustworthy: 45 sets
        # over the derived bridge, none of them working, is what condemned that
        # decomposition rather than the lemma set.
        print(f"   none. `{node}` resists every set tried, standalone included."
              f"\n   That does not make it unprovable -- it makes it a bad "
              f"target, if something reachable sits nearby.")
    if a.json:
        print(json.dumps({"node": node, "winner": won, "proved": best,
                          "n_sets": len(cands), "n_space": total,
                          "n_verdicts": len(verdicts), "cpu": round(cpu, 1),
                          "errors": len(errors),
                          "channel": a.channel, "order": a.order,
                          "seed": a.seed, "pool": pool}, indent=2))


if __name__ == "__main__":
    main()
