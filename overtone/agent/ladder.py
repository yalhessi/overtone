"""Run a sketch as a ladder of goals instead of a bag of hints.

twee's hint mechanism cannot steer *toward* a waypoint -- `Index.matches` is a
discount on arrival, with no gradient -- so a waypoint only helps if the search
happens to reach it. Making each waypoint a goal supplies the missing direction:
the run's actual goal is the waypoint, so goal flattening and twee's
goal-directedness point at it.

Rungs come from a donor proof's `Lemma N: lhs = rhs` lines, which are equations
and can therefore be goals; the v0 hint terms are rewrite-chain states, which
cannot.

Two things about *how* the rungs are run matter more than the decomposition did.

**Verify standalone, do not chain.** Carrying proven lemmas into the next rung
is the ladder's original premise and it is what made it slow. Each added
equation enlarges the rewrite system, and the penalty compounds with depth --
measured on MVA005-1 at 1.9x with 12 prior lemmas and 10.2x with 18:

    rung 16 (lemma 227)   22.4s standalone    143.4s with 15 prior as axioms
    rung 20 (lemma 269)   11.5s standalone    117.3s with 18 prior as axioms

Over all 20 rungs: 94.3s standalone proving 20/20, against 324.9s chained
proving 19/20 -- chaining is 3.4x more expensive *and* fails on a lemma that
takes 22.4s alone. Standalone rungs are also independent, so they parallelise;
a chain cannot. Three of the twenty rungs are genuinely faster chained (their
predecessors are real shortcuts), but they save ~22s against ~250s lost.

**Promote as hints, not axioms.** Same mechanism at the final run:

    20 lemmas as axioms  -> Timeout at 1001.7s
    the same as hints    -> proved in 173.6s

An axiom enlarges the rewrite system and forms critical pairs with every
existing rule; a hint only reweights scoring. "Sound and strictly stronger" is
true logically and false operationally.
"""
import json
from concurrent.futures import ProcessPoolExecutor
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


def _verify_one(job):
    """Prove one rung from the problem's own axioms. Module-level so it pickles."""
    problem, i, n, lhs, rhs, outdir, budget, flags, binary = job
    path = write_rung(problem, [], (lhs, rhs), Path(outdir) / f"rung{i:02d}.p")
    r = runner.run(path, list(flags), budget, problem=problem, binary=binary)
    return {"rung": i, "donor_lemma": n, "eq": f"{lhs} = {rhs}",
            "result": r.status, "proved": r.proved, "cpu": round(r.cpu, 1)}


def run_ladder(problem, donor_proof: Path, waypoints, *, rung_budget=120,
               final_budget=1000, direction="--no-flatten-goal",
               promote="hints", verify="standalone", outdir: Path,
               binary: str | None = None, workers: int = 1):
    """Prove each rung, then the original goal with everything proven so far.

    `promote` decides how proven rungs reach the final run: "hints" (default,
    3.1x faster on MVA005-1) or "axioms" (what the first implementation did).

    `verify` is "standalone" (default -- each rung proved from the problem's own
    axioms) or "chained" (each rung also gets the previously proven lemmas as
    axioms, the original design). See the module docstring for why standalone
    wins; `workers` > 1 parallelises it, which chaining cannot do.

    `binary` selects a twee build. A ladder is 20+ related problems of graded
    difficulty over one theory, so it is a far better test bed than a single
    problem for anything that changes prover behaviour.
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
    if verify == "standalone" and workers > 1:
        jobs = [(problem, i, n, lhs, rhs, str(outdir), rung_budget,
                 tuple(flags), binary) for i, (n, lhs, rhs)
                in enumerate(rungs, start=1)]
        with ProcessPoolExecutor(max_workers=workers) as pool:
            results = sorted(pool.map(_verify_one, jobs), key=lambda r: r["rung"])
        for r in results:
            print(f"  rung {r['rung']:2d} (lemma {r['donor_lemma']:3d}) "
                  f"{'ok ' if r['proved'] else 'FAIL'} {r['cpu']:6.1f}s  {r['eq']}")
            if r["proved"]:
                lhs, rhs = r["eq"].split(" = ", 1)
                proven.append((lhs, rhs))
    else:
        for i, (n, lhs, rhs) in enumerate(rungs, start=1):
            prior = proven if verify == "chained" else []
            path = write_rung(problem, prior, (lhs, rhs),
                              outdir / f"rung{i:02d}.p")
            r = runner.run(path, flags, rung_budget, problem=problem,
                           binary=binary)
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
    r = runner.run(path, final_flags, final_budget, problem=problem,
                   binary=binary)
    (outdir / "final.out").write_text(r.output)
    print(f"  FINAL: {r.status} {r.cpu:.1f}s")

    out = {"problem": problem, "direction": direction, "promote": promote,
           "verify": verify, "binary": binary or "stock",
           "rung_budget": rung_budget, "final_budget": final_budget,
           "rungs": results, "n_proven": len(proven),
           "rung_cpu": round(sum(x["cpu"] for x in results), 1),
           "final": {"result": r.status, "proved": r.proved,
                     "cpu": round(r.cpu, 1)}}
    (outdir / "ladder.json").write_text(json.dumps(out, indent=2) + "\n")
    return out
