"""What is the goal actually waiting on, and is that thing reachable?

Gold recall was the wrong scoreboard. It scores agreement with a 29-node route
that these searches provably cannot reconstruct -- five of its identities are
derived by no search in any run on record -- so a loop can improve and the
number cannot move. Eleven runs sat between 9 and 11 of 29 while every one of
them failed in the same place.

That place is the **obligation**: the ungrounded node nearest the conjecture.
On a derived RNG029-5 sketch it is the bridge,

    associator(X, Y, multiply(Z, X)) = multiply(X, associator(Y, Z, X))

which turns right Moufang into an associator identity. Every run proves the goal
FROM it in about five seconds and then fails to establish it. So the honest
score is not "how much of the manual library did we rediscover" but "did the
obligation get grounded, and if not, what happened to it".

Two modes.

**report** reads finished runs and says what each was waiting on, how the
obligation failed, and -- the reading that matters -- whether anything ever
proved it CONDITIONALLY, which is how a run fakes success. One run proved the
bridge in 0.009s from four unproved parents, two of which asserted the very
terms it was about to conclude were zero. `dag.grounding` refused it; this makes
that refusal visible next to the score.

**probe** answers the prior question nobody has run: is the obligation reachable
from the scaffold at all? Every run to date attempts it at 60s in both
directions and every one times out -- never `saturated`, so nothing has refuted
it; the search simply is not closing. Timing out at 60s and being unreachable
are very different diagnoses and the loop cannot tell them apart.

That is not the "budget is a diagnostic, not a resource" rule being ignored. The
rule is about refusing to wait out a bad decomposition in order to bank a node.
Nothing here banks anything: the question is whether one specific statement
follows from one specific scaffold at all, and the project has run exactly this
kind of reachability check at 4000s before (RNG025-4/5, and RNG029-5's own
baseline). What comes back changes what the loop should be asked to do -- prove
it at 900s and the job is subdivision, time out at 3600s and the scaffold is
missing a lemma and that is where the mathematics is.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from overtone import config                                      # noqa: E402
from overtone.agent.dag import (Sketch, grounding, unproved_ancestors,  # noqa: E402
                                verify)
from overtone.agent.loop import failure_kind, _contact           # noqa: E402


def _goal_of(sketch):
    return next((n for n in sketch.nodes if n.endswith("goal")), None)


def report(run: Path):
    """What this finished run was waiting on."""
    loop = json.loads((run / "loop.json").read_text())
    sketch = Sketch.from_json(loop["final_sketch"])
    iters = sorted(run.glob("iter*/dag.json"))
    rows = json.loads(iters[-1].read_text())["results"] if iters else []
    ground, cond = grounding(sketch, rows)
    goal = _goal_of(sketch)
    open_chain = unproved_ancestors(sketch, goal, ground) if goal else []

    out = {"run": run.name, "proved": loop.get("proved"),
           "iterations": loop.get("iterations"), "cpu": loop.get("cpu_total"),
           "goal": goal, "frontier": open_chain, "obligations": []}
    # Nearest first, so the head of the chain is the thing standing in the way.
    for name in open_chain[:4]:
        lhs, rhs, parents = sketch.nodes[name]
        mine = [r for r in rows if r["node"] == name]
        out["obligations"].append({
            "node": name, "eq": f"{lhs} = {rhs}",
            "parents": list(parents),
            "failure": failure_kind(mine),
            "attempted": bool(mine),
            # A conditional proof here is the interesting case: it means the run
            # DID close the implication and only its assumptions are missing.
            "conditional_on": list(cond.get(name, ())),
            "contact": (_contact(name, mine) or {}).get("both"),
        })
    return out


def probe(problem, budgets, *, workers=16, scope="parents", binary=None):
    """Run the derived obligation alone at escalating budgets. -> [rows]

    The scaffold is exactly what `derive_sketch` produces, so this asks the
    question the loop asks on iteration 0 and nothing else: given the axioms'
    polarizations and the symmetries they certify, does the obligation follow?
    """
    from overtone.agent.derive import derive_sketch

    sketch, _ = derive_sketch(problem)
    goal = _goal_of(sketch)
    target = unproved_ancestors(sketch, goal, sketch.given)
    obligation = target[0] if target else goal
    lhs, rhs, parents = sketch.nodes[obligation]
    print(f"obligation: {obligation}\n  {lhs} = {rhs}\n  parents: {parents}\n")

    out = []
    for budget in budgets:
        outdir = Path(config.LOGS) / "obligation" / f"{problem}-{budget}s"
        print(f"=== budget {budget}s -> {outdir}", flush=True)
        v = verify(problem, sketch, outdir=outdir, budget=budget,
                   workers=workers, scope=scope, binary=binary,
                   target=obligation)
        rows = [r for r in v["results"] if r["node"] == obligation]
        got = [r for r in rows if r.get("proved")]
        out.append({"budget": budget, "proved": bool(got),
                    "grounded": obligation in v["grounded"],
                    "results": [(r["direction"], r["result"], r["cpu"])
                                for r in rows]})
        print(f"  {obligation}: {'PROVED' if got else 'not proved'} "
              f"{out[-1]['results']}", flush=True)
        if got:
            print("  -> reachable from the derived scaffold. The loop's job is "
                  "to find a decomposition that gets there inside the node "
                  "budget, not to find different mathematics.", flush=True)
            break
    else:
        print("\n  -> NOT reachable from this scaffold at any budget tried. The "
              "scaffold is missing a lemma; that is the mathematics, and no "
              "amount of scheduling or evidence delivery reaches it.", flush=True)
    return out


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", type=Path, nargs="*", help="finished run directories")
    ap.add_argument("--probe", metavar="PROBLEM",
                    help="instead of reporting, run the derived obligation at "
                         "escalating budgets until it proves")
    ap.add_argument("--budgets", default="300,900,3600",
                    help="comma-separated seconds for --probe")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--binary")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if a.probe:
        budgets = [int(x) for x in a.budgets.split(",") if x.strip()]
        res = probe(a.probe, budgets, workers=a.workers,
                    binary=a.binary or config.twee_path(deterministic=True))
        if a.json:
            print(json.dumps(res, indent=2))
        return

    for run in a.runs:
        if not (run / "loop.json").exists():
            continue
        r = report(run)
        if a.json:
            print(json.dumps(r, indent=2))
            continue
        print(f"\n{r['run']}  ({r['iterations']} iter, "
              f"{'PROVED' if r['proved'] else 'not proved'}, {r['cpu']:.0f}s)")
        if not r["frontier"]:
            print("   nothing open: the goal's route is fully grounded")
        for o in r["obligations"]:
            mark = "conditional" if o["conditional_on"] else (o["failure"] or
                                                             "not attempted")
            print(f"   {o['node']:<24} {mark}")
            print(f"      {o['eq'][:96]}")
            if o["conditional_on"]:
                print(f"      closes GIVEN {o['conditional_on'][:4]} -- the "
                      f"implication holds, the assumptions do not")
            if o["contact"] is not None:
                print(f"      goal contact both={o['contact']}")


if __name__ == "__main__":
    main()
