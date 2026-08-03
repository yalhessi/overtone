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
from overtone.agent.dag import DIRECTIONS, Sketch, attempt, cost, verify


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
    final: int = 300
    workers: int = 8


def run_problem(problem, sketch: Sketch, *, outdir: Path, budget=Budget(),
                binary=None, directions=DIRECTIONS):
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
               directions=directions, workers=budget.workers, binary=binary)
    proved = [n for n in sketch.nodes if n in v["proved"]]
    a = attempt(problem, sketch.equations(proved), outdir=outdir / "attempt",
                budget=budget.final, binary=binary, directions=directions)

    slow = {n: c for n, c in v["proved"].items() if c and c >= budget.slow}
    out = {"pipeline": "problem", "problem": problem,
           "proved": any(r["proved"] for r in a),
           "cost": cost(v["results"], a),
           "n_nodes": v["n_nodes"], "n_proved": v["n_proved"],
           "missing": v["missing"], "slow": slow,
           "attempt": a, "baseline": batch.screen_baseline(problem),
           "budget": asdict(budget), "sketch": sketch.to_json()}
    (outdir / "problem.json").write_text(json.dumps(out, indent=2) + "\n")
    return out


def run_theory(sketch: Sketch, targets, *, host, outdir: Path, budget=Budget(),
               binary=None, directions=DIRECTIONS, on_missing="skip"):
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
                 directions=directions, workers=budget.workers, binary=binary)
    proved = [n for n in sketch.nodes if n in lib["proved"]]
    eqs = sketch.equations(proved)

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
        a = attempt(t, eqs, outdir=outdir / "targets", budget=budget.final,
                    binary=binary, directions=directions, label=t)
        best = min((r for r in a if r["proved"]), key=lambda r: r["cpu"],
                   default=None)
        rows[t] = {"contained": True, "missing_axioms": [],
                   "proved": bool(best), "marginal": cost(a),
                   "cpu": best["cpu"] if best else None,
                   "direction": best["direction"] if best else None}
        mark = f"PROVED {best['cpu']:.1f}s" if best else "unproved"
        print(f"  {t:<12} {mark}", flush=True)

    out = {"pipeline": "theory", "host": host,
           "library": {"cost": cost(lib["results"]), "n_nodes": lib["n_nodes"],
                       "n_proved": lib["n_proved"], "missing": lib["missing"]},
           "targets": rows,
           "n_proved": sum(1 for r in rows.values() if r["proved"]),
           "n_targets": len(targets), "budget": asdict(budget),
           "sketch": sketch.to_json()}
    (outdir / "theory.json").write_text(json.dumps(out, indent=2) + "\n")
    return out
