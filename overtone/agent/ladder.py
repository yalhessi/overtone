"""Run a sketch as a ladder of goals instead of a bag of hints.

twee's hint mechanism cannot steer *toward* a waypoint -- `Index.matches` is a
discount on arrival, with no gradient -- so a waypoint only helps if the search
happens to reach it. Making each waypoint a goal supplies the missing direction:
the run's actual goal is the waypoint, so goal flattening and twee's
goal-directedness point at it.

Rungs come from a donor proof's `Lemma N: lhs = rhs` lines, which are equations
and can therefore be goals; the v0 hint terms are rewrite-chain states, which
cannot.

How proven rungs are carried forward matters more than the decomposition did.
Measured on MVA005-1 (docs/FINDINGS.md):

    20 lemmas as axioms  -> Timeout at 1001.7s
    the same as hints    -> proved in 173.6s

An axiom enlarges the rewrite system and forms critical pairs with every
existing rule; a hint only reweights scoring. "Sound and strictly stronger" is
true logically and false operationally, so `promote="hints"` is the default.
"""
import json
from pathlib import Path

from overtone import proofs, runner
from overtone.agent import hints as hintlib
from overtone.runner import BASE_FLAGS
from overtone.terms import alpha_key


def select_rungs(lemmas, waypoints):
    """Donor lemmas whose either side is one of our waypoint terms.

    The waypoints were extracted as terms from these very lemmas, so this
    recovers the equations they came from -- turning a bag of hints back into
    the ordered ladder it was flattened from.
    """
    want = {alpha_key(w) for w in waypoints}
    picked, seen = [], set()
    for n, lhs, rhs in lemmas:
        key = alpha_key(lhs)
        if (key in want or alpha_key(rhs) in want) and key not in seen:
            seen.add(key)
            picked.append((n, lhs, rhs))
    return picked


def write_rung(problem, proven, goal, dest: Path) -> Path:
    """Problem + proven lemmas as axioms, with `goal` as the conjecture.

    Delegates to `runner.write_problem`, which keeps the problem's own clauses.
    The earlier local version emitted only the `include(...)` lines, so any
    problem carrying its axioms inline rather than via an axiom file lost them.
    """
    return runner.write_problem(problem, dest, extra_axioms=proven, goal=goal,
                                goal_prefix="sk_rung_", axiom_prefix="rung")


def run_ladder(problem, donor_proof: Path, waypoints, *, rung_budget=120,
               final_budget=1000, direction="--no-flatten-goal",
               promote="hints", outdir: Path):
    """Prove each rung, then the original goal with everything proven so far.

    `promote` decides how proven rungs reach the final run: "hints" (default,
    3.1x faster on MVA005-1) or "axioms" (what the first implementation did).
    """
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    lemmas = proofs.lemmas(Path(donor_proof).read_text(errors="replace"))
    rungs = select_rungs(lemmas, waypoints)
    print(f"{len(waypoints)} waypoints -> {len(rungs)} rungs "
          f"from {len(lemmas)} donor lemmas")
    if not rungs:
        raise ValueError("no rungs matched; are the waypoints from this donor?")

    flags = [*BASE_FLAGS, direction]
    proven, results = [], []
    for i, (n, lhs, rhs) in enumerate(rungs, start=1):
        path = write_rung(problem, proven, (lhs, rhs), outdir / f"rung{i:02d}.p")
        r = runner.run(path, flags, rung_budget, problem=problem)
        results.append({"rung": i, "donor_lemma": n, "eq": f"{lhs} = {rhs}",
                        "result": r.status, "proved": r.proved,
                        "cpu": round(r.cpu, 1)})
        print(f"  rung {i:2d} (lemma {n:3d}) {'ok ' if r.proved else 'FAIL'} "
              f"{r.cpu:6.1f}s  {lhs} = {rhs}", flush=True)
        if r.proved:
            proven.append((lhs, rhs))

    print(f"\n{len(proven)}/{len(rungs)} rungs proven; final goal with "
          f"{len(proven)} lemmas as {promote}")
    if promote == "axioms":
        path = write_rung(problem, proven, None, outdir / "final.p")
        final_flags = flags
    else:
        terms = []
        for lhs, rhs in proven:
            terms += [t for t in (lhs, rhs) if "(" in t and t not in terms]
        path = runner.write_problem(problem, outdir / "final.p", hints=terms)
        final_flags = [*BASE_FLAGS, *hintlib.HINT_FLAGS, direction]
    r = runner.run(path, final_flags, final_budget, problem=problem)
    (outdir / "final.out").write_text(r.output)
    print(f"  FINAL: {r.status} {r.cpu:.1f}s")

    out = {"problem": problem, "direction": direction, "promote": promote,
           "rung_budget": rung_budget, "final_budget": final_budget,
           "rungs": results, "n_proven": len(proven),
           "rung_cpu": round(sum(x["cpu"] for x in results), 1),
           "final": {"result": r.status, "proved": r.proved,
                     "cpu": round(r.cpu, 1)}}
    (outdir / "ladder.json").write_text(json.dumps(out, indent=2) + "\n")
    return out
