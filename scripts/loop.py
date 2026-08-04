#!/usr/bin/env python3
"""Run the draft -> verify -> diagnose -> revise loop.

    ./scripts/loop.py RNG029-5 --agent scripted --sketch scripts/rng_dag.py
    ./scripts/loop.py RNG029-5 --agent scripted --dry-run

The scripted agent replays the four edits this session actually made, starting
from the sketch as it stood *before* them. That is the harness's regression test:
if the loop cannot reproduce a trajectory a human already walked, it will not
find a new one. Each edit is a real measured decision, not an illustration --
the notes below cite what each was worth.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# also this directory: these CLIs import a sibling script, which only
# resolves implicitly when run directly, not when imported.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from overtone import config
from overtone.agent.dag import Sketch
from overtone.agent.loop import ScriptedAgent, apply, run_loop
from overtone.agent.pipeline import Budget
from prove import load_budgets, load_sketch

A, M, Z = "associator", "multiply", "additive_identity"

# This session's decisions, in order, each with what it was measured to be worth.
SESSION_EDITS = [
    # teichmuller was drafted with three trilinearity lemmas and the two sign
    # lemmas as parents. None is on its derivation -- it is pure expansion of the
    # associator definition. 3.3s with none, 358.6s with two, timeout at 900s
    # with five, and it gated six downstream nodes.
    [{"op": "set_parents", "name": "teichmuller", "parents": []}],

    # assoc_add_1 took 32.9s against 1.9s for its two siblings. Its proof had to
    # derive the associator definition rearranged additively, which the sketch
    # never named. Adding it: 37.9s -> 2.1s.
    [{"op": "subdivide", "name": "assoc_add_1", "parents": [],
      "intermediates": [{"name": "assoc_def_add",
                         "lhs": f"add({A}(X,Y,Z),{M}(X,{M}(Y,Z)))",
                         "rhs": f"{M}({M}(X,Y),Z)", "parents": []}]},
     {"op": "set_parents", "name": "assoc_add_2", "parents": ["assoc_def_add"]},
     {"op": "set_parents", "name": "assoc_add_3", "parents": ["assoc_def_add"]}],

    # The bridge to Moufang: cyclicity plus two rearrangements of the associator
    # definition. Found by asking which of a donor proof's 234 lemmas its goal
    # cited -- four, the same four for all three targets, three of them reachable
    # from this sketch in under a second.
    [{"op": "add_node", "name": "assoc_cyclic", "lhs": f"{A}(X,Y,Z)",
      "rhs": f"{A}(Y,Z,X)", "parents": ["alt12_additive", "alt23_additive"]},
     {"op": "add_node", "name": "assoc_def_246",
      "lhs": f"add({A}(X,Y,Z),{M}(Y,{M}(Z,X)))", "rhs": f"{M}({M}(Y,Z),X)",
      "parents": ["assoc_cyclic", "flexible", "assoc_xyx",
                  "alt12_additive", "alt23_additive"]},
     {"op": "add_node", "name": "assoc_def_247",
      "lhs": f"add({A}(X,Y,Z),{M}({M}(Y,X),Z))", "rhs": f"{M}(Y,{M}(X,Z))",
      "parents": ["assoc_cyclic", "flexible", "assoc_xyx",
                  "alt12_additive", "alt23_additive"]},
     # All five Moufang nodes were rewired in this step, not two. left_moufang_a
     # is given right_moufang here -- copied from its mirror sibling -- which is
     # the bug the next iteration corrects.
     {"op": "set_parents", "name": "right_moufang",
      "parents": ["assoc_cyclic", "assoc_def_246", "assoc_def_247"]},
     {"op": "set_parents", "name": "left_moufang",
      "parents": ["assoc_cyclic", "assoc_def_246", "assoc_def_247",
                  "right_moufang"]},
     {"op": "set_parents", "name": "middle_moufang",
      "parents": ["assoc_cyclic", "assoc_def_246", "assoc_def_247",
                  "right_moufang"]},
     {"op": "set_parents", "name": "right_moufang_a",
      "parents": ["assoc_cyclic", "assoc_def_246", "assoc_def_247",
                  "right_moufang"]},
     {"op": "set_parents", "name": "left_moufang_a",
      "parents": ["assoc_cyclic", "assoc_def_246", "assoc_def_247",
                  "right_moufang"]}],

    # left_moufang_a is the mirror of right_moufang_a and was handed its
    # sibling's parent list verbatim -- right_moufang where it needed
    # left_moufang. One wrong parent: 300s timeout against 1.0s.
    [{"op": "set_parents", "name": "left_moufang_a",
      "parents": ["assoc_cyclic", "assoc_def_246", "assoc_def_247",
                  "left_moufang"]}],
]


A33, M33, I33, C33 = ("associator", "multiply", "additive_inverse",
                      "commutator")

# RNG033-8, iteration 2: the four nodes added after mining 6,777 universal rules
# out of iteration 1's failed searches. The mining said the search builds the
# goal's left side prolifically (699 + 629 rules) and its right side almost never
# (86, all sign shuffling), so these aim at making that shape available.
RNG033_EDITS = [
    [{"op": "add_node", "name": "teich_isolated",
      "lhs": f"{M33}({A33}(X,Y,Z),W)",
      "rhs": f"add(add({A33}({M33}(X,Y),Z,W),{A33}(X,Y,{M33}(Z,W))),"
             f"{I33}(add({A33}(X,{M33}(Y,Z),W),{M33}(X,{A33}(Y,Z,W)))))",
      "parents": ["teichmuller", "neg_add", "neg_mult_r"]},
     {"op": "add_node", "name": "assoc_comm_1",
      "lhs": f"add({A33}({M33}(X,Y),Z,W),{A33}({C33}(X,Y),Z,W))",
      "rhs": f"{A33}({M33}(Y,X),Z,W)",
      "parents": ["assoc_add_1", "comm_def_add", "neg_add", "neg_mult_r"]},
     {"op": "add_node", "name": "assoc_prod_comm_a",
      "lhs": f"{A33}({M33}(X,Y),Z,{M33}(Y,X))",
      "rhs": f"{A33}({C33}(Y,X),Z,{M33}(X,Y))",
      "parents": ["assoc_comm_1", "assoc_cyclic", "alt12_additive"]},
     {"op": "add_node", "name": "assoc_prod_comm_b",
      "lhs": f"{A33}({M33}(X,Y),{M33}(Y,X),Z)",
      "rhs": f"{A33}({C33}(X,Y),Z,{M33}(X,Y))",
      "parents": ["assoc_comm_1", "assoc_cyclic", "alt23_additive"]},
     {"op": "set_parents", "name": "rng033_goal",
      "parents": ["teichmuller", "teich_isolated", "assoc_comm_3",
                  "assoc_comm_1", "assoc_prod_comm_a", "assoc_prod_comm_b",
                  "assoc_cyclic", "alt12_additive", "alt23_additive",
                  "flexible"]}],
]


def rewind_rng033(sketch: Sketch) -> Sketch:
    """The RNG033-8 sketch as iteration 1 had it, before the mined refinement."""
    nodes = {n: v for n, v in sketch.nodes.items()
             if n not in ("teich_isolated", "assoc_comm_1",
                          "assoc_prod_comm_a", "assoc_prod_comm_b")}
    nodes["rng033_goal"] = (*nodes["rng033_goal"][:2],
                            ["teichmuller", "assoc_comm_3", "assoc_cyclic",
                             "alt12_additive", "alt23_additive", "flexible"])
    return Sketch(nodes)


def rewind(sketch: Sketch) -> Sketch:
    """The sketch as it stood before the scripted edits, so replaying them means
    something. Reversing each edit is more honest than shipping a second copy of
    the sketch that could drift from the real one."""
    nodes = dict(sketch.nodes)
    nodes["teichmuller"] = (*nodes["teichmuller"][:2],
                            ["assoc_add_1", "assoc_add_2", "assoc_add_3",
                             "neg_mult_l", "neg_mult_r"])
    for n in ("assoc_add_1", "assoc_add_2", "assoc_add_3"):
        nodes[n] = (*nodes[n][:2], [])
    for n in ("assoc_cyclic", "assoc_def_246", "assoc_def_247", "assoc_def_add"):
        nodes.pop(n, None)
    nodes["right_moufang"] = (*nodes["right_moufang"][:2],
                              ["right_moufang_a", "flexible", "assoc_xyx"])
    nodes["middle_moufang"] = (*nodes["middle_moufang"][:2],
                               ["left_moufang", "right_moufang", "flexible"])
    nodes["right_moufang_a"] = (*nodes["right_moufang_a"][:2],
                                ["teichmuller", "alt12_additive", "alt23_additive",
                                 "assoc_xxy", "assoc_xyy", "flexible"])
    nodes["left_moufang_a"] = (*nodes["left_moufang_a"][:2],
                               ["teichmuller", "alt12_additive", "alt23_additive",
                                "assoc_xxy", "assoc_xyy", "flexible"])
    nodes["left_moufang"] = (*nodes["left_moufang"][:2],
                             ["left_moufang_a", "flexible", "assoc_xyx"])
    return Sketch(nodes)


SCRIPTS = {"rng029": SESSION_EDITS, "rng033": RNG033_EDITS}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("problem")
    ap.add_argument("--sketch", type=Path,
                    default=config.ROOT / "scripts" / "rng_dag.py")
    ap.add_argument("--script", choices=("rng029", "rng033"), default="rng029",
                    help="which recorded edit sequence the scripted agent replays")
    ap.add_argument("--agent", choices=("scripted", "anthropic", "openai"),
                    default="scripted")
    ap.add_argument("--model", help="default: claude-opus-5 for anthropic; "
                                    "required (or $OPENAI_MODEL) for openai")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--no-rewind", action="store_true",
                    help="start from the sketch as it is, not as it was")
    ap.add_argument("--node-budget", type=int, default=60)
    ap.add_argument("--final-budget", type=int, default=300)
    ap.add_argument("--slow", type=int, default=30)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--max-iterations", type=int, default=6)
    ap.add_argument("--total-cpu", type=float)
    ap.add_argument("--outdir", type=Path)
    ap.add_argument("--rerun", action="store_true",
                    help="ignore the ledger and re-run every "
                         "invocation, even ones already recorded")
    ap.add_argument("--binary")
    ap.add_argument("--dry-run", action="store_true",
                    help="apply the edits without running twee, and report the "
                         "sketch they produce")
    a = ap.parse_args()

    sketch = load_sketch(a.sketch)
    target = sketch
    edits = SCRIPTS[a.script]
    if a.script == "rng029" and not a.no_rewind:
        sketch = rewind(sketch)
    elif a.script == "rng033":
        # RNG033-8's iteration 1 sketch is the committed one minus the four
        # nodes iteration 2 added; the edits below re-add them.
        sketch = rewind_rng033(sketch)

    if a.dry_run:
        print(f"start: {len(sketch.nodes)} nodes")
        s = sketch
        for i, batch_ in enumerate(edits):
            for act in batch_:
                s = apply(s, act)
            print(f"  iter {i}: {len(batch_)} action(s) -> {len(s.nodes)} nodes")
        same = s.nodes == target.nodes
        print(f"\nreplay reaches the committed sketch: {same}")
        if not same:
            only_s = sorted(set(s.nodes) - set(target.nodes))
            only_t = sorted(set(target.nodes) - set(s.nodes))
            if only_s or only_t:
                print(f"  node mismatch: extra={only_s} missing={only_t}")
            for n in sorted(set(s.nodes) & set(target.nodes)):
                if s.nodes[n] != target.nodes[n]:
                    print(f"  {n}:\n    replay={s.nodes[n][2]}\n    target={target.nodes[n][2]}")
        return 0 if same else 1

    outdir = a.outdir or (config.LOGS / "loop" / a.problem)
    outdir.mkdir(parents=True, exist_ok=True)
    budget = Budget(node=a.node_budget, slow=a.slow, final=a.final_budget,
                    workers=a.workers)
    if a.agent == "scripted":
        agent = ScriptedAgent(edits)
    else:
        from overtone.agent.llm import LLMAgent
        agent = LLMAgent(a.agent, a.model, temperature=a.temperature,
                         transcript_dir=outdir)
        print(f"agent: {a.agent} {agent.model}", flush=True)

    out = run_loop(a.problem, sketch, agent,
                   outdir=outdir, budget=budget,
                   budgets=load_budgets(a.sketch),
                   binary=a.binary or config.twee_path(deterministic=True),
                   max_iterations=a.max_iterations, total_cpu=a.total_cpu)
    print(f"\n  {'PROVED' if out['proved'] else 'NOT PROVED'} after "
          f"{out['iterations']} iteration(s), {out['cpu_total']:.1f}s CPU")
    print(f"  -> {outdir}/loop.json, trajectory.jsonl")


if __name__ == "__main__":
    sys.exit(main() or 0)
