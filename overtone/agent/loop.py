"""The draft -> verify -> diagnose -> revise loop, automated.

A human ran this loop by hand and it was regular enough to be worth writing
down. Every mechanical piece already existed -- `verify` proves nodes, `attempt`
runs the target, `sibling_diff` and the mined candidates explain failures. What
was missing is the part that reads a failure and edits the sketch.

**Scripted agent first, model later.** `Agent` is a protocol and `ScriptedAgent`
replays a fixed list of edits, so the harness can be exercised end to end with no
model and no API key. When a model is attached, a failure is then unambiguously
the model's or the harness's, never both.

**The action set is closed and the edits are pure.** `apply` returns a new
`Sketch` or raises; nothing mutates in place, so a trajectory can be replayed and
a bad action cannot corrupt the run.

**`restate` is guarded, structurally.** A node annotated with a TPTP problem
cannot be given a hand-written statement -- it must be copied from that problem
file. Our `left_moufang` node states `((xy)x)z = x(y(xz))` where RNG028-7 states
`(x(yx))z = x(y(xz))`; they differ by the flexible law and are not the same
problem. Under this rule that drift is unrepresentable rather than merely
detectable, which is the difference between a guard and a hope.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from overtone import batch, problems
from overtone.agent import blueprint
from overtone.agent.dag import (DIRECTIONS, Sketch, attempt, cost, diff,
                                mined_parents, sibling_diff, verify)
from overtone.agent.pipeline import Budget

ACTIONS = ("add_node", "remove_node", "set_parents", "subdivide", "restate",
           "attempt")


# ----------------------------------------------------------------- state

@dataclass(frozen=True)
class NodeState:
    name: str
    lhs: str
    rhs: str
    parents: tuple
    status: str          # proved | proved_scoped | slow | failed_* | blocked | pending
    cpu: float | None
    direction: str | None


@dataclass(frozen=True)
class State:
    """What the agent sees. Derived from the sketch and the run directory.

    Never free text: an agent that has to parse prose is an agent whose failures
    are unattributable.
    """
    problem: str
    iteration: int
    cpu_spent: float
    nodes: tuple = ()
    candidates: dict = field(default_factory=dict)
    diffs: dict = field(default_factory=dict)
    sources: tuple = ()          # retrieved references, for offline replay

    def failing(self):
        return [n for n in self.nodes if n.status.startswith("failed")]

    def slow(self):
        return [n for n in self.nodes if n.status == "slow"]


def state_of(problem, sketch: Sketch, results, outdir: Path, *, iteration=0,
             slow=30, sources=()):
    """Classify every node, and explain the ones that need explaining.

    Builds on `blueprint.statuses`, which already computes
    proved/proved_scoped/failed/blocked/pending and is exercised by the renderer.
    The refinement is the part a reviser needs: *slow* (proved but above the
    diagnostic threshold, so a node is probably missing beneath it) and whether a
    failure survived a standalone retry, which separates a wrong edge from a hard
    lemma.
    """
    outdir = Path(outdir)
    st = blueprint.statuses(sketch, results)
    nodes, candidates, diffs = [], {}, {}
    for name, (lhs, rhs, parents) in sketch.nodes.items():
        s = st[name]
        status = s["status"]
        if status.startswith("proved") and s["cpu"] and s["cpu"] >= slow:
            status = "slow"
        elif status == "failed":
            retried = any(r.get("scope_retry") for r in results
                          if r["node"] == name)
            status = "failed_standalone" if retried else "failed_with_parents"
        nodes.append(NodeState(name, lhs, rhs, tuple(parents), status,
                               s["cpu"], s["direction"]))
        if status == "slow" or status.startswith("failed"):
            candidates[name] = _candidates(name, sketch, outdir, proved=status == "slow")
            d = sibling_diff(sketch, results, name)
            if d:
                diffs[name] = d
    spent = cost(results)["cpu"]
    return State(problem=problem, iteration=iteration, cpu_spent=spent,
                 nodes=tuple(nodes), candidates=candidates, diffs=diffs,
                 sources=tuple(sources))


def _candidates(name, sketch, outdir: Path, *, proved, limit=12):
    """Equations this node's own run derived that the sketch does not name.

    For a slow success the proof's unnamed lemmas; for a failure the derived
    rules, since a timed-out run emits no `Lemma` lines at all. `assoc_def_add`
    -- worth 18x on `assoc_add_1` -- was read off exactly this listing by hand.
    """
    from overtone import proofs
    out = []
    for path in sorted(outdir.glob(f"{name}.*")):
        if path.suffix not in (".out",) and not path.name.endswith(".fail.out"):
            continue
        text = path.read_text(errors="replace")
        if proved:
            _, unmatched = mined_parents(sketch, name, text)
            out += [f"{l} = {r}" for _, l, r in unmatched]
        else:
            rules = proofs.derived_rules(text)
            out += [r["body"] for r in sorted(rules.values(),
                                              key=lambda r: r["score"])[:limit]]
        if out:
            break
    return out[:limit]


# ----------------------------------------------------------------- actions

def apply(sketch: Sketch, action: dict, *, annot=None) -> Sketch:
    """Apply one edit, returning a new Sketch. Pure; raises on anything invalid."""
    op = action.get("op")
    if op not in ACTIONS:
        raise ValueError(f"unknown op {op!r}; expected one of {ACTIONS}")
    nodes = dict(sketch.nodes)
    annot = annot or {}

    if op == "add_node":
        name = action["name"]
        if name in nodes:
            raise ValueError(f"{name} already exists; use restate or set_parents")
        nodes[name] = (action["lhs"], action["rhs"],
                       list(action.get("parents", [])))
    elif op == "remove_node":
        name = action["name"]
        nodes.pop(name, None)
        nodes = {n: (l, r, [p for p in ps if p != name])
                 for n, (l, r, ps) in nodes.items()}
    elif op == "set_parents":
        name = action["name"]
        l, r, _ = nodes[name]
        nodes[name] = (l, r, list(action["parents"]))
    elif op == "subdivide":
        # Insert intermediates beneath a node and rewire it onto them. The whole
        # point of the loop: a node that will not go quickly wants smaller steps,
        # not a larger budget.
        name = action["name"]
        l, r, ps = nodes[name]
        added = []
        for inter in action["intermediates"]:
            nodes[inter["name"]] = (inter["lhs"], inter["rhs"],
                                    list(inter.get("parents", ps)))
            added.append(inter["name"])
        nodes[name] = (l, r, list(action.get("parents", ps)) + added)
    elif op == "restate":
        name = action["name"]
        _, _, ps = nodes[name]
        tptp = (annot.get(name) or {}).get("tptp") or []
        src = action.get("from_problem")
        if tptp and not src:
            raise ValueError(
                f"{name} is annotated with {tptp}; restate it with "
                f"from_problem=<name> so the statement is copied from the "
                f"problem file rather than authored")
        if src:
            c = problems.conjecture(problems.problem_path(src))
            if c is None:
                raise ValueError(f"{src} has no negated conjecture to copy")
            nodes[name] = (c[0], c[1], ps)
        else:
            nodes[name] = (action["lhs"], action["rhs"], ps)
    elif op == "attempt":
        return sketch                     # handled by the loop, not an edit
    return Sketch(nodes)


# ----------------------------------------------------------------- agents

class Agent(Protocol):
    def act(self, state: State) -> list: ...


class ScriptedAgent:
    """Replays a fixed list of action-lists, one per iteration.

    This session's edits are the harness's regression test, and they run with no
    model and -- against a fake runner -- no prover.
    """

    def __init__(self, script):
        self.script = list(script)

    def act(self, state: State):
        i = state.iteration
        return list(self.script[i]) if i < len(self.script) else []


# ----------------------------------------------------------------- the loop

def run_loop(problem, sketch: Sketch, agent: Agent, *, outdir: Path,
             budget=Budget(), budgets=None, binary=None, max_iterations=6,
             total_cpu=None, directions=DIRECTIONS, annot=None):
    """verify -> attempt -> diagnose -> act -> repeat.

    Stops on: the target proved, `max_iterations`, `total_cpu`, or an empty
    action list. The trajectory is written either way -- a failed run with its
    diagnoses is the training data the loop exists to produce, and is the only
    record of *why* an edit was made.
    """
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    traj = open(outdir / "trajectory.jsonl", "a", buffering=1)
    spent, proved, history = 0.0, False, []

    try:
        for i in range(max_iterations):
            v = verify(problem, sketch, outdir=outdir / f"iter{i:02d}",
                       budget=budget.node, budgets=budgets, workers=budget.workers,
                       binary=binary, directions=directions)
            ok = [n for n in sketch.nodes if n in v["proved"]]
            a = attempt(problem, sketch.equations(ok),
                        outdir=outdir / f"iter{i:02d}", budget=budget.final,
                        binary=binary, directions=directions)
            spent += cost(v["results"], a)["cpu"]
            proved = any(r["proved"] for r in a)

            state = state_of(problem, sketch, v["results"],
                             outdir / f"iter{i:02d}", iteration=i, slow=budget.slow)
            (outdir / f"sketch.{i:02d}.json").write_text(
                json.dumps(sketch.to_json(), indent=2) + "\n")

            actions = [] if proved else list(agent.act(state))
            rec = {"iter": i, "proved": proved, "cpu_spent": round(spent, 1),
                   "n_proved": v["n_proved"], "n_nodes": v["n_nodes"],
                   "missing": v["missing"],
                   "slow": [n.name for n in state.slow()],
                   "failing": [n.name for n in state.failing()],
                   "diffs": state.diffs, "actions": actions,
                   "sources": list(state.sources)}
            batch.append_record(traj, rec)
            history.append(rec)
            print(f"iter {i}: {v['n_proved']}/{v['n_nodes']} nodes, "
                  f"{'PROVED' if proved else 'not proved'}, "
                  f"{spent:.1f}s CPU, {len(actions)} action(s)", flush=True)

            if proved or not actions:
                break
            if total_cpu and spent >= total_cpu:
                print(f"  stopping: {spent:.1f}s >= total_cpu {total_cpu}", flush=True)
                break
            before = sketch
            for act in actions:
                sketch = apply(sketch, act, annot=annot)
            d = diff(before, sketch)
            print(f"  applied {d['n_edits']} edit(s): +{len(d['added'])} "
                  f"-{len(d['removed'])} ~{len(d['restated'])} "
                  f"parents:{len(d['reparented'])}", flush=True)
    finally:
        traj.close()

    out = {"problem": problem, "proved": proved, "cpu_total": round(spent, 1),
           "iterations": len(history), "history": history,
           "final_sketch": sketch.to_json()}
    (outdir / "loop.json").write_text(json.dumps(out, indent=2) + "\n")
    return out
