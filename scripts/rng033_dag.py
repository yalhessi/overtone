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

# -- the target --------------------------------------------------------------
DAG["rng033_goal"] = (
    f"add({A}({M}(X,Y),Z,W),{A}(X,Y,{C}(Z,W)))",
    f"add({M}(X,{A}(Y,Z,W)),{M}({A}(X,Z,W),Y))",
    ["teichmuller", "assoc_comm_3", "assoc_cyclic", "alt12_additive",
     "alt23_additive", "flexible"])

# Budget is a diagnostic. right_moufang keeps a large budget only because the
# library declares one; here it should be free, and a large number would itself
# be the finding.
TIER_BUDGET = dict(_rng.TIER_BUDGET)
TIER_BUDGET.update({"rng033_goal": 300, "assoc_comm_3": 60, "comm_def_add": 60})

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
    print(f"{len(DAG)} nodes, {len(SKETCH.layers())} layers")
    for i, layer in enumerate(SKETCH.layers(), 1):
        print(f"  {i}: {layer}")
