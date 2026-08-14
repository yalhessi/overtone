#!/usr/bin/env python3
"""The alternative-ring sketch as a dependency DAG, verified in parent scope.

Supersedes the flat 19-lemma list in `overnight_rng.py` (removed at 8712094).
Two changes, both forced by measurement:

**Nodes carry their parents.** R1 (`logs/r1_scope/`): `alt12_additive` timed out
at 300s verified standalone and proves in 0.2s given its five direct parents as
axioms -- ~3000x. Supplying all thirteen verified lemmas instead of the five is
no better (0.1s), so scope follows the *direct parents*, not the ancestor
closure. A flat list cannot express that; this is the smallest structure that
can.

**Parents go in as axioms, not hints.** Also R1: `alt12_additive` never proved
from any hint configuration, and parents-as-hints (>600.7s) was worse than
supplying nothing (592.5s). That inverts MVA005-1, where 20 lemmas as axioms
timed out and the same set as hints proved in 173.6s. The variable is size and
precision -- a handful of exact parents belongs in the rewrite system; a large
approximate set belongs in the hint channel, where it only reweights scoring.

**The gap this fills.** The overnight library drafted nothing between the
alternating laws and Moufang -- its top two rungs *were* the target theorems, so
the hardest rung was the conjecture. Tiers 6-8 below are the missing bridge:
Teichmuller (which holds in any ring, and is TPTP RNG026 at rating 0.30-0.39),
the absorption lemmas twee derived unaided 2000s into the RNG025-5 proof, and
the associator forms of Moufang, which sit strictly below the product forms.

Verification is topological: a node is attempted only once its parents are
proved, and it receives exactly those parents. Both goal directions throughout --
three trilinearity lemmas prove under `--flatten-goal` and time out under the
other, and an earlier single-direction run wrongly concluded the subdivision was
mathematically wrong.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from overtone import config
from overtone.agent.dag import Sketch, verify

os.environ.setdefault("TWEE_STEPS_PER_SECOND", "10000")
OUT = config.LOGS / "rng_dag"
DIRS = ("--no-flatten-goal", "--flatten-goal")
HOST = "RNG029-5"

A = "associator"
M = "multiply"
I = "additive_inverse"
Z = "additive_identity"

# name -> (lhs, rhs, parents).  Tiers 1-5 are the overnight library minus the
# two badly-oriented negated forms (`(x,y,z) = -(y,x,z)`: applying it twice
# returns to the start, so it is a poor rewrite rule and its additive twin
# carries the same content).  Tiers 6-8 are new.
DAG = {
    # -- tier 1: sign and cancellation ------------------------------------
    "neg_mult_r":     (f"{M}(X,{I}(Y))", f"{I}({M}(X,Y))", []),
    "neg_mult_l":     (f"{M}({I}(X),Y)", f"{I}({M}(X,Y))", []),
    "neg_add":        (f"{I}(add(X,Y))", f"add({I}(X),{I}(Y))", []),
    "cancel_r":       (f"add(add(X,Y),{I}(Y))", "X", []),
    # -- tier 2: associator vanishes on repeats ---------------------------
    "assoc_xxy":      (f"{A}(X,X,Y)", Z, []),
    "assoc_xyy":      (f"{A}(X,Y,Y)", Z, []),
    "assoc_xyx":      (f"{A}(X,Y,X)", Z, ["assoc_xxy", "assoc_xyy"]),
    "flexible":       (f"{M}({M}(X,Y),X)", f"{M}(X,{M}(Y,X))", ["assoc_xyx"]),
    # -- tier 3: trilinearity ---------------------------------------------
    # `assoc_def_add` is the associator definition rearranged additively, with
    # no additive_inverse. It was not drafted: it was read off the unnamed steps
    # of the trilinearity proofs, which all had to derive it. It costs 0.0s and
    # takes assoc_add_1 from 37.9s to 2.1s -- the slow node was slow because the
    # sketch was missing a node, not because the lemma is hard.
    "assoc_def_add":  (f"add({A}(X,Y,Z),{M}(X,{M}(Y,Z)))", f"{M}({M}(X,Y),Z)", []),
    "assoc_add_1":    (f"{A}(add(X,Y),Z,W)", f"add({A}(X,Z,W),{A}(Y,Z,W))",
                       ["assoc_def_add"]),
    "assoc_add_2":    (f"{A}(X,add(Y,Z),W)", f"add({A}(X,Y,W),{A}(X,Z,W))",
                       ["assoc_def_add"]),
    "assoc_add_3":    (f"{A}(X,Y,add(Z,W))", f"add({A}(X,Y,Z),{A}(X,Y,W))",
                       ["assoc_def_add"]),
    # -- tier 4: linearised instances -------------------------------------
    "lin_left_inst":  (f"{A}(add(X,Y),add(X,Y),Z)", Z, ["assoc_xxy"]),
    "lin_right_inst": (f"{A}(X,add(Y,Z),add(Y,Z))", Z, ["assoc_xyy"]),
    # -- tier 5: alternating laws -----------------------------------------
    "alt12_additive": (f"add({A}(X,Y,Z),{A}(Y,X,Z))", Z,
                       ["lin_left_inst", "assoc_add_1", "assoc_add_2",
                        "assoc_xxy", "assoc_xyy"]),
    "alt23_additive": (f"add({A}(X,Y,Z),{A}(X,Z,Y))", Z,
                       ["lin_right_inst", "assoc_add_2", "assoc_add_3",
                        "assoc_xyy", "assoc_xxy"]),
    # -- tier 6: absorption (twee found these unaided, 2000s in) ----------
    "absorb_12a":     (f"{A}(X,add(X,Y),Z)", f"{A}(X,Y,Z)",
                       ["assoc_add_2", "assoc_xxy"]),
    "absorb_12b":     (f"{A}(add(X,Y),Y,Z)", f"{A}(X,Y,Z)",
                       ["assoc_add_1", "assoc_xxy"]),
    "absorb_23a":     (f"{A}(X,Y,add(Y,Z))", f"{A}(X,Y,Z)",
                       ["assoc_add_3", "assoc_xyy"]),
    "absorb_23b":     (f"{A}(X,Y,add(Z,Y))", f"{A}(X,Y,Z)",
                       ["assoc_add_3", "assoc_xyy"]),
    # -- tier 7: Teichmuller (holds in ANY ring; = TPTP RNG026) -----------
    # NO parents, and that is the whole point: it is pure expansion of the
    # associator definition, needing only distributivity and additive
    # associativity, both axioms. Drafted with five parents it timed out at
    # 900s; with the two sign lemmas, 358.6s; with none, 3.3s. The trilinearity
    # lemmas are adjacent in the theory and absent from the derivation, which is
    # exactly the mistake a drafter makes and a flat lemma list cannot record.
    "teichmuller":    (f"add({A}({M}(X,Y),Z,W),{A}(X,Y,{M}(Z,W)))",
                       f"add(add({A}(X,{M}(Y,Z),W),{M}(X,{A}(Y,Z,W))),"
                       f"{M}({A}(X,Y,Z),W))",
                       []),
    # -- tier 7b: the three lemmas the whole Moufang family actually needs --
    # Found by asking which of a donor proof's 234 lemmas its *goal* cited: four,
    # and the same four for all three targets. Three are cheap and reachable from
    # this sketch; the fourth is right_moufang itself. So the donor's 34-deep
    # chain was an artifact of starting from bare axioms, not the decomposition.
    "assoc_cyclic":   (f"{A}(X,Y,Z)", f"{A}(Y,Z,X)",
                       ["alt12_additive", "alt23_additive"]),
    "assoc_def_246":  (f"add({A}(X,Y,Z),{M}(Y,{M}(Z,X)))", f"{M}({M}(Y,Z),X)",
                       ["assoc_cyclic", "flexible", "assoc_xyx",
                        "alt12_additive", "alt23_additive"]),
    "assoc_def_247":  (f"add({A}(X,Y,Z),{M}({M}(Y,X),Z))", f"{M}(Y,{M}(X,Z))",
                       ["assoc_cyclic", "flexible", "assoc_xyx",
                        "alt12_additive", "alt23_additive"]),
    # -- tier 8: Moufang, associator form (= RNG027-8/9, RNG028-8/9) ------
    "right_moufang_a": (f"{A}(X,{M}(X,Y),Z)", f"{M}({A}(X,Y,Z),X)",
                        ["assoc_cyclic", "assoc_def_246", "assoc_def_247",
                         "right_moufang"]),
    # Mirror of right_moufang_a, so it takes left_moufang -- not right_moufang,
    # which is what it was first given by copying its sibling's parent list.
    # That single wrong parent cost a 300s timeout against 1.0s.
    "left_moufang_a":  (f"{A}(X,{M}(Y,X),Z)", f"{M}(X,{A}(X,Y,Z))",
                        ["assoc_cyclic", "assoc_def_246", "assoc_def_247",
                         "left_moufang"]),
    # -- tier 9: Moufang, product form -- these are the targets -----------
    # The one hard step: 192.4s from the three lemmas above, timeout without
    # them. Everything downstream is then under 90s.
    "right_moufang":  (f"{M}({M}({M}(X,Y),Z),Y)", f"{M}(X,{M}(Y,{M}(Z,Y)))",
                       ["assoc_cyclic", "assoc_def_246", "assoc_def_247"]),
    "left_moufang":   (f"{M}({M}({M}(X,Y),X),Z)", f"{M}(X,{M}(Y,{M}(X,Z)))",
                       ["assoc_cyclic", "assoc_def_246", "assoc_def_247",
                        "right_moufang"]),
    "middle_moufang": (f"{M}({M}(X,Y),{M}(Z,X))", f"{M}(X,{M}({M}(Y,Z),X))",
                       ["assoc_cyclic", "assoc_def_246", "assoc_def_247",
                        "right_moufang"]),
}

# Budget is a diagnostic, not a resource. A good decomposition verifies every
# node in seconds; a node that needs minutes is telling us the DAG is wrong
# there, and giving it 1800s buys a slow success that hides the fault. Measured
# support: every proved node in this sketch lands under 5s once its edges are
# right, and the one that did not (assoc_add_1 at 32.9s) was missing a node.
# So a timeout here means "revise the sketch", not "raise the budget".
DEFAULT_BUDGET = 60
TIER_BUDGET = {"right_moufang": 400, "left_moufang": 300,
               "middle_moufang": 300, "right_moufang_a": 300,
               "left_moufang_a": 300}
SLOW = 30          # over this, a node is suspect even when it proves





SKETCH = Sketch(DAG)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scope", choices=("none", "parents", "closure"),
                    default="parents")
    ap.add_argument("--channel", choices=("axioms", "hints"), default=None,
                    help="force a channel; default lets the DAG decide")
    ap.add_argument("--workers", type=int, default=20)
    ap.add_argument("--resume", action="store_true",
                    help="skip nodes an earlier run already proved")
    a = ap.parse_args()

    known, prior_results = (), ()
    prior = OUT / "dag.json"
    if a.resume and prior.exists():
        d = json.loads(prior.read_text())
        known = tuple(d.get("proved", {}))
        prior_results = tuple(d.get("results", ()))

    t0 = time.time()
    out = verify("RNG029-5", SKETCH, outdir=OUT, budget=DEFAULT_BUDGET,
                 budgets=TIER_BUDGET, scope=a.scope, channel=a.channel,
                 workers=a.workers, binary=config.twee_path(deterministic=True), known=known,
                 prior_results=prior_results)
    print(f"\n{out['n_proved']}/{out['n_nodes']} nodes proved")
    for n in out["missing"]:
        print(f"  MISSING:  {n}")
    slow = {n: c for n, c in out["proved"].items() if c and c >= SLOW}
    for n, c in sorted(slow.items(), key=lambda kv: -kv[1]):
        print(f"  SLOW:     {n} at {c:.1f}s -- mine its proof for a missing node")
    print(f"total {time.time() - t0:.0f}s wall")


if __name__ == "__main__":
    main()
