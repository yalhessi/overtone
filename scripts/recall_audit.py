"""How much of a known-good decomposition did a run actually reach?

Gold, AFTER THE FACT. `scripts/rng_dag.py` holds the 29-node library that is the
one real result this project has produced, and a loop run under the no-retrieval
constraint must never see it. This reads it only to score a run that has already
finished, which is the difference between a benchmark and a leak -- and it is
why this lives in a script that nothing in `overtone/agent/` imports.

Three numbers, never summed, in the shape `run_theory` already uses for a reason:

  surfaced   the equation appears somewhere in the run's evidence bank. The
             search found it. Whether the planner could SEE it is the question
             `agent/evidence.py` exists to answer -- before that module, eight
             equations per node reached the model out of ~2,000 per artifact.
  promoted   the planner turned it into a node. It looked at the evidence and
             chose this.
  grounded   the node verified with a proved chain back to the axioms. It is a
             theorem of the problem, not an implication.

They are strictly nested, so the gaps between them say where a run lost the
thread: surfaced-but-not-promoted is an attention failure, promoted-but-not-
grounded is a mathematics failure, and never-surfaced means the search did not
produce it at all and no amount of better reading would have helped.

    python scripts/recall_audit.py logs/loop/RNG029-5-derive-01
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from overtone.agent import evidence as evidencelib          # noqa: E402
from overtone.agent.dag import Sketch, grounding            # noqa: E402
from overtone.terms import eq_key                           # noqa: E402


def gold(path=None):
    """The manual sketch, as {eq_key: name}. Loaded by path, never imported."""
    import importlib.util
    src = Path(path or Path(__file__).with_name("rng_dag.py"))
    spec = importlib.util.spec_from_file_location("_gold", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return {eq_key(l, r): n for n, (l, r, _) in mod.SKETCH.nodes.items()}


def _final(run: Path):
    """The run's last sketch and the verification rows behind it."""
    loop = json.loads((run / "loop.json").read_text())
    sketch = Sketch.from_json(loop["final_sketch"])
    iters = sorted(run.glob("iter*/dag.json"))
    rows = json.loads(iters[-1].read_text())["results"] if iters else []
    return loop, sketch, rows


def audit(run: Path, gold_path=None):
    run = Path(run)
    want = gold(gold_path)
    loop, sketch, rows = _final(run)

    bank = evidencelib.load(run)
    if not len(bank):
        # A run finished before the bank existed. Mine its artifacts now -- they
        # are still on disk, and the whole point of an after-the-fact audit is
        # that it can be run on the archive.
        for it in sorted(run.glob("iter*/dag.json")):
            bank.update(json.loads(it.read_text())["results"])

    seen = {eq_key(e.lhs, e.rhs) for e in bank.all()}
    nodes = {eq_key(l, r): n for n, (l, r, _) in sketch.nodes.items()}
    ground, _ = grounding(sketch, rows)

    out = []
    for key, name in want.items():
        node = nodes.get(key)
        out.append({"gold": name, "surfaced": key in seen,
                    "promoted": node, "grounded": bool(node and node in ground)})
    return {"run": str(run), "n_gold": len(want),
            "n_surfaced": sum(1 for r in out if r["surfaced"]),
            "n_promoted": sum(1 for r in out if r["promoted"]),
            "n_grounded": sum(1 for r in out if r["grounded"]),
            "n_evidence": len(bank), "proved": loop.get("proved"),
            "iterations": loop.get("iterations"), "rows": out}


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", type=Path, nargs="+")
    ap.add_argument("--gold", type=Path,
                    help="a python file exposing SKETCH; default scripts/rng_dag.py")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--missing", action="store_true",
                    help="list the gold nodes the search never even produced")
    a = ap.parse_args()

    for run in a.run:
        r = audit(run, a.gold)
        if a.json:
            print(json.dumps(r, indent=2))
            continue
        print(f"\n{r['run']}  ({r['iterations']} iteration(s), "
              f"{'proved' if r['proved'] else 'not proved'})")
        print(f"  evidence bank: {r['n_evidence']} equations")
        # Never summed and never averaged into one score: the gaps between them
        # are the whole reading.
        print(f"  surfaced  {r['n_surfaced']:>3}/{r['n_gold']}   "
              f"the search produced it")
        print(f"  promoted  {r['n_promoted']:>3}/{r['n_gold']}   "
              f"the planner made it a node")
        print(f"  grounded  {r['n_grounded']:>3}/{r['n_gold']}   "
              f"it verified back to the axioms")
        lost = [x["gold"] for x in r["rows"]
                if x["surfaced"] and not x["promoted"]]
        if lost:
            print(f"  surfaced but never promoted ({len(lost)}): "
                  f"{', '.join(sorted(lost)[:8])}"
                  + (" ..." if len(lost) > 8 else ""))
        if a.missing:
            never = sorted(x["gold"] for x in r["rows"] if not x["surfaced"])
            print(f"  never produced by any search ({len(never)}): "
                  f"{', '.join(never)}")


if __name__ == "__main__":
    main()
