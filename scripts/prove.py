#!/usr/bin/env python3
"""Pipeline A -- solve one problem, and report what it actually cost.

    ./scripts/prove.py RNG029-5 --sketch data/sketches/rng_alt.json
    ./scripts/prove.py RNG014-6 --sketch scripts/rng_dag.py --final-budget 60

Nothing is shared with any other problem: every lemma is verified against this
problem's own axioms in this run, and the cost reported is everything spent,
failures and both goal directions included. Expect that number to be far larger
than a theory run's marginal cost -- the whole sketch is charged here, which is
the point.

The problem file is never rewritten. The final attempt appends lemmas as axioms
to the original, so what is proved is the problem as TPTP states it.
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from overtone import config
from overtone.agent.dag import Sketch
from overtone.agent.pipeline import Budget, run_problem


def load_sketch(path: Path) -> Sketch:
    """A sketch from JSON, or from a module defining SKETCH or DAG."""
    if path.suffix == ".json":
        return Sketch.from_json(json.loads(path.read_text()))
    spec = importlib.util.spec_from_file_location("_sketch", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if hasattr(mod, "SKETCH"):
        return mod.SKETCH
    if hasattr(mod, "DAG"):
        return Sketch(mod.DAG)
    sys.exit(f"{path} defines neither SKETCH nor DAG")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("problem")
    ap.add_argument("--sketch", type=Path, required=True)
    ap.add_argument("--node-budget", type=int, default=60)
    ap.add_argument("--final-budget", type=int, default=300)
    ap.add_argument("--slow", type=int, default=30)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--outdir", type=Path)
    ap.add_argument("--binary", help="default: the deterministic build")
    a = ap.parse_args()

    outdir = a.outdir or (config.LOGS / "prove" / a.problem)
    budget = Budget(node=a.node_budget, slow=a.slow, final=a.final_budget,
                    workers=a.workers)
    try:
        sketch = load_sketch(a.sketch)
        binary = a.binary or config.twee_path(deterministic=True)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        sys.exit(str(e))

    print(f"{a.problem}: {len(sketch.nodes)} nodes, node budget {budget.node}s, "
          f"final {budget.final}s", flush=True)
    out = run_problem(a.problem, sketch, outdir=outdir, budget=budget,
                      binary=binary)

    print(f"\n  nodes proved   {out['n_proved']}/{out['n_nodes']}")
    for n in out["missing"]:
        print(f"  MISSING:       {n}")
    for n, c in sorted(out["slow"].items(), key=lambda kv: -kv[1]):
        print(f"  SLOW:          {n} at {c:.1f}s -- mine its proof for a missing node")
    print(f"  {'PROVED' if out['proved'] else 'NOT PROVED'}")
    c = out["cost"]
    print(f"  total cost     {c['cpu']:.1f}s CPU over {c['n_runs']} runs "
          f"({c['n_failed']} failed)")
    if out["baseline"]:
        print(f"  baseline       {out['baseline']}")
    print(f"  -> {outdir}/problem.json")


if __name__ == "__main__":
    main()
