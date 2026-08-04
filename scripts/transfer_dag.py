#!/usr/bin/env python3
"""Transfer a donor's proof to a resisted target, as a DAG rather than hints.

The method that flipped RNG029-5, RNG028-7 and RNG027-8, generalised. Four steps,
none of which involve drafting anything:

  1. Find the most axiom-similar solved sibling (`agent/donors.find_donor`).
  2. Read its proof as a DAG -- `Lemma N:` lines are nodes, `by lemma N`
     citations are edges. This is the donor's own dependency structure, not a
     guessed one, which matters: hand-drafted edges were wrong three times out
     of four, at costs from 18x to a blocked subtree.
  3. Verify that DAG against the *target's* axioms, topologically, each node
     given its parents. Nodes that fail are dropped and their descendants
     skipped, so what survives is a set of theorems of the target's theory.
  4. Attempt the target with the deepest survivors as axioms.

Why the deepest, and why axioms. On RNG027-5 the donor's proof ran 234 lemmas
deep and its goal cited exactly four; those four flipped all three targets, while
all 234 in the hint channel flipped none. Depth is the proxy for "near the goal",
and a small precise axiom set beats any quantity of hints.

Budget is a diagnostic here, not a resource: a node needing more than ~30s is
evidence the decomposition is wrong at that point, not that it needs longer.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from overtone import config
from overtone.agent.dag import attempt, sketch_from_proof, verify
from overtone.agent.donors import find_donor

os.environ.setdefault("TWEE_STEPS_PER_SECOND", "10000")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target")
    ap.add_argument("--domain", help="default: the target's 3-letter prefix")
    ap.add_argument("--donor", help="skip donor selection")
    ap.add_argument("--proofs-dir", type=Path)
    ap.add_argument("--node-budget", type=int, default=60)
    ap.add_argument("--final-budget", type=int, default=300)
    ap.add_argument("--top", type=int, default=8, help="deepest N survivors to supply")
    ap.add_argument("--max-nodes", type=int, default=260)
    ap.add_argument("--workers", type=int, default=44)
    a = ap.parse_args()

    domain = a.domain or a.target[:3]
    out = config.LOGS / "transfer_dag" / a.target
    out.mkdir(parents=True, exist_ok=True)
    binary = config.twee_path(deterministic=True)

    sim, donor, path = find_donor(a.target, domain, exclude=(a.target,),
                                  proofs_dir=a.proofs_dir)
    if a.donor:
        donor = a.donor
    if not donor or not path:
        sys.exit(f"no donor with a saved proof for {a.target} in {domain}")
    print(f"{a.target}: donor {donor} (similarity {sim:.3f})", flush=True)

    sketch, d = sketch_from_proof(path.read_text(errors="replace"),
                                  max_nodes=a.max_nodes)
    if not sketch.nodes:
        sys.exit(f"{path} has no parsable proof section")
    print(f"  donor proof: {len(sketch.nodes)} nodes, depth {max(d.values())}; "
          f"verifying against {a.target}'s axioms", flush=True)

    res = verify(a.target, sketch, outdir=out, budget=a.node_budget,
                 scope="parents", workers=a.workers, binary=binary,
                 retry_standalone=False)
    ok = [n for n in res["proved"]]
    print(f"  {len(ok)}/{len(sketch.nodes)} donor lemmas hold in the target's theory",
          flush=True)
    if not ok:
        sys.exit("  nothing transferred")

    top = sorted(ok, key=lambda n: -d[n])[:a.top]
    print(f"  supplying the {len(top)} deepest as axioms: "
          f"{[f'{n}(d{d[n]})' for n in top]}", flush=True)
    finals = attempt(a.target, sketch.equations(top), outdir=out,
                     budget=a.final_budget, binary=binary)
    for f in finals:
        print(f"  FINAL {f['direction']:<18} "
              f"{('PROVED' if f['proved'] else f['result']):<10} {f['cpu']:>7.1f}s",
              flush=True)
    (out / "transfer_dag.json").write_text(json.dumps(
        {"target": a.target, "donor": donor, "similarity": sim,
         "n_nodes": len(sketch.nodes), "n_held": len(ok), "top": top,
         "verify": res["proved"], "final": finals}, indent=2) + "\n")


if __name__ == "__main__":
    main()
