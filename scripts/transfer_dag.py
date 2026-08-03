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
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from overtone import config, proofs, runner
from overtone.agent.dag import Sketch, verify
from overtone.agent.donors import find_donor

os.environ.setdefault("TWEE_STEPS_PER_SECOND", "10000")
CITE = re.compile(r"by lemma (\d+)")
DIRS = ("--no-flatten-goal", "--flatten-goal")


def donor_dag(proof_text):
    """(statements, citations) keyed by lemma number, plus the goal's citations."""
    section = proofs.proof_section(proof_text)
    stmt, cites, cur, buf = {}, {}, None, []

    def flush():
        if cur is not None:
            cites[cur] = {int(x) for x in CITE.findall("\n".join(buf))}

    for line in section.splitlines():
        m = re.match(r"^Lemma (\d+): (.+?) = (.+?)\.\s*$", line)
        g = re.match(r"^Goal \d+", line)
        if m or g:
            flush()
            cur = int(m.group(1)) if m else "GOAL"
            if m:
                stmt[cur] = (m.group(2).strip(), m.group(3).strip())
            buf = [line]
        else:
            buf.append(line)
    flush()
    return stmt, cites


def depths(stmt, cites):
    d = {}

    def go(n, seen=()):
        if n in d:
            return d[n]
        if n in seen:
            return 0
        ps = [p for p in cites.get(n, ()) if p in stmt]
        d[n] = 1 + max([go(p, seen + (n,)) for p in ps] or [-1])
        return d[n]

    for n in stmt:
        go(n)
    return d


def _binary():
    hits = [p for p in config.ROOT.glob(
        "build/twee-deterministic/dist-newstyle/**/twee")
        if p.is_file() and os.access(p, os.X_OK)]
    if not hits:
        raise RuntimeError("no deterministic twee; see the build script")
    return str(max(hits, key=lambda p: p.stat().st_mtime))


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
    binary = _binary()

    sim, donor, path = find_donor(a.target, domain, exclude=(a.target,),
                                  proofs_dir=a.proofs_dir)
    if a.donor:
        donor = a.donor
    if not donor or not path:
        sys.exit(f"no donor with a saved proof for {a.target} in {domain}")
    print(f"{a.target}: donor {donor} (similarity {sim:.3f})", flush=True)

    stmt, cites = donor_dag(path.read_text(errors="replace"))
    if not stmt:
        sys.exit(f"{path} has no parsable proof section")
    d = depths(stmt, cites)
    keep = sorted(stmt, key=lambda n: d[n])[:a.max_nodes]
    nodes = {f"L{n}": (stmt[n][0], stmt[n][1],
                       [f"L{p}" for p in cites.get(n, ()) if p in keep and p != n])
             for n in keep}
    sketch = Sketch(nodes)
    print(f"  donor proof: {len(stmt)} lemmas, depth {max(d.values())}; "
          f"verifying {len(nodes)} nodes against {a.target}'s axioms", flush=True)

    res = verify(a.target, sketch, outdir=out, budget=a.node_budget,
                 scope="parents", workers=a.workers, binary=binary,
                 retry_standalone=False)
    ok = [int(n[1:]) for n in res["proved"]]
    print(f"  {len(ok)}/{len(nodes)} donor lemmas hold in the target's theory",
          flush=True)
    if not ok:
        sys.exit("  nothing transferred")

    top = sorted(ok, key=lambda n: -d[n])[:a.top]
    eqs = [stmt[n] for n in top]
    print(f"  supplying the {len(top)} deepest as axioms: "
          f"{[f'L{n}(d{d[n]})' for n in top]}", flush=True)

    from concurrent.futures import ProcessPoolExecutor
    jobs = [(a.target, direc, tuple(eqs), a.final_budget, str(out), binary)
            for direc in DIRS]
    with ProcessPoolExecutor(max_workers=2) as pool:
        finals = list(pool.map(_final, jobs))
    for f in finals:
        print(f"  FINAL {f['direction']:<18} "
              f"{('PROVED' if f['proved'] else f['result']):<10} {f['cpu']:>7.1f}s",
              flush=True)
    (out / "transfer_dag.json").write_text(json.dumps(
        {"target": a.target, "donor": donor, "similarity": sim,
         "n_nodes": len(nodes), "n_held": len(ok), "top": top,
         "verify": res["proved"], "final": finals}, indent=2) + "\n")


def _final(x):
    target, direc, eqs, budget, outdir, binary = x
    p = runner.write_problem(target, Path(outdir) / f"final.{direc[2:]}.p",
                             extra_axioms=list(eqs), axiom_prefix="donor")
    r = runner.run(p, [*runner.BASE_FLAGS, direc], budget, problem=target,
                   binary=binary)
    if r.proved:
        (Path(outdir) / f"final.{direc[2:]}.out").write_text(r.output)
    return {"direction": direc, "result": r.status, "proved": r.proved,
            "cpu": round(r.cpu, 1)}


if __name__ == "__main__":
    main()
