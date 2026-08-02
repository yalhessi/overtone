#!/usr/bin/env python3
"""Does a drafted lemma library transfer across a whole theory?

11 of the 13 resisted RNG problems share `Axioms/RNG003-0.ax` (alternative
rings), so one drafted library applies to all of them. That turns "does drafting
generalise" into a cheap test: draft once, attempt ten.

Two jobs:

  1. Verify the library in BOTH goal directions. Iterations 1 and 2 ran only
     --no-flatten-goal and concluded several lemmas were unprovable; assoc_add_1
     then proved in 26.0s under --flatten-goal, with 1565 rules touching the goal
     where the other direction derived 3862 rules and touched it zero times.
     Every earlier negative is therefore suspect.
  2. Attempt all the problems with whatever verified, both directions, at 4000s
     -- the same budget the baseline resisted, so a proof is a real flip.

Runs on the deterministic build, which matters here: parallelism inflates
wall-clock but cannot change any outcome, so the pool size is free to choose.
"""
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from overtone import config, runner
from overtone.agent.hints import HINT_FLAGS

os.environ.setdefault("TWEE_STEPS_PER_SECOND", "10000")
OUT = config.LOGS / "overnight"
DIRS = ("--no-flatten-goal", "--flatten-goal")

# Drafted for alternative rings: the classical route to the Moufang identities
# (associator alternating -> flexible law -> Moufang), plus the sign and
# linearity lemmas twee needs to get there.
LIBRARY = [
    ("neg_mult_r", "multiply(X,additive_inverse(Y))", "additive_inverse(multiply(X,Y))"),
    ("neg_mult_l", "multiply(additive_inverse(X),Y)", "additive_inverse(multiply(X,Y))"),
    ("neg_add", "additive_inverse(add(X,Y))", "add(additive_inverse(X),additive_inverse(Y))"),
    ("cancel_r", "add(add(X,Y),additive_inverse(Y))", "X"),
    ("assoc_xxy", "associator(X,X,Y)", "additive_identity"),
    ("assoc_xyy", "associator(X,Y,Y)", "additive_identity"),
    ("assoc_xyx", "associator(X,Y,X)", "additive_identity"),
    ("flexible", "multiply(multiply(X,Y),X)", "multiply(X,multiply(Y,X))"),
    ("assoc_add_1", "associator(add(X,Y),Z,W)", "add(associator(X,Z,W),associator(Y,Z,W))"),
    ("assoc_add_2", "associator(X,add(Y,Z),W)", "add(associator(X,Y,W),associator(X,Z,W))"),
    ("assoc_add_3", "associator(X,Y,add(Z,W))", "add(associator(X,Y,Z),associator(X,Y,W))"),
    ("lin_left_inst", "associator(add(X,Y),add(X,Y),Z)", "additive_identity"),
    ("lin_right_inst", "associator(X,add(Y,Z),add(Y,Z))", "additive_identity"),
    ("alt12_additive", "add(associator(X,Y,Z),associator(Y,X,Z))", "additive_identity"),
    ("alt23_additive", "add(associator(X,Y,Z),associator(X,Z,Y))", "additive_identity"),
    ("assoc_alt_12", "associator(X,Y,Z)", "additive_inverse(associator(Y,X,Z))"),
    ("assoc_alt_23", "associator(X,Y,Z)", "additive_inverse(associator(X,Z,Y))"),
    ("left_moufang", "multiply(multiply(multiply(X,Y),X),Z)",
     "multiply(X,multiply(Y,multiply(X,Z)))"),
    ("right_moufang", "multiply(Z,multiply(multiply(X,Y),X))",
     "multiply(multiply(multiply(Z,X),Y),X)"),
]

# Any problem over these axioms serves as the host for verifying the library.
HOST = "RNG029-5"
TARGETS = ["RNG025-5", "RNG027-7", "RNG027-8", "RNG027-9", "RNG028-7",
           "RNG028-8", "RNG028-9", "RNG029-5", "RNG029-6", "RNG029-7"]


def _binary():
    hits = [p for p in config.ROOT.glob(
        "build/twee-deterministic/dist-newstyle/**/twee")
        if p.is_file() and os.access(p, os.X_OK)]
    if not hits:
        raise RuntimeError("no deterministic twee; see the build script")
    return str(max(hits, key=lambda p: p.stat().st_mtime))


BIN = _binary()


def verify_job(a):
    name, lhs, rhs, direc, budget = a
    p = runner.write_problem(HOST, OUT / "verify" / f"{name}.{direc[2:]}.p",
                             goal=(lhs, rhs), goal_prefix="sk_lib_")
    r = runner.run(p, [*runner.BASE_FLAGS, direc], budget, problem=HOST,
                   binary=BIN)
    return {"lemma": name, "direction": direc, "result": r.status,
            "proved": r.proved, "cpu": round(r.cpu, 1)}


def attempt_job(a):
    prob, direc, hints, budget = a
    p = runner.write_problem(prob, OUT / "attempt" / f"{prob}.{direc[2:]}.p",
                             hints=list(hints))
    r = runner.run(p, [*runner.BASE_FLAGS, *HINT_FLAGS, direc], budget,
                   problem=prob, binary=BIN)
    if r.proved:
        (OUT / "attempt" / f"{prob}.{direc[2:]}.out").write_text(r.output)
    return {"problem": prob, "direction": direc, "result": r.status,
            "proved": r.proved, "cpu": round(r.cpu, 1), "n_hints": len(hints)}


def main():
    (OUT / "verify").mkdir(parents=True, exist_ok=True)
    (OUT / "attempt").mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    print(f"JOB 1: verify {len(LIBRARY)} lemmas, both directions, 300s",
          flush=True)
    jobs = [(n, l, r, d, 300) for n, l, r in LIBRARY for d in DIRS]
    with ProcessPoolExecutor(max_workers=10) as pool:
        vres = list(pool.map(verify_job, jobs))
    best = {}
    for v in vres:
        if v["proved"] and (v["lemma"] not in best
                            or v["cpu"] < best[v["lemma"]]["cpu"]):
            best[v["lemma"]] = v
    for n, _, _ in LIBRARY:
        b = best.get(n)
        mark = f"PROVED {b['direction']:<18} {b['cpu']:>7.1f}s" if b \
            else "unproven in both directions"
        print(f"  {n:<16} {mark}", flush=True)
    verified = [(n, l, r) for n, l, r in LIBRARY if n in best]
    print(f"  -> {len(verified)}/{len(LIBRARY)} verified", flush=True)
    (OUT / "verify.json").write_text(json.dumps(
        {"results": vres, "verified": [n for n, _, _ in verified]}, indent=2))

    hints = []
    for _, l, r in verified:
        hints += [t for t in (l, r) if "(" in t and t not in hints]
    print(f"\nJOB 2: attempt {len(TARGETS)} problems with {len(hints)} hints, "
          f"both directions, 4000s", flush=True)
    jobs = [(p, d, tuple(hints), 4000) for p in TARGETS for d in DIRS]
    with ProcessPoolExecutor(max_workers=10) as pool:
        ares = list(pool.map(attempt_job, jobs))
    for a in sorted(ares, key=lambda x: (x["problem"], x["direction"])):
        print(f"  {a['problem']:<12} {a['direction']:<18} "
              f"{('PROVED' if a['proved'] else a['result']):<10} "
              f"{a['cpu']:>8.1f}s", flush=True)
    flips = sorted({a["problem"] for a in ares if a["proved"]})
    print(f"\n  FLIPS: {len(flips)}/{len(TARGETS)}  {flips}", flush=True)
    (OUT / "attempt.json").write_text(json.dumps(
        {"results": ares, "flips": flips, "n_hints": len(hints)}, indent=2))
    print(f"\ntotal {time.time() - t0:.0f}s wall", flush=True)


if __name__ == "__main__":
    main()
