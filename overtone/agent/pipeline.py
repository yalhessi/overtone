"""Two ways to run a sketch, separated because they answer different questions.

The RNG work ran them as one activity -- draft a theory, verify it, attack twelve
problems at once -- and that conflation cost two things.

**Cost became unattributable.** Six lemmas took ~1122s and flipped ten problems.
That is 112s per problem, or 1122s for the first and nothing for the rest, or
1122s each. Nothing forced a choice, because no problem was ever solved alone.

**Encodings drifted.** Sharing a library across a family invites restating a
lemma in whatever form the prover likes, and twee is sensitive enough to encoding
that "equivalent" stops being a safe word. Our `left_moufang` node states
`((xy)x)z = x(y(xz))` where RNG028-7 states `(x(yx))z = x(y(xz))`; they differ by
the flexible law, and one is not the other.

`run_problem` answers "is this problem reachable, and what did it cost" -- one
problem, one number, nothing shared. `run_theory` answers "does a library pay for
itself across a family" -- sharing allowed, two numbers, never summed.

Both are about **reachability**: problems out of reach at 4000s in either goal
direction becoming reachable at all. A larger per-problem cost is an acceptable
price and is reported rather than hidden.
"""
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from overtone import batch, problems
from overtone.agent import blueprint
from overtone.agent.dag import DIRECTIONS, Sketch, attempt, cost, verify
from overtone.terms import eq_key


@dataclass(frozen=True)
class Budget:
    """Node budget is a *diagnostic*, not a resource.

    Every node of a correct decomposition verifies in seconds; the one that did
    not (32.9s) was missing a node beneath it, and supplying it gave 18x. So a
    node over `slow` is reported as suspect even when it proves, and a timeout
    means revise the sketch rather than wait longer. `final` is the budget the
    baseline resisted, so a proof there is a real comparison.
    """
    node: int = 60
    slow: int = 30
    # A node may still need more than `node` -- `right_moufang` takes 192.6s --
    # and a sketch says so per node via `budgets`. That is not a licence to wait
    # out a bad decomposition: anything over `slow` is still reported as suspect,
    # so an oversized budget is visible rather than absorbed.
    final: int = 300
    # Nodes in flight. `verify` keeps this many slots full across the whole DAG,
    # and each one forks up to 2 twee processes to race the goal directions -- so
    # 16 is up to 32 processes. That ceiling is not about throughput: `runner.run`
    # enforces the budget on WALL CLOCK, so oversubscribing the box does not slow
    # runs down, it silently shortens every budget in flight and makes a starved
    # node look unprovable. Keep 2 x workers comfortably under the core count.
    workers: int = 16


def run_problem(problem, sketch: Sketch, *, outdir: Path, budget=Budget(),
                budgets=None, binary=None, directions=DIRECTIONS,
                reuse=True, ledger=None):
    """Pipeline A: one problem, one honest cost.

    Four rules, each enforced here rather than by convention:

    1. The problem file is immutable -- `attempt` supplies no goal, so the
       original negated_conjecture survives and what is proved is the problem as
       TPTP states it.
    2. Every lemma is verified against *this problem's own axioms*, because
       `verify` is called with this problem as the host.
    3. Cost is everything spent, failures and both goal directions included.
    4. No cross-problem state: `known` and `prior_results` are deliberately not
       accepted, so there is no parameter through which another problem's
       library could arrive.
    """
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    v = verify(problem, sketch, outdir=outdir / "nodes", budget=budget.node,
               budgets=budgets, directions=directions, workers=budget.workers,
               binary=binary, reuse=reuse, ledger=ledger)
    # GROUNDED, not merely proved. `verify` now attempts every claim, so a node
    # can verify while something it rests on has not -- an implication, not a
    # theorem here. Supplying one to the problem's own file would prove the
    # conjecture from an unproved assumption and report it as rule 1 of this
    # pipeline ("the problem file is immutable") being satisfied, which it would
    # not be. `v["grounded"]` is the set with a chain back to the axioms.
    proved = [n for n in sketch.nodes if n in v["grounded"]]
    a = attempt(problem, sketch.equations(proved), outdir=outdir / "attempt",
                budget=budget.final, binary=binary, directions=directions,
                reuse=reuse, ledger=ledger)

    reused = sum(1 for r in v["results"] + a if r.get("reused"))
    slow = {n: c for n, c in v["proved"].items() if c and c >= budget.slow}
    out = {"pipeline": "problem", "problem": problem,
           "proved": any(r["proved"] for r in a),
           "cost": cost(v["results"], a),
           "n_nodes": v["n_nodes"], "n_proved": v["n_proved"],
           "missing": v["missing"], "slow": slow, "n_reused": reused,
           "attempt": a, "baseline": batch.screen_baseline(problem),
           "budget": asdict(budget), "sketch": sketch.to_json()}
    (outdir / "problem.json").write_text(json.dumps(out, indent=2) + "\n")
    blueprint.write_for_run(
        sketch, v["results"], outdir, run_dir=outdir / "nodes",
        title=f"{problem} — per problem",
        subtitle=(f"{v['n_proved']}/{v['n_nodes']} nodes · "
                  f"{'proved' if out['proved'] else 'not proved'} · "
                  f"{out['cost']['cpu']:.0f}s CPU over {out['cost']['n_runs']} runs"))
    return out


def _states(sketch: Sketch, node, target):
    """Is this node the target's own conjecture?"""
    c = problems.conjecture(problems.problem_path(target))
    if c is None:
        return False
    lhs, rhs, _ = sketch.nodes[node]
    return eq_key(lhs, rhs) == eq_key(*c)


def run_theory(sketch: Sketch, targets, *, host, outdir: Path, budget=Budget(),
               budgets=None, binary=None, directions=DIRECTIONS,
               on_missing="skip", reuse=True, ledger=None):
    """Pipeline B: a library once, a marginal cost per target.

    Reports **two** numbers and never adds them: what the library cost to derive,
    and what each target cost given it. A single blended figure is what made the
    RNG result unattributable.

    Containment is asserted per target before any lemma is supplied. A lemma
    proved from `host`'s axioms is a theorem of a target's theory only if that
    theory is at least as strong; RNG027-10 and RNG029-10 drop three and four of
    RNG029-5's axioms, and skipping this check is exactly how they were briefly
    claimed. `on_missing="skip"` records the reason and attempts nothing.
    """
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    lib = verify(host, sketch, outdir=outdir / "library", budget=budget.node,
                 budgets=budgets, directions=directions, workers=budget.workers,
                 binary=binary, reuse=reuse, ledger=ledger)
    # Grounded only, for the same reason `run_problem` insists on it and a
    # sharper one: a library lemma travels to OTHER problems. A conditional one
    # would carry its unproved assumption with it, silently, into every target
    # it is supplied to -- containment checks the axioms and would not catch it.
    proved = [n for n in sketch.nodes if n in lib["grounded"]]

    rows = {}
    for t in targets:
        ok, missing = problems.contains_axioms(t, host)
        if not ok:
            rows[t] = {"contained": False, "missing_axioms": missing,
                       "proved": False, "marginal": None,
                       "why": (f"{t} lacks {len(missing)} of {host}'s axioms, so "
                               f"these lemmas are assumptions there, not lemmas")}
            print(f"  {t:<12} SKIPPED -- missing {len(missing)} axioms", flush=True)
            continue
        # A library must not contain the theorem it is being used to prove.
        # This sketch has nodes that *are* target conjectures -- middle_moufang
        # is RNG029-5 -- and handing a problem its own statement proves it in
        # 0.0s while saying nothing. It is sound (the node was verified from the
        # host's axioms) and it is vacuous, so the marginal cost would be a
        # fiction. Dropping it puts the work back where it happened.
        supply = [n for n in proved if not _states(sketch, n, t)]
        dropped = [n for n in proved if n not in supply]
        a = attempt(t, sketch.equations(supply), outdir=outdir / "targets",
                    budget=budget.final, binary=binary, directions=directions,
                    label=t, reuse=reuse, ledger=ledger)
        best = min((r for r in a if r["proved"]), key=lambda r: r["cpu"],
                   default=None)
        rows[t] = {"contained": True, "missing_axioms": [],
                   "proved": bool(best), "marginal": cost(a),
                   "n_supplied": len(supply), "excluded_as_target": dropped,
                   "cpu": best["cpu"] if best else None,
                   "direction": best["direction"] if best else None}
        mark = f"PROVED {best['cpu']:.1f}s" if best else "unproved"
        drop = f"  (excluding {', '.join(dropped)})" if dropped else ""
        print(f"  {t:<12} {mark}{drop}", flush=True)

    out = {"pipeline": "theory", "host": host,
           "library": {"cost": cost(lib["results"]), "n_nodes": lib["n_nodes"],
                       "n_proved": lib["n_proved"], "missing": lib["missing"]},
           "targets": rows,
           "n_proved": sum(1 for r in rows.values() if r["proved"]),
           "n_targets": len(targets), "budget": asdict(budget),
           "sketch": sketch.to_json()}
    (outdir / "theory.json").write_text(json.dumps(out, indent=2) + "\n")
    blueprint.write_for_run(
        sketch, lib["results"], outdir, run_dir=outdir / "library",
        title=f"{host} — theory library",
        subtitle=(f"{lib['n_proved']}/{lib['n_nodes']} nodes · "
                  f"{out['n_proved']}/{out['n_targets']} targets · "
                  f"library {out['library']['cost']['cpu']:.0f}s CPU"))
    return out
