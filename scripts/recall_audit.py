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
    return {eq_key(a, b): n for n, (a, b, _) in mod.SKETCH.nodes.items()}


def route(problem, gold_path=None):
    """The manual proof's own path to `problem`'s conjecture, with its timings.

    A reference for us, never an input to a run. The 29-node library is the
    whole of what was proved; the ROUTE is the much smaller part the conjecture
    actually rests on, and it is what tells us whether a loop is going anywhere.

    On RNG029-5 it is 17 nodes and 309.0s, and the shape is the finding: every
    step is free (<= 1.5s) until the last two, which are 192.6s and 112.2s. So
    "on the right track" does not look like a run proving lots of cheap nodes --
    every arm did that -- it looks like a run holding the five lemmas the
    Moufang step needs and then being allowed the time to take it.
    """
    import importlib.util
    from overtone import problems

    src = Path(gold_path or Path(__file__).with_name("rng_dag.py"))
    spec = importlib.util.spec_from_file_location("_gold", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sk = mod.SKETCH

    c = problems.conjecture(problems.problem_path(problem))
    want = eq_key(*c)
    target = next((n for n, (a, b, _) in sk.nodes.items()
                   if eq_key(a, b) == want), None)
    if target is None:
        return None

    seen = []

    def walk(n):
        for p in sk.nodes[n][2]:
            if p not in seen:
                seen.append(p)
                walk(p)
    walk(target)
    members = set(seen) | {target}
    ordered = [n for n in sk.topological() if n in members]

    # Timings from the archived manual run, when it is on disk.
    times = {}
    dag = Path(mod.OUT) / "dag.json" if hasattr(mod, "OUT") else None
    if dag and dag.exists():
        for r in json.loads(dag.read_text())["results"]:
            if r.get("proved"):
                n, cpu = r["node"], r["cpu"]
                if n not in times or cpu < times[n][0]:
                    times[n] = (cpu, r["direction"])
    return {"problem": problem, "target": target, "nodes": ordered,
            "sketch": sk, "times": times}


def on_route(run: Path, problem, gold_path=None):
    """Where a finished run stands against that route. -> rows, nearest last."""
    r = route(problem, gold_path)
    if r is None:
        return None
    loop, sketch, rows = _final(run)
    bank = evidencelib.load(run)
    if not len(bank):
        for it in sorted(run.glob("iter*/dag.json")):
            bank.update(json.loads(it.read_text())["results"])
    seen_keys = {eq_key(e.lhs, e.rhs) for e in bank.all()}
    have = {eq_key(a, b): n for n, (a, b, _) in sketch.nodes.items()}
    ground, _ = grounding(sketch, rows)

    out = []
    for n in r["nodes"]:
        a, b, _ = r["sketch"].nodes[n]
        k = eq_key(a, b)
        node = have.get(k)
        cpu, direction = r["times"].get(n, (None, None))
        out.append({"gold": n, "eq": f"{a} = {b}", "manual_cpu": cpu,
                    "in_evidence": k in seen_keys, "node": node,
                    "grounded": bool(node and node in ground)})
    return {"run": run.name, "target": r["target"], "rows": out,
            "proved": loop.get("proved")}


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
    nodes = {eq_key(a, b): n for n, (a, b, _) in sketch.nodes.items()}
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


def _show_route(a, problem):
    """The reference, and where each run stands on it."""
    r = route(problem, a.gold)
    if r is None:
        print(f"no node in the manual sketch states {problem}'s conjecture")
        return
    if a.json:
        print(json.dumps({"target": r["target"], "nodes": r["nodes"],
                          "times": {k: v[0] for k, v in r["times"].items()}},
                         indent=2))
        return

    print(f"\nTHE MANUAL ROUTE TO {problem} ({len(r['nodes'])} nodes)")
    print(f"target node: {r['target']}\n")
    total, over = 0.0, []
    for n in r["nodes"]:
        lhs, rhs, ps = r["sketch"].nodes[n]
        cpu, direction = r["times"].get(n, (None, None))
        total += cpu or 0.0
        flag = ""
        if cpu is not None and cpu > a.node_budget:
            flag = f"   <-- OVER a {a.node_budget}s node budget"
            over.append((n, cpu))
        t = f"{cpu:>7.1f}s" if cpu is not None else "      --"
        print(f"  {n:<18} {t}{flag}")
        print(f"      {lhs} = {rhs}")
        if ps:
            print(f"      <- {ps}")
    print(f"\n  total on the route: {total:.1f}s")
    if over:
        print(f"\n  CEILING: {len(over)} step(s) cost more than the {a.node_budget}s "
              f"a run gives a node --")
        for n, cpu in over:
            print(f"     {n} at {cpu:.1f}s")
        print("  A run cannot take these however good its sketch becomes. The "
              "manual proof gave them 300-400s per node via `budgets`.")

    for run in a.run:
        if not (run / "loop.json").exists():
            continue
        st = on_route(run, problem, a.gold)
        got = [x for x in st["rows"] if x["grounded"]]
        near = [x for x in st["rows"] if not x["grounded"] and x["in_evidence"]]
        cold = [x for x in st["rows"] if not x["grounded"] and not x["in_evidence"]]
        print(f"\n{st['run']}: {len(got)}/{len(st['rows'])} of the route grounded")
        if near:
            print(f"   in its evidence, never made a node ({len(near)}): "
                  f"{', '.join(x['gold'] for x in near)}")
        if cold:
            print(f"   never derived at all ({len(cold)}): "
                  f"{', '.join(x['gold'] for x in cold)}")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", type=Path, nargs="*")
    ap.add_argument("--gold", type=Path,
                    help="a python file exposing SKETCH; default scripts/rng_dag.py")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--missing", action="store_true",
                    help="list the gold nodes the search never even produced")
    ap.add_argument("--route", metavar="PROBLEM",
                    help="print the manual proof's own path to that problem's "
                         "conjecture, with its measured timings; with run "
                         "directories, score each against it")
    ap.add_argument("--node-budget", type=int, default=60,
                    help="the budget a run gave each node, for the ceiling "
                         "check against the route's measured times")
    a = ap.parse_args()

    if a.route:
        _show_route(a, a.route)
        return

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
