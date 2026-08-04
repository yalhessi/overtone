#!/usr/bin/env python3
"""RNG033-8: a Stevens challenge problem TPTP records as Status: Unknown.

    (xy, z, w) + (x, y, [z,w])  =  x(y,z,w) + (x,z,w)y

No proof and no countermodel on record, rated 1.00. Selected over the other
seven open RNG problems on three measured grounds:

  * its axioms contain RNG029-5's, so the 29-node alternative-ring library is a
    set of theorems here rather than assumptions (`problems.contains_axioms`);
  * 47% of the rules a 180s probe derived touch the goal's own constants, where
    RNG010-5/6/7 manage 0% -- that family is not reaching its goal at all, which
    is a different and worse problem than needing a better decomposition;
  * it supplies the right Moufang identity as a *hypothesis*, so the one node
    that costs 192.9s to derive is free here.

**No donor.** The best-scoring sibling is RNG027-5 at 0.982 axiom similarity, and
its proof is exactly what this library was distilled from: 234 lemmas of which
four did the work. Re-importing it would undo the distillation, and 234 lemmas in
the hint channel flipped nothing.

So: the library, plus a drafted bridge from Teichmuller to the goal.

PREDICTIONS, recorded before running. The point of writing them down is that the
ones I get wrong are the informative ones -- three of four hand-drafted edges
were wrong earlier in this project, and each error was only visible against a
stated expectation.

  library tiers 1-5      <= 2s each      unchanged from RNG029-5
  (right_moufang is a hypothesis here, so it would be free -- but the sketch is
   pruned to the goal's ancestors below and the Moufang tier is not among them,
   so there is no prediction to score.)
  teichmuller            ~3s             3.3s on RNG029-5, same axioms
  comm_def_add           <1s             the commutator definition rearranged
                                         additively. Exactly the shape of
                                         assoc_def_add, which was worth 18x and
                                         which no draft had thought to name.
  assoc_comm_3           <10s            trilinearity in argument 3 applied
                                         through the commutator. Needs
                                         assoc_add_3 and comm_def_add; without
                                         comm_def_add I expect it to fail.
ITERATION 2 predictions (after the goal failed at 600s with parents and
standalone). The refinement is driven by mining 6,777 universal rules out of the
eight failed runs, not by guessing:

  teich_isolated         <5s      Teichmuller solved for the multiplied term.
                                  Follows from teichmuller by rearrangement, so
                                  it should be near-free; if it is slow, my
                                  rearrangement is wrong.
  assoc_comm_1           <10s     mirror of assoc_comm_3, which took 0.0s.
  assoc_prod_comm_a/b    <30s     mined verbatim from the failed runs, so twee
                                  has already derived them -- they are theorems
                                  and must verify. If either FAILS, the mining is
                                  producing rules that do not hold standalone,
                                  which would invalidate the whole approach and
                                  is the most valuable thing this run could tell
                                  me.
  rng033_goal            unknown  I will not put a number on it. The evidence
                                  says the search never builds the goal's RHS
                                  shape; these four nodes are an attempt to make
                                  it available. Whether that is sufficient is
                                  exactly what is unknown.

ITERATION 1 predictions and outcomes -- 4 of 5 correct, and the miss was the one
flagged as least confident:

  library tiers 1-5      <=2s     ACTUAL 0.0-1.8s      correct
  teichmuller            ~3s      ACTUAL 3.6s          correct
  comm_def_add           <1s      ACTUAL 0.0s          correct
  assoc_comm_3           <10s     ACTUAL 0.0s          correct
  rng033_goal            30-300s  ACTUAL unproven      WRONG

  rng033_goal            30-300s         LEAST CONFIDENT. This is the real test.
                                         My hand derivation of the step from
                                         Teichmuller to the goal did not close --
                                         it left a factor of 2 I do not believe --
                                         so either a bridge node is missing or my
                                         arithmetic is wrong. The prover
                                         adjudicates; I have been wrong three
                                         times this session doing this by hand.

If `rng033_goal` fails, the diagnosis follows the usual order: was the failure
with parents or standalone, what did its own run derive that the sketch does not
name, and does a same-shape sibling that proved have different parents.
"""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "_rng_dag", Path(__file__).resolve().parent / "rng_dag.py")
_rng = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_rng)

A, M, I, C, Z = ("associator", "multiply", "additive_inverse", "commutator",
                 "additive_identity")

# The whole alternative-ring library, unchanged. It is verified against this
# problem's own axioms by the pipeline, not assumed from the RNG029-5 run.
DAG = dict(_rng.DAG)

# -- the bridge --------------------------------------------------------------
# The commutator definition rearranged so no additive_inverse appears, which is
# what made assoc_def_add worth 18x: twee orients the definitional axiom one way
# and the sketch needs the other.
DAG["comm_def_add"] = (f"add({C}(X,Y),{M}(X,Y))", f"{M}(Y,X)", [])

# Trilinearity in argument 3, pushed through the commutator. The goal's only
# structural difference from Teichmuller is this term.
DAG["assoc_comm_3"] = (
    f"{A}(X,Y,{C}(Z,W))",
    f"add({A}(X,Y,{M}(W,Z)),{I}({A}(X,Y,{M}(Z,W))))",
    ["assoc_add_3", "comm_def_add", "neg_add", "neg_mult_r"])

# -- iteration 2: refinement driven by the failed search ---------------------
# 6,777 universal rules were mined from the 8 failed runs. Of them, 699 build the
# goal's LHS shape (associator of a product) and 629 the commutator term -- but
# only 86 contain an associator *multiplied* by anything, which is the goal's
# entire RHS, and on inspection those are sign shuffling and degenerate cases.
# The search never constructs the right-hand side.
#
# The mechanism: teichmuller is the only source of `x(y,z,w)` and `(x,y,z)w`, and
# it carries them on its heavier side, so twee orients it to eliminate exactly
# what the goal needs. That is the assoc_def_add fault -- an identity oriented
# against the direction the sketch requires -- which was worth 18x, and which
# assoc_def_246/247 fixed for Moufang.

# Teichmuller solved for the multiplied term, so the goal's RHS shape has a rule
# that yields it rather than only rules that consume it.
DAG["teich_isolated"] = (
    f"{M}({A}(X,Y,Z),W)",
    f"add(add({A}({M}(X,Y),Z,W),{A}(X,Y,{M}(Z,W))),"
    f"{I}(add({A}(X,{M}(Y,Z),W),{M}(X,{A}(Y,Z,W)))))",
    ["teichmuller", "neg_add", "neg_mult_r"])

# Trilinearity in argument 1 through the commutator -- the mirror of
# assoc_comm_3, which verified at 0.0s. The goal has a product in argument 1 and
# a commutator in argument 3, so both directions are plausibly needed.
DAG["assoc_comm_1"] = (
    f"add({A}({M}(X,Y),Z,W),{A}({C}(X,Y),Z,W))",
    f"{A}({M}(Y,X),Z,W)",
    ["assoc_add_1", "comm_def_add", "neg_add", "neg_mult_r"])

# Mined verbatim from the failed runs: twee derived these, so they are theorems
# and will verify by construction. They bridge the goal's two LHS terms, relating
# an associator of a product to an associator of a commutator.
DAG["assoc_prod_comm_a"] = (
    f"{A}({M}(X,Y),Z,{M}(Y,X))", f"{A}({C}(Y,X),Z,{M}(X,Y))",
    ["assoc_comm_1", "assoc_cyclic", "alt12_additive"])
DAG["assoc_prod_comm_b"] = (
    f"{A}({M}(X,Y),{M}(Y,X),Z)", f"{A}({C}(X,Y),Z,{M}(X,Y))",
    ["assoc_comm_1", "assoc_cyclic", "alt23_additive"])

# -- the target --------------------------------------------------------------
DAG["rng033_goal"] = (
    f"add({A}({M}(X,Y),Z,W),{A}(X,Y,{C}(Z,W)))",
    f"add({M}(X,{A}(Y,Z,W)),{M}({A}(X,Z,W),Y))",
    ["teichmuller", "teich_isolated", "assoc_comm_3", "assoc_comm_1",
     "assoc_prod_comm_a", "assoc_prod_comm_b", "assoc_cyclic",
     "alt12_additive", "alt23_additive", "flexible"])

# Budget is a diagnostic. right_moufang keeps a large budget only because the
# library declares one; here it should be free, and a large number would itself
# be the finding.
TIER_BUDGET = dict(_rng.TIER_BUDGET)
TIER_BUDGET.update({"rng033_goal": 900, "assoc_comm_3": 60,
                    "comm_def_add": 60, "teich_isolated": 120,
                    "assoc_comm_1": 120, "assoc_prod_comm_a": 120,
                    "assoc_prod_comm_b": 120})

TARGETS = ["RNG033-8"]

from overtone.agent.dag import Sketch          # noqa: E402

# Prune to what the goal actually needs. The library's Moufang tier is not on
# this goal's derivation, and Pipeline A charges every node to the problem --
# verifying five irrelevant nodes (one of them a 400s budget) would be waste
# reported as cost, not honesty. `scope(..., "closure")` is the ancestor set the
# sketch already knows how to compute.
_full = Sketch(DAG)
_keep = set(_full.scope("rng033_goal", "closure")) | {"rng033_goal"}
DAG = {n: v for n, v in DAG.items() if n in _keep}
TIER_BUDGET = {n: b for n, b in TIER_BUDGET.items() if n in _keep}

SKETCH = Sketch(DAG)

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="Sketch definition for RNG033-8. Run it through "
                    "./scripts/prove.py --sketch scripts/rng033_dag.py; "
                    "executing this file only prints the topology.")
    ap.add_argument("--json", action="store_true", help="emit the sketch as JSON")
    a = ap.parse_args()
    if a.json:
        import json as _json
        print(_json.dumps(SKETCH.to_json(), indent=1))
    else:
        print(f"{len(DAG)} nodes, {len(SKETCH.layers())} layers")
        for i, layer in enumerate(SKETCH.layers(), 1):
            print(f"  {i}: {layer}")
