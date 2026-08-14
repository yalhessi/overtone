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
ITERATION 3 predictions. Iteration 2 was drafted on a measurement that does not
work: it grepped the output for the goal's right-hand term shape and found ~10
matches in 24k rules, concluding the search never builds that side. But
`--flatten-goal` introduces a constant for every goal subterm and rewrites
matching terms to it on sight, so the shape *cannot* appear literally -- the
count measured twee's naming convention. `proofs.goal_contact` resolves the names
first, and says the opposite:

  run                  rules    lhs     rhs    both
  iter00  6 parents    24107   3033   11565     162   0.67%
  iter01 10 parents    24727   2927   11596     102   0.41%
  iter01 +precedence   25894   3058   12270     103   0.40%

The right-hand side is the *dominant* side. What is scarce is rules touching
both sides, which are the only ones that can close the goal -- and iteration 2's
four nodes cut those by 37%. A --precedence experiment built on the same bad
count moved them by one.

So iteration 3 reverts those four nodes and cuts the goal to three parents:
teichmuller, assoc_comm_3, assoc_cyclic. The two data points say contact fell as
the parent set grew, which is the wrong-parents finding (an axiom forms critical
pairs with every rule) appearing in the goal rather than in a lemma.

  both > 162   dilution confirmed; six parents was never the floor
  both ~ 162   parent count is not the lever -- it is which parents, and the
               next move varies membership at fixed size
  both < 162   one of the three dropped parents was load-bearing, and the diff
               says which

No prediction on proving the goal: three iterations have failed at it and a
number here would be invention. `both` is what is being measured.

ITERATION 3 OUTCOME: the middle branch, plus one result not predicted at all.

  parents   rules    lhs     rhs   both    both%
        0   19163   3297    9322    371    1.94%
        3   26358   2708   12839    171    0.65%
        6   24107   3033   11565    162    0.67%
       10   24727   2927   11596    102    0.41%

171 against 162 is flat, and lower by rate, so parent count is not the lever
between 3 and 6; ten is genuinely worse. The unpredicted row is the standalone
retry: **no parents scores the highest contact measured**, 371 at 1.94%, and
did not prove the goal at 300s. So `both` is a veto, not an objective -- a fall is
evidence an edit hurt, a rise is evidence of nothing, and maximising it would
drive the sketch to the configuration already known to fail. That correction is
now in `proofs.goal_contact`, `loop.State.contact`, and the agent's prompt.

The goal remains unproven at 300s under every parent set tried (0, 3, 6, 10) and
under a flipped term ordering.

ITERATION 2 predictions (after the goal failed at 600s with parents and
standalone). The refinement is driven by mining 6,777 universal rules out of the
eight failed runs, not by guessing. All four verified; the refinement was
nonetheless wrong, for the reason recorded above -- the nodes were sound and
aimed at a problem that did not exist:

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
import re
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

# -- iteration 2, reverted --------------------------------------------------
# Four nodes (teich_isolated, assoc_comm_1, assoc_prod_comm_a/b) were added here
# after mining the failed searches, on the reading that "the search never builds
# the goal's RHS shape". That reading came from grepping the output for the term
# shape, and --flatten-goal names every goal subterm and rewrites matching terms
# to the name, so the shape cannot appear literally. The count measured the
# naming convention. Measured properly (`proofs.goal_contact`), the RHS is the
# dominant side and the four nodes cut the rules touching *both* sides -- the
# only ones that can close the goal -- from 162 to 102. They are removed rather
# than kept: an axiom forms critical pairs with every rule, so a node that does
# not help is not free. Their statements survive in scripts/loop.py, which
# replays the iteration that added them.

# -- invented waypoints -------------------------------------------------------
# A first attempt identified two of the goal's four variables. Wrong altitude:
# an instance of an open conjecture is still open, and it sits right next to the
# conclusion, so it cannot decompose anything.
#
# A waypoint has to be far from BOTH ends -- real work from the axioms, real
# progress toward the goal. Teichmuller is the model, and note what it is: an
# identity true in EVERY ring (overtone/freering.py confirms it expands to zero)
# relating the associator to products. Sound by construction, and the single
# most useful node in this sketch.
#
# These were derived rather than guessed. `freering.express` solves for how far a
# familiar associative law is from holding, over a basis of associator terms,
# exactly and with no prover; each statement is then checked by expansion before
# it costs a run. They relate the commutator to the associator, which is what the
# goal mixes and what nothing else in the library addresses.
# Each waypoint gets the lemmas its own derivation uses, and nothing else.
#
# The first draft gave all four the same nine-lemma library tier. Both Leibniz
# identities then FAILED with those parents and proved in ~8.6s standalone --
# the wrong-parents finding, landing on this file's own draft. A generic tier is
# not a parent set.
_WP_PARENTS = []

# Leibniz rule for a commutator over a product, with its
# non-associative correction. Universal.
DAG["comm_prod_l"] = (
    "commutator(multiply(X,Y),Z)",
    "add(add(add(add(multiply(X,commutator(Y,Z)),multiply(commutator(X,Z),Y)),additive_inverse(associator(X,Y,Z))),associator(X,Z,Y)),additive_inverse(associator(Z,X,Y)))",
    list(_WP_PARENTS))

# The mirror: product in the second argument. Universal.
DAG["comm_prod_r"] = (
    "commutator(X,multiply(Y,Z))",
    "add(add(add(add(multiply(commutator(X,Y),Z),multiply(Y,commutator(X,Z))),associator(X,Y,Z)),additive_inverse(associator(Y,X,Z))),associator(Y,Z,X))",
    list(_WP_PARENTS))

# How far the commutator is from a Lie bracket -- the alternating sum of
# associators. Universal, and the expander is certain of it (zero monomials),
# yet twee did not prove it at 120s either standalone or with a library tier.
# Right altitude, wrong step size: it is a twelve-term additive identity, and
# budget-as-diagnostic says subdivide rather than wait. Jacobi is a sum of three
# commutator-of-commutator terms, and the Leibniz rules are precisely what
# expand those -- so they are its parents, now that both have proved.
DAG["jacobi_defect"] = (
    "add(add(commutator(commutator(X,Y),Z),commutator(commutator(Y,Z),X)),commutator(commutator(Z,X),Y))",
    "add(add(add(add(add(associator(X,Y,Z),additive_inverse(associator(X,Z,Y))),additive_inverse(associator(Y,X,Z))),associator(Y,Z,X)),associator(Z,X,Y)),additive_inverse(associator(Z,Y,X)))",
    ["comm_prod_l", "comm_prod_r"])

# The same defect in an ALTERNATIVE ring, where the alternating associator
# collapses those six terms to 6(x,y,z). Not universal -- it needs alternativity
# -- so it is a genuine conjecture, and the interesting waypoint of the four.
# Its parents are the universal form plus the three alternating facts that do
# the collapsing; nothing else is on its derivation.
DAG["jacobi_alternative"] = (
    "add(add(commutator(commutator(X,Y),Z),commutator(commutator(Y,Z),X)),commutator(commutator(Z,X),Y))",
    "add(add(add(add(add(associator(X,Y,Z),associator(X,Y,Z)),associator(X,Y,Z)),associator(X,Y,Z)),associator(X,Y,Z)),associator(X,Y,Z))",
    ["jacobi_defect", "alt12_additive", "alt23_additive",
     "assoc_cyclic"])

WAYPOINTS = ['comm_prod_l', 'comm_prod_r', 'jacobi_defect', 'jacobi_alternative']

# -- the target --------------------------------------------------------------
# Three parents, not ten and not six. Goal contact fell as the parent set grew
# (6 -> 162 rules touching both sides, 10 -> 102), which is the wrong-parents
# finding showing up in the goal rather than in a lemma. These three carry the
# goal's structure: teichmuller is the only lemma relating a multiplied
# associator to associators of products, assoc_comm_3 handles the commutator
# term, assoc_cyclic is the symmetry both rely on.
DAG["rng033_goal"] = (
    f"add({A}({M}(X,Y),Z,W),{A}(X,Y,{C}(Z,W)))",
    f"add({M}(X,{A}(Y,Z,W)),{M}({A}(X,Z,W),Y))",
    ["teichmuller", "assoc_comm_3", "assoc_cyclic"] + WAYPOINTS)

# Budget is a diagnostic. right_moufang keeps a large budget only because the
# library declares one; here it should be free, and a large number would itself
# be the finding.
TIER_BUDGET = dict(_rng.TIER_BUDGET)
# 300s, matching iteration 1, so the only variable between iterations is the
# four mined nodes. It was briefly 900s, which mixed two changes: a proof
# would not have separated the nodes from the extra 600 seconds. Reuse makes
# holding it at 300s free -- iteration 1's runs are already in the ledger.
# The goal gets 4000s; every other node keeps a diagnostic budget.
#
# Budget-as-diagnostic governs the *library*: a lemma that needs more than
# seconds means the sketch is wrong there, and all 18 of these prove in <=3.6s,
# which is what says the decomposition itself is sound. It is the wrong rule for
# the target. Reachability is the result being pursued here -- a problem out of
# reach at any budget coming into reach -- and per-problem cost may rise.
#
# The untried configuration, after three iterations of sketch surgery:
#
#   no parents,  4000s   Timeout (the plain baseline screen)
#   3 parents,    300s   Timeout
#   3 parents,   4000s   <- this
#
# Both levers have produced results separately: the strongest RNG result in this
# project is a plain 4000s screen (RNG027-10, 3271.1s, rating 1.00), and
# decomposition flipped ten targets. They have never been combined on this
# problem.
TIER_BUDGET.update({"rng033_goal": 600, "assoc_comm_3": 60,
                    "comm_def_add": 60})
# An instance is meant to be easier than the goal. If one needs more than this,
# it is not a waypoint and saying so early is the point of the budget.
TIER_BUDGET.update({n: 120 for n in WAYPOINTS})

TARGETS = ["RNG033-8"]

from overtone.agent.dag import Sketch          # noqa: E402

# Nodes the goal's parent set has named at any point, so every recorded
# iteration stays representable. Iteration 3 cut the goal to three parents, and
# pruning to *those* ancestors alone would drop `flexible` -- which iteration 0
# names -- leaving scripts/loop.py unable to replay its own history.
_HISTORICAL_PARENTS = ["alt12_additive", "alt23_additive", "flexible"]

# Prune to what the goal actually needs. The library's Moufang tier is not on
# this goal's derivation, and Pipeline A charges every node to the problem --
# verifying five irrelevant nodes (one of them a 400s budget) would be waste
# reported as cost, not honesty. `scope(..., "closure")` is the ancestor set the
# sketch already knows how to compute.
_full = Sketch(DAG)
_keep = set(_full.scope("rng033_goal", "closure")) | {"rng033_goal"}
for _p in _HISTORICAL_PARENTS:
    _keep |= set(_full.scope(_p, "closure")) | {_p}
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
