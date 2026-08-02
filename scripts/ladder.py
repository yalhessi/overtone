#!/usr/bin/env python3
"""Run a sketch as a ladder of goals instead of a bag of hints.

docs/SKETCH_LOOP.md argues that twee's hint mechanism cannot steer toward a
waypoint -- `Index.matches` is a discount on arrival, with no gradient -- so a
waypoint only helps if the search happens to reach it. Making each waypoint a
*goal* supplies the missing direction for free: the run's actual goal is the
waypoint, so goal flattening and twee's goal-directedness point at it.

Rung i is: prove waypoint i from the problem's axioms plus waypoints 1..i-1
already proven. Proven rungs are added as axioms, which is sound -- they are
theorems of the same axiom set -- and strictly stronger than a hint. The final
rung is the original conjecture with every proven waypoint available.

Waypoints come from a donor proof's `Lemma N: lhs = rhs` lines, which are
equations and can therefore be goals; the v0 hint terms are rewrite-chain
states, which cannot.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from overtone import runner                                      # noqa: E402
from overtone.runner import BASE_FLAGS                           # noqa: E402
from overtone.problems import problem_path                       # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LEMMA = re.compile(r"^Lemma (\d+): (.+?) = (.+?)\.\s*$")


def donor_lemmas(proof: Path):
    """(number, lhs, rhs) for each lemma in a twee proof, in derivation order."""
    out = []
    for line in proof.read_text(errors="replace").splitlines():
        m = LEMMA.match(line.strip())
        if m:
            out.append((int(m.group(1)), m.group(2).strip(), m.group(3).strip()))
    return out


def norm(s):
    """Compare terms ignoring whitespace and variable names."""
    s = re.sub(r"\s+", "", s)
    return re.sub(r"\b[A-Z][A-Za-z0-9_]*\b", "*", s)


def select_rungs(lemmas, waypoints):
    """Donor lemmas whose either side is one of our waypoint terms.

    The waypoints were extracted as terms from these very lemmas, so this
    recovers the equations they came from -- turning a bag of hints back into
    the ordered ladder it was flattened from.
    """
    want = {norm(w) for w in waypoints}
    picked, seen = [], set()
    for n, lhs, rhs in lemmas:
        if (norm(lhs) in want or norm(rhs) in want) and norm(lhs) not in seen:
            seen.add(norm(lhs))
            picked.append((n, lhs, rhs))
    return picked


VARNAME = re.compile(r"\b([A-Z][A-Za-z0-9_]*)\b")


def skolemise(lhs, rhs):
    """Replace goal variables with fresh constants.

    A CNF negated_conjecture with free variables means "for all X, lhs != rhs",
    so refuting it only needs *some* instantiation -- that proves an instance,
    not the universal law. Promoting the variable-form equation back as an axiom
    would then be unsound. Fresh constants cannot be instantiated, so a proof
    establishes the universal statement and the promotion is sound by
    generalisation.
    """
    names = sorted(set(VARNAME.findall(lhs)) | set(VARNAME.findall(rhs)))
    sub = {v: f"sk_rung_{i}" for i, v in enumerate(names, start=1)}
    rep = lambda s: VARNAME.sub(lambda m: sub.get(m.group(1), m.group(1)), s)
    return rep(lhs), rep(rhs)


def write_rung(problem: str, extra_axioms, goal, dest: Path) -> Path:
    """Problem's axioms + proven lemmas, with `goal` as the conjecture.

    The original negated_conjecture is dropped: each rung has its own goal.
    `include(...)` lines are kept so twee still pulls the theory's axiom file.
    """
    text = problem_path(problem).read_text()
    kept = []
    for role, body in _clauses(text):
        if role != "negated_conjecture":
            kept.append((role, body))
    lines = [l for l in text.splitlines() if l.strip().startswith("include(")]
    for i, (lhs, rhs) in enumerate(extra_axioms, start=1):
        lines.append(f"cnf(rung_{i}, axiom,\n    ( {lhs} = {rhs} )).")
    if goal is not None:
        lhs, rhs = skolemise(*goal)
        lines.append(f"cnf(rung_goal, negated_conjecture,\n    ( {lhs} != {rhs} )).")
    else:
        for role, body in _clauses(text):
            if role == "negated_conjecture":
                lines.append(f"cnf(orig_goal, negated_conjecture,\n    ( {body} )).")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n")
    return dest


def _clauses(text):
    for m in re.finditer(r"cnf\s*\(", text):
        i, depth = m.end(), 1
        while i < len(text) and depth:
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
            i += 1
        parts = text[m.end():i - 1].split(",", 2)
        if len(parts) == 3:
            yield parts[1].strip(), parts[2].strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("problem")
    ap.add_argument("--donor-proof", type=Path, required=True)
    ap.add_argument("--waypoints", type=Path, required=True,
                    help="hints.tptp whose $hint terms name the rungs")
    ap.add_argument("--rung-budget", type=int, default=120)
    ap.add_argument("--final-budget", type=int, default=1000)
    ap.add_argument("--direction", default="--no-flatten-goal")
    ap.add_argument("--outdir", type=Path)
    a = ap.parse_args()

    outdir = a.outdir or (ROOT / "examples" / "sketch_loop" / a.problem / "ladder")
    outdir.mkdir(parents=True, exist_ok=True)

    waypoints = re.findall(r"\$hint\(\s*(.*?)\s*\)\)\.",
                           a.waypoints.read_text(), re.S)
    lemmas = donor_lemmas(a.donor_proof)
    rungs = select_rungs(lemmas, waypoints)
    print(f"{len(waypoints)} waypoints -> {len(rungs)} rungs "
          f"from {len(lemmas)} donor lemmas")
    if not rungs:
        sys.exit("no rungs matched; are the waypoints from this donor proof?")

    flags = [*BASE_FLAGS, a.direction]
    proven, results = [], []
    for i, (n, lhs, rhs) in enumerate(rungs, start=1):
        path = write_rung(a.problem, proven, (lhs, rhs),
                          outdir / f"rung{i:02d}.p")
        r = runner.run(path, flags, a.rung_budget, problem=a.problem)
        results.append({"rung": i, "donor_lemma": n, "eq": f"{lhs} = {rhs}",
                        "result": r.status, "proved": r.proved,
                        "cpu": round(r.cpu, 1)})
        mark = "ok " if r.proved else "FAIL"
        print(f"  rung {i:2d} (lemma {n:3d}) {mark} {r.cpu:6.1f}s  {lhs} = {rhs}",
              flush=True)
        if r.proved:
            proven.append((lhs, rhs))

    print(f"\n{len(proven)}/{len(rungs)} rungs proven; final goal with "
          f"{len(proven)} added axioms")
    path = write_rung(a.problem, proven, None, outdir / "final.p")
    r = runner.run(path, flags, a.final_budget, problem=a.problem)
    (outdir / "final.out").write_text(r.output)
    print(f"  FINAL: {r.status} {r.cpu:.1f}s")

    json.dump({"problem": a.problem, "direction": a.direction,
               "rung_budget": a.rung_budget, "final_budget": a.final_budget,
               "rungs": results, "n_proven": len(proven),
               "final": {"result": r.status, "proved": r.proved,
                         "cpu": round(r.cpu, 1)}},
              open(outdir / "ladder.json", "w"), indent=2)


if __name__ == "__main__":
    main()
