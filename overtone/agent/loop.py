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
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Protocol

from overtone import batch, problems
from overtone.agent import blueprint, pricing, review as reviewlib
from overtone.agent.dag import (DIRECTIONS, Sketch, attempt, channel_for, cost,
                                diff, mined_parents, sibling_diff, verify)
from overtone.agent.pipeline import Budget

ACTIONS = ("add_node", "remove_node", "set_parents", "subdivide", "restate",
           "attempt", "redraft")

# Iterations an approach gets before the loop says it has had its turn. Not a
# hard stop -- the agent still chooses -- but without it a run can spend every
# iteration on one route, which is what happened: ten iterations, 27 nodes
# proved, one approach, no proof.
APPROACH_BUDGET = 4


# ----------------------------------------------------------------- state

@dataclass(frozen=True)
class NodeState:
    name: str
    lhs: str
    rhs: str
    parents: tuple
    status: str          # proved | proved_scoped | slow | failed | blocked | pending
    cpu: float | None
    direction: str | None
    # Parents supplied to the winning run that its proof certificate never
    # cited. Candidates for a `set_parents` experiment, not proven dead weight:
    # see `dag._support_usage`. Empty when the node did not prove, when the
    # support went through the hint channel, or when the artifact is gone --
    # `failure` and `status` say which.
    unused_support: tuple = ()
    # Why a `failed` node failed, when the rows say: `timeout`, `saturated`
    # (the search closed and the statement does not follow from what was
    # supplied -- suspect the statement), or `error` (nothing was proved about
    # anything). This replaced `failed_standalone`/`failed_with_parents`, which
    # cost a whole extra prover run per failure to distinguish two cases and
    # conflated these three.
    failure: str | None = None


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
    # {node: {lhs, rhs, both, rules}} for each failing node -- how much of its
    # search touched each side of its own goal. `both` is a veto, not a score: it
    # fell 162 -> 102 across a refinement that made the problem harder while
    # every other count rose, but the highest value measured (371) belongs to
    # supplying no parents at all, which did not prove it at 300s. A fall condemns
    # an edit; a rise endorses nothing.
    contact: dict = field(default_factory=dict)
    # The target attempt itself: what was supplied, through which channel, what
    # came back, and its goal contact -- with the previous iteration's contact
    # beside it so the agent sees a DELTA rather than a level. This is the only
    # measurement taken against the real conjecture in the real problem file, it
    # is the most expensive run of every iteration, and until now it was recorded
    # nowhere and shown to nobody: two agent runs spent 58% and 83% of their
    # prover budget on a run whose result never reached the agent that caused it.
    target: dict = field(default_factory=dict)
    # The outcome of the PREVIOUS turn's edits, scored against the probe that
    # turn declared. See `score_outcome`.
    outcome: dict = field(default_factory=dict)
    # Findings from the review of the PREVIOUS turn's proposals. An edit that
    # was withheld, and why. Without this the agent cannot learn that a class of
    # proposal is bad -- one run repeated the same unsound edit three times.
    findings: tuple = ()
    # Consecutive iterations that proved nothing new. One run sat at 15 proved
    # nodes for four iterations while adding five more; nothing noticed, so it
    # kept making local edits. A stalled loop needs a different approach, not
    # another nudge.
    stalled: int = 0
    # Iterations spent on the current approach without closing the goal. The
    # stall counter alone is not enough: one run proved 27 nodes over ten
    # iterations, so it never stalled, and never changed approach either --
    # 11,647s of prover time on a single route that was not working. Proving
    # more nodes is not the objective; closing the goal is.
    iterations_on_approach: int = 0
    approach: str = ""
    approaches_tried: tuple = ()
    # Every sketch already tried, with what it achieved. Without this an agent
    # re-proposes an edit it made two iterations ago, the loop undoes it, and the
    # two states alternate forever -- each iteration "new" at the node level
    # because the node ledger only remembers invocations, not sketches.
    history: tuple = ()

    def failing(self):
        return [n for n in self.nodes if n.status.startswith("failed")]

    def slow(self):
        return [n for n in self.nodes if n.status == "slow"]


def failure_kind(rows):
    """Why a node's runs failed, from their result lines.

    The three cases point at different repairs, and the statuses this replaced
    (`failed_standalone` / `failed_with_parents`) conflated all three into
    whichever one an extra full-budget prover run happened to distinguish:

      * `saturated` -- twee closed the search and the statement does not follow
        from what was supplied. More time cannot help and neither can more
        parents in the loose sense; the statement is the suspect. Note the
        parents are proved or `given` lemmas and so already entailed by the
        axioms, which is why removing them cannot turn this verdict around --
        the standalone retry used to spend a full budget rediscovering that.
      * `timeout` -- the budget ran out with the question open. Either the step
        is too big (subdivide) or a parent is costing more than it pays.
      * `error` -- no verdict about anything. Infrastructure, not mathematics.

    `saturated` wins over `timeout` when directions disagree: one direction
    settling the question is a real answer, and the other merely ran out.
    """
    from overtone import proofs
    kinds = set()
    for r in rows:
        status = (r.get("result") or "").strip()
        if r.get("proved") or status in ("", "?", "Cancelled"):
            continue
        if status in proofs.SATURATED:
            kinds.add("saturated")
        elif status == "Timeout":
            kinds.add("timeout")
        else:
            kinds.add("error")            # NoResult, Error: ..., anything new
    for kind in ("saturated", "timeout", "error"):
        if kind in kinds:
            return kind
    return None


@dataclass(frozen=True)
class Probation:
    """One controller-authored parent drop, awaiting the run that judges it."""
    node: str
    dropped: tuple            # the parents removed, to restore verbatim
    parents: tuple            # the full parent list as it was before the drop
    cpu: float | None         # what the node cost WITH them
    iteration: int


def probation_drops(sketch, results, *, target=None, probe_node=None,
                    active=(), done=(), iteration=0):
    """Put each proved node's uncited parents on probation. -> (actions, probations)

    A proof certificate names the support it used, and across the 154 proved
    parented runs on record 164 of 307 supplied parents were never cited. An
    uncited parent is a good *candidate* for removal and nothing more: twee's
    search depends on which rules enter the system, so dropping one is a
    different search whose outcome is not predictable from the certificate --
    which is the argument `agent/ledger.py` is built on. So the drop is
    provisional. `probation_verdicts` reads the next run and restores anything
    that came back slower or stopped proving, at no prover cost, because that
    run was happening regardless.

    Four things are never touched:

      * the target node -- stripping it leaves nothing to supply the final
        attempt, which `run_loop` already rejects and `score_outcome` scores as
        a regression;
      * the node this turn's probe names -- the controller's edit and the
        agent's would land together and the scorer would credit the wrong one;
      * a node already on probation, which has not been judged yet;
      * a node whose probation was reverted, in `done` -- the measurement came
        back and said no.

    And an edge is left alone when removing it would leave its parent with no
    children at all. That orphan is a new sink, and `_target_node` falls back to
    the unique sink when a sketch's goal is not the problem's conjecture -- so a
    drop that orphans a lemma can cost the run its target, which is a far larger
    change than the one edge this is allowed to make. Removing the orphan too
    would be a structural edit the agent did not ask for; the agent can still
    drop it deliberately.
    """
    actions, out = [], []
    children = {n: 0 for n in sketch.nodes}
    for _, _, parents in sketch.nodes.values():
        for p in parents:
            if p in children:
                children[p] += 1
    for name, (_, _, parents) in sketch.nodes.items():
        if not parents or name == target or name == probe_node:
            continue
        if name in active or name in done or name in getattr(sketch, "given", ()):
            continue
        best = blueprint.best_row([r for r in results if r["node"] == name])
        unused = (best or {}).get("unused_support") or []
        # Only parents still declared: `unused_support` names what was supplied,
        # and an agent edit in the same turn may have moved on already.
        # `children` is decremented as drops accumulate, so two nodes dropping
        # the same parent in one turn cannot orphan it between them.
        drop = []
        for p in parents:
            if p in unused and children.get(p, 0) > 1:
                children[p] -= 1
                drop.append(p)
        if not drop:
            continue
        keep = [p for p in parents if p not in drop]
        actions.append({"op": "set_parents", "name": name, "parents": keep})
        out.append(Probation(name, tuple(drop), tuple(parents),
                             best.get("cpu"), iteration))
    return actions, out


def probation_verdicts(active, results):
    """Judge each pending drop against the run that followed it.

    -> (restore actions, kept, reverted). A node with no rows this iteration was
    not re-run -- blocked behind a failed parent, most often -- so it is left
    pending rather than judged on no evidence.

    The test is deliberately blunt: any loss reverts. Timings are reproducible
    enough to compare directly under the deterministic build, and the asymmetry
    is right -- the drop was a guess, and keeping a guess that cost time is
    worse than paying one iteration to undo it.
    """
    actions, kept, reverted = [], [], []
    for p in active:
        rows = [r for r in results if r["node"] == p.node]
        if not rows:
            continue                       # not re-run; still pending
        best = blueprint.best_row(rows)
        if best is None:
            reverted.append((p, f"{p.node} no longer proves without "
                                f"{list(p.dropped)}"))
        elif (p.cpu is not None and best.get("cpu") is not None
              and best["cpu"] > p.cpu):
            reverted.append((p, f"{p.node} rose from {p.cpu:.1f}s to "
                                f"{best['cpu']:.1f}s without {list(p.dropped)}"))
        else:
            kept.append((p, best))
    for p, _ in reverted:
        actions.append({"op": "set_parents", "name": p.node,
                        "parents": list(p.parents)})
    return actions, kept, reverted


def state_of(problem, sketch: Sketch, results, outdir: Path, *, iteration=0,
             slow=30, sources=(), history=(), findings=(), stalled=0,
             approach="", approaches_tried=(), iterations_on_approach=0,
             attempts=(), prev_target=None, outcome=None, spent=None):
    """Classify every node, and explain the ones that need explaining.

    Builds on `blueprint.statuses`, which already computes
    proved/proved_scoped/failed/blocked/pending and is exercised by the renderer.
    The refinement is the part a reviser needs: *slow* (proved but above the
    diagnostic threshold, so a node is probably missing beneath it), why a
    failure failed (`failure_kind`), and which supplied parents the proof
    certificate never cited.
    """
    outdir = Path(outdir)
    st = blueprint.statuses(sketch, results)
    nodes, candidates, diffs, contact = [], {}, {}, {}
    for name, (lhs, rhs, parents) in sketch.nodes.items():
        s = st[name]
        status = s["status"]
        rows = [r for r in results if r["node"] == name]
        failure = None
        if name in getattr(sketch, "given", ()):
            # An axiom is an assumption, not an open claim. Left as `pending` it
            # reads as work outstanding: one prompt showed the model 15 of the
            # problem's own axioms as `pending`, three quarters of the node list,
            # inviting it to go and prove things that are true by definition.
            status = "given"
        elif status.startswith("proved") and s["cpu"] and s["cpu"] >= slow:
            status = "slow"
        elif status == "failed":
            failure = failure_kind(rows)
        # Read from the SAME winning row `blueprint.statuses` timed, or evidence
        # and timing can describe two different searches -- the two directions
        # of one node routinely use different support.
        best = blueprint.best_row(rows)
        unused = (best or {}).get("unused_support") or ()
        nodes.append(NodeState(name, lhs, rhs, tuple(parents), status,
                               s["cpu"], s["direction"],
                               unused_support=tuple(unused), failure=failure))
        if status == "slow" or status.startswith("failed"):
            candidates[name] = _candidates(name, sketch, results,
                                           proved=status == "slow")
            d = sibling_diff(sketch, results, name)
            if d:
                diffs[name] = d
            c = _contact(name, results)
            if c:
                contact[name] = c
    # The target attempt is the longest search of the iteration -- 600s against
    # the real conjecture -- and its derived rules were read only for a contact
    # count. Everything it built was thrown away. These are the equations a run
    # aimed at the actual goal produced, which is the listing the single most
    # valuable node in this project was read off.
    from_target = _candidates("final", sketch, attempts, proved=False)
    if from_target:
        candidates["(the target attempt)"] = from_target
    # `spent` is the run's cumulative charged cost. Computed here it would be
    # this ITERATION's cost while `loop.json` and the printed line both report a
    # running total under the same name -- so the agent reasoning about budget
    # was reading a different quantity from the one the operator sees.
    c = cost(results, attempts)
    return State(problem=problem, iteration=iteration,
                 cpu_spent=c["cpu"] if spent is None else spent,
                 nodes=tuple(nodes), candidates=candidates, diffs=diffs,
                 contact=contact, target=target_of(attempts, prev_target),
                 outcome=dict(outcome or {}),
                 sources=tuple(sources), history=tuple(history),
                 findings=tuple(findings), stalled=stalled, approach=approach,
                 approaches_tried=tuple(approaches_tried),
                 iterations_on_approach=iterations_on_approach)


def target_of(attempts, prev=None):
    """What the target attempt was asked and what it answered.

    `both` is the veto quantity (FINDINGS: it fell 162 -> 102 across an edit
    that made the problem harder while every other count rose). The previous
    iteration's value travels with it so the agent reads a change rather than a
    level -- a level is the number it must never maximise, and a fall is the
    only reading that carries evidence.
    """
    attempts = list(attempts or ())
    if not attempts:
        return {}
    contact = _contact("final", attempts)
    best = next((r for r in attempts if r.get("proved")), attempts[0])
    out = {"proved": any(r.get("proved") for r in attempts),
           "result": best.get("result"),
           "channel": best.get("channel"),
           "support": list(best.get("support") or []),
           "n_support": best.get("n_support"),
           "cpu": round(sum(r.get("cpu") or 0.0 for r in attempts), 1),
           "reused": all(r.get("reused") for r in attempts),
           "skipped_unchanged": all(r.get("skipped_unchanged")
                                    for r in attempts)}
    if contact:
        out["contact"] = contact
        # A delta is only meaningful between comparable configurations, and the
        # empty-support run is the one configuration FINDINGS says is NOT
        # comparable: supplying nothing scores the highest contact ever measured
        # (371 against 171 for three parents and 162 for six) and proves
        # nothing. Using it as the reference would make the first edit that
        # supplies a real lemma look like a large regression -- and this loop
        # REVERTS regressions, so it would undo every genuine step and keep the
        # configuration already known to fail.
        if (prev and prev.get("contact") and prev.get("n_support")
                and out["n_support"]):
            out["contact_previous"] = prev["contact"]
            out["contact_delta_both"] = (contact["both"]
                                         - prev["contact"]["both"])
        elif prev and prev.get("contact"):
            out["contact_incomparable"] = (
                "no delta: one of the two runs supplied no lemmas, and contact "
                "is highest when nothing is supplied")
    return out


# What an iteration's edits turned out to be worth, judged against the probe
# the agent declared BEFORE the run. Only the first two count as progress.
OUTCOMES = ("solved", "productive", "regressed", "inconclusive", "invalid")


def score_outcome(probe, *, target, nodes, prev_nodes, slow=30,
                  applied=0, rejected=0, support_lost=False):
    """Classify the last turn's edits against the probe that turn declared.

    The loop had exactly one notion of progress -- a node newly proved -- and it
    is the wrong one. One run proved 27 nodes across ten iterations, never
    stalled, and never came closer to the goal; another grew 9 nodes to 24 and
    5 proved to 13 while its target contact went nowhere. Proving an isolated
    lemma is not evidence that the decomposition is aimed at the conjecture, so
    here it scores `inconclusive` and does not reset the stall counter.

    Order is deliberate. A proof of the target settles everything. A fall in
    goal contact outranks a proved node next, because that combination -- nodes
    proving while the only rules that can close the goal disappear -- is the
    exact shape of the refinement FINDINGS records as having made the problem
    harder. A rise in contact is never productive on its own: the highest value
    ever measured belongs to supplying no parents at all, which did not prove
    the goal.
    """
    def done(msg, name):
        return {"outcome": name, "why": msg, "probe": dict(probe or {})}

    if rejected and not applied:
        return done("every proposed edit was withheld or invalid, so the "
                    "sketch never changed", "invalid")
    if target.get("proved"):
        return done("the target attempt proved the conjecture", "solved")
    if support_lost:
        # Losing every proved lemma the goal rests on is a regression by
        # construction, and no measurement can show it: with nothing to supply
        # the attempt is the bare baseline, which is skipped, so there is no
        # contact number to fall. Without this an edit that strips the target
        # bare scores `inconclusive` and stands.
        return done("the target lost all of its proved support; there is now "
                    "nothing to supply it, which is the bare baseline",
                    "regressed")
    delta = target.get("contact_delta_both")
    if delta is not None and delta < 0:
        return done(f"goal contact fell by {-delta} rules touching both sides "
                    f"of the conjecture; the edits made the target harder to "
                    f"reach", "regressed")

    now = {n.name: n for n in nodes}
    was = {n.name: n for n in prev_nodes}
    node = (probe or {}).get("node")
    expect = (probe or {}).get("expect")
    n, before = now.get(node), was.get(node)
    if expect == "prove" and n is not None:
        if n.status.startswith("proved") and not (
                before is not None and before.status.startswith("proved")):
            return done(f"{node} proved, as the probe predicted", "productive")
        return done(f"{node} is {n.status}; the probe predicted it would prove",
                    "inconclusive")
    if expect == "speed_up" and n is not None:
        if n.cpu is not None and n.cpu < slow and (
                before is None or before.cpu is None or before.cpu >= slow):
            return done(f"{node} fell to {n.cpu:.1f}s, under the {slow}s "
                        f"diagnostic threshold", "productive")
        return done(f"{node} is at "
                    f"{'?' if n.cpu is None else format(n.cpu, '.1f')}s; the "
                    f"probe predicted it would drop below {slow}s",
                    "inconclusive")
    if expect == "target":
        return done("the target did not prove and its goal contact did not "
                    "fall; the probe resolved neither way", "inconclusive")

    gained = sum(1 for k, v in now.items()
                 if v.status.startswith("proved")
                 and not (k in was and was[k].status.startswith("proved")))
    if gained:
        return done(f"{gained} node(s) proved, but none was the probed one, so "
                    f"this is not evidence the decomposition is aimed at the "
                    f"conjecture", "inconclusive")
    return done("nothing moved", "inconclusive")


def _contact(name, rows):
    """Goal contact for a node's best failed run, or None.

    Reads the artifacts those runs recorded, addressed through `row["output"]`.
    It used to glob `{name}.flatten-goal.*.fail.out` in the iteration directory,
    which is wrong in both directions. Under-inclusive: an agent run reported
    `contact = None` at every iteration because the goal node was blocked and so
    never ran, while the target attempt it made in the same iteration left a
    2.2 MB failed search that scores `both = 22` -- the one signal this project
    trusts as a veto, on disk and read by nothing. Over-inclusive: repeated runs
    of a loop share an `iterNN` directory, and one such directory holds
    artifacts from five separate invocations, so the glob was reading other
    runs' output.

    Only `--flatten-goal` runs put the goal into the rewrite system, so a
    no-flatten run reports zeros that mean "not measurable here" rather than
    "not reaching the goal". Skip those instead of averaging the two modes into
    a number that means neither.
    """
    from overtone import proofs
    best = None
    for row in rows:
        if row.get("node") != name or row.get("proved"):
            continue
        if row.get("direction") != "--flatten-goal":
            continue
        path = row.get("output")
        if not path or not Path(path).exists():
            continue
        c = proofs.goal_contact(Path(path).read_text(errors="ignore"))
        if c.get("goal_directed") and (best is None or c["both"] > best["both"]):
            best = {k: c[k] for k in ("lhs", "rhs", "both", "rules")}
    return best


def _candidates(name, sketch, rows, *, proved, limit=12):
    """Equations this node's own run derived that the sketch does not name.

    For a slow success the proof's unnamed lemmas; for a failure the derived
    rules, since a timed-out run emits no `Lemma` lines at all. `assoc_def_add`
    -- worth 18x on `assoc_add_1` -- was read off exactly this listing by hand.

    Addressed through `row["output"]` for the same reason as `_contact`: a
    directory glob picks up other runs' artifacts when an `iterNN` directory is
    reused, and misses the ones a row points at elsewhere -- `_prior_artifact`
    hands on a ledger-recorded path from whichever run first produced it.
    """
    from overtone import proofs
    out = []
    for row in rows:
        if row.get("node") != name:
            continue
        path = row.get("output")
        if not path or not Path(path).exists():
            continue
        text = Path(path).read_text(errors="replace")
        if proved:
            _, unmatched = mined_parents(sketch, name, text)
            out += [f"{l} = {r}" for _, l, r in unmatched]
        else:
            rules = proofs.derived_rules(text)
            out += [r["body"] for r in sorted(rules.values(),
                                              key=lambda r: r["score"])]
        if out:
            break
    return _useful(out, sketch, limit)


# Run-local names twee mints for goal subterms and flattening constants. A rule
# mentioning one cannot become a reusable lemma: the name means nothing outside
# the run that created it.
_RUN_LOCAL = re.compile(r"\b(sk_dag_\d+|[a-z_]+\d+)\b")

# twee writes an oriented rule `l -> r` and a permutative one `l <-> r`. Both are
# equations and both are candidates; splitting on `->` alone lands INSIDE the
# second arrow, leaving a left side ending in `<` and handing the model the
# literal string `multiply(a,b) < = multiply(b,a)`. One artifact of a single
# iteration carried 17 such rules.
_ARROW = re.compile(r"\s*<?->\s*")


def _useful(bodies, sketch, limit):
    """Drop candidates that cannot become a node, keep the order otherwise.

    Ranking by raw twee score "surfaces plumbing the sketch already has"
    (PLAN.md). Three kinds of noise dominate the listing and none of them can
    ever be a lemma: rules naming run-local constants, rules the sketch already
    states, and rules that are one of the problem's own axioms. Filtering is
    cheap and honest -- it removes only what is unusable, and does not try to
    rank what remains, which nothing here has earned the right to do.
    """
    from overtone.terms import eq_key

    known = {eq_key(l, r) for l, r, _ in sketch.nodes.values()}
    out, seen = [], set()
    for body in bodies:
        parts = _ARROW.split(body, maxsplit=1)
        if len(parts) != 2:
            continue
        lhs, rhs = parts[0].strip(), parts[1].strip()
        if not lhs or not rhs:
            continue
        if _RUN_LOCAL.search(body):
            continue                      # a name that dies with the run
        k = eq_key(lhs, rhs)
        if k in known or k in seen:
            continue                      # already a node, or already listed
        seen.add(k)
        out.append(f"{lhs} = {rhs}")
        if len(out) >= limit:
            break
    return out


# ----------------------------------------------------------------- actions

def _goal_of(sketch: Sketch):
    """The goal node by naming convention. What `apply`'s redraft rewires.

    Deliberately NOT the broader search `_target_node` does. A redraft keeps
    this node and replaces its parents, so guessing wrong here would silently
    rewire a lemma into the goal's place; returning None just means the redraft
    does not rewire, which is safe. The broader search exists for the target
    attempt, where returning None is the unsafe answer.
    """
    return next((n for n in sketch.nodes if n.endswith("goal")), None)


def _target_node(sketch: Sketch, problem=None):
    """The node that is the conjecture, for choosing the target's support.

    By its statement first, by the `*goal` naming convention second, and by
    being the DAG's sink last. The name test alone was the whole rule, and once
    the target attempt started taking its support from this node that became a
    silent failure mode rather than a cosmetic one: a sketch whose goal is
    called anything else supplies NOTHING to the attempt, which is not the old
    behaviour and not the intended one either. The goal is the conjecture, so
    identify it by the conjecture.
    """
    if problem:
        from overtone.terms import eq_key
        try:
            c = problems.conjecture(problems.problem_path(problem))
        except Exception:
            c = None
        if c:
            want = eq_key(*c)
            hit = next((n for n, (l, r, _) in sketch.nodes.items()
                        if eq_key(l, r) == want), None)
            if hit:
                return hit
    named = next((n for n in sketch.nodes if n.endswith("goal")), None)
    if named:
        return named
    claims = [n for n in sketch.nodes if n not in sketch.given]
    cited = {p for n in sketch.nodes for p in sketch.nodes[n][2]}
    sinks = [n for n in claims if n not in cited]
    return sinks[0] if len(sinks) == 1 else None


def _probe_of(actions):
    """(probe, hypothesis) declared by this batch, or ({}, "").

    Carried on the actions rather than in a separate call so a batch and the
    prediction it is making cannot be recorded apart from one another. A batch
    that declares nothing is scored on whether anything moved at all, which is
    the weakest reading available and the right default.
    """
    for a in actions:
        p = a.get("probe")
        if isinstance(p, dict) and p.get("node"):
            return dict(p), a.get("hypothesis", "") or ""
    for a in actions:
        if a.get("hypothesis"):
            return {}, a["hypothesis"]
    return {}, ""


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
    elif op == "redraft":
        # Replace the decomposition wholesale, keeping the axioms, the goal, and
        # any proved nodes worth carrying. The one result this project has
        # produced is a 29-node library designed as a coherent whole; the other
        # actions can only nudge an existing sketch, so a loop restricted to
        # them cannot reach that shape however many iterations it runs.
        keep = set(action.get("keep", [])) | set(sketch.given)
        goal = action.get("goal") or _goal_of(sketch)
        if goal:
            keep.add(goal)
        unknown = sorted(keep - set(nodes))
        if unknown:
            raise ValueError(f"redraft keeps unknown node(s) {unknown}")
        nodes = {n: v for n, v in nodes.items() if n in keep}
        for spec in action.get("nodes", []):
            nodes[spec["name"]] = (spec["lhs"], spec["rhs"],
                                   list(spec.get("parents", [])))
        if goal in nodes and action.get("goal_parents") is not None:
            l, r, _ = nodes[goal]
            nodes[goal] = (l, r, list(action["goal_parents"]))
    elif op == "attempt":
        return sketch                     # handled by the loop, not an edit
    # `given` survives every edit. Dropping it turns the problem's axioms back
    # into claims on the first edit, so they get scheduled and proved -- and
    # every ratio the run reports inflates by the axiom count.
    return Sketch(nodes, given=[g for g in sketch.given if g in nodes])


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


def _report(findings):
    """Print every finding. A filter the agent cannot see is one it keeps
    tripping over, so nothing here is silent."""
    for f in findings:
        mark = {"reject": "WITHHELD", "warn": "warn", "note": "note"}[f.verdict]
        print(f"  review[{mark}] {f.node}: {f.reason}", flush=True)


def _axiom_text(path: Path):
    """Every `cnf(...)` line of the problem and its includes, as written."""
    import re
    from overtone import config
    out, seen = [], set()
    todo = [Path(path)]
    while todo:
        f = todo.pop(0)
        if f in seen or not f.exists():
            continue
        seen.add(f)
        text = f.read_text(errors="ignore")
        for inc in re.findall(r"include\('([^']+)'\)", text):
            todo.append(Path(config.tptp_root()) / inc)
        for m in re.finditer(r"cnf\(\s*(\w+)\s*,\s*(\w+)\s*,(.*?)\)\s*\.",
                             text, re.S):
            if m.group(2) == "negated_conjecture":
                continue      # the goal is passed separately, already parsed
            out.append(f"{m.group(1)} [{m.group(2)}]: "
                       f"{' '.join(m.group(3).split())}")
    return out


def _draft(problem, sketch: Sketch, agent, traj, annot):
    """Ask the agent for an initial sketch, and apply what it proposes.

    The conjecture is read from the problem file rather than described, so the
    drafted goal cannot drift from the problem it claims to be -- the same rule
    `restate` enforces, applied at draft time.
    """
    # Prefer the sketch's own axiom nodes: citing one by name is what an agent
    # should do instead of restating it, so it must see the names it can cite.
    path = problems.problem_path(problem)
    if sketch.given:
        axioms = [f"{n}: {sketch.nodes[n][0]} = {sketch.nodes[n][1]}"
                  for n in sorted(sketch.given)]
    else:
        axioms = _axiom_text(path)
    # `conjecture` normalises variables to VX/VY/...; nodes are written with
    # single uppercase letters, and showing the model two conventions invites it
    # to mix them.
    conj = tuple(re.sub(r"\bV([A-Z])\b", r"\1", t)
                 for t in problems.conjecture(path))
    print(f"drafting: {len(axioms)} axioms, goal "
          f"{conj[0]} = {conj[1]}"[:110], flush=True)
    goal = next((n for n in sketch.claims()), "goal")
    actions = list(agent.draft(problem, axioms, conj, goal_name=goal))
    actions, found = reviewlib.review(
        actions, reviewlib.context_for(problem, sketch, goal))
    _report(found)
    for act in actions:
        try:
            sketch = apply(sketch, act, annot=annot)
        except (ValueError, KeyError) as e:
            # Surfaced, not just printed. A draft that fails to apply leaves the
            # run with a bare goal, and the model was never told: one run spent
            # four of its first five iterations on a one-node sketch because its
            # whole draft had been discarded silently here.
            print(f"  DRAFT NOT APPLIED {act.get('op')} "
                  f"{act.get('name')!r}: {e}", flush=True)
            found = list(found) + [reviewlib.Finding(
                "apply", act.get("name") or act.get("op", "?"),
                reviewlib.REJECT,
                f"your draft could not be applied and was DISCARDED, so the "
                f"sketch is still just the goal: {e}")]
    batch.append_record(traj, {"iter": -1, "phase": "draft", "actions": actions,
                               "findings": [f.to_json() for f in found],
                               "sketch": sketch.to_json()})
    named = next((a.get("approach") for a in actions
                  if a.get("op") == "redraft" and a.get("approach")), "")
    print(f"  drafted {len(sketch.claims())} claim(s)"
          + (f": {named!r}" if named else ""), flush=True)
    # Draft-time findings travel into iteration 0, or the model's first turn
    # begins with no idea why its sketch is missing.
    return sketch, named, tuple(f for f in found if f.verdict != reviewlib.NOTE)


# ----------------------------------------------------------------- the loop

def run_loop(problem, sketch: Sketch, agent: Agent, *, outdir: Path,
             budget=Budget(), budgets=None, binary=None, max_iterations=6,
             total_cpu=None, directions=DIRECTIONS, annot=None, draft=True,
             ledger=None):
    """draft -> verify -> attempt -> diagnose -> act -> repeat.

    `draft` asks the agent for an initial decomposition from the problem
    statement, before anything is run. Without it a run handed a goal-only seed
    spends a full budget proving the seed cannot be verified, and the drafting
    half of the loop never happens at all -- which is what running the loop
    against a bare goal actually did.

    Stops on: the target proved, `max_iterations`, `total_cpu`, or an empty
    action list. The trajectory is written either way -- a failed run with its
    diagnoses is the training data the loop exists to produce, and is the only
    record of *why* an edit was made.
    """
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    traj = open(outdir / "trajectory.jsonl", "a", buffering=1)
    spent, spent_new, proved, history = 0.0, 0.0, False, []
    stalled, approach, tried, best_proved, approach_started = 0, "", [], -1, 0
    # Carried across iterations so an edit can be judged against what preceded
    # it: the last target measurement, the last node statuses, the probe the
    # agent declared with its edits, and the sketch to fall back to.
    prev_target, prev_nodes, probe, outcome = {}, (), {}, {}
    prev_support, prev_attempts, inconclusive_run = None, [], 0
    last_applied, last_rejected, prev_sketch = 0, 0, None
    # Detects a loop spinning with no prover work at all -- see below.
    last_new, idle = -1.0, 0
    # The verify results and attempt rows belonging to `prev_sketch`, so a
    # rollback can rebuild the state from the sketch it restores rather than
    # describing the one it just threw away.
    prev_results, prev_attempts_before = [], []
    draft_findings = ()
    if draft and hasattr(agent, "draft") and len(sketch.claims()) <= 1:
        sketch, approach, draft_findings = _draft(problem, sketch, agent, traj,
                                                  annot)
    timeline_steps, results_of_last = [], []
    # Sketch digest -> the iteration that tried it. A loop that re-proposes a
    # sketch it has already verified is going in a circle, and the only useful
    # response is to stop and say so.
    seen, stop_reason, findings = {}, None, draft_findings
    # Set when a whole batch was rejected: the sketch is unchanged, so its
    # digest repeats, but that is not the agent going in a circle -- it has not
    # had a turn with the rejection findings yet.
    retry_after_rejection = False
    # Parent drops the controller made and has not yet judged, and the nodes
    # whose drop came back worse. Restoring parents reproduces the digest the
    # sketch had before the drop, so a revert must be excused from the cycle
    # check for exactly the same reason a rejected batch is: it is the harness
    # moving, not the agent going in a circle.
    probations, probation_done, controller_edited = [], set(), False

    try:
        for i in range(max_iterations):
            digest = sketch.digest()
            if digest in seen and not (retry_after_rejection
                                       or controller_edited):
                stop_reason = (f"cycle: this sketch was already verified at "
                               f"iteration {seen[digest]}")
                print(f"iter {i}: {stop_reason}", flush=True)
                break
            seen[digest] = i
            retry_after_rejection = controller_edited = False
            v = verify(problem, sketch, outdir=outdir / f"iter{i:02d}",
                       budget=budget.node, budgets=budgets, workers=budget.workers,
                       binary=binary, directions=directions, ledger=ledger)
            # The support for the target is the GOAL NODE's declared parents,
            # not every node that happens to have proved. Sending everything was
            # the loose-bag-as-axioms configuration this project measured as a
            # timeout on MVA005-1 and worse than nothing on `teichmuller`, and it
            # consumed 58% and 83% of two agent runs' prover budgets. The channel
            # follows the same `channel_for` rule as every other node.
            goal = _target_node(sketch, problem)
            if goal is not None and not sketch.nodes[goal][2]:
                # A goal with no parents is not a decomposition of anything, and
                # nothing else in the loop complains: the target is skipped as a
                # bare baseline and the run looks cheap and busy. One run sat
                # like this for four iterations with 24 lemmas proved and never
                # supplied to anything. Repeated every turn, at reject severity,
                # because it costs the whole iteration and one `set_parents`
                # fixes it.
                proved_now = sorted(n for n in sketch.nodes
                                    if n in v["proved"] and n != goal
                                    and n not in sketch.given)
                findings = tuple(findings) + (reviewlib.Finding(
                    "controller", goal, reviewlib.REJECT,
                    f"`{goal}` has NO parents, so nothing is supplied to the "
                    f"target and it is not attempted at all. "
                    + (f"Set its parents from the {len(proved_now)} node(s) "
                       f"that have proved: {proved_now[:12]}"
                       if proved_now else
                       "Nothing has proved yet that could support it."),
                    {"proved_available": proved_now}),)
                print(f"  GOAL DISCONNECTED: {goal} has no parents; "
                      f"{len(proved_now)} proved node(s) available", flush=True)
            if goal is None:
                # Silently attempting with no support would look like a cheap
                # iteration and be a measurement of nothing.
                print("  WARNING: no goal node identified (not the conjecture, "
                      "not named *goal, and not a unique sink) -- the target "
                      "is attempted with no support", flush=True)
            declared = list(sketch.nodes[goal][2]) if goal else []
            support = [n for n in declared if n in v["proved"]]
            # on_route: `support` is the goal's own declared parents filtered to
            # what proved, so every member is on the route by construction even
            # while the set is incomplete.
            ch = (channel_for(support, sketch, goal, on_route=True)
                  if goal else "axioms")
            if not support:
                # With nothing supplied the attempt IS the problem's own
                # baseline, and for any target worth a sketch that baseline is a
                # recorded timeout -- RNG029-5 resists 4000s in both directions.
                # A gpt-5.4 run spent 600.5s of its 2045.3s of new prover time
                # (29%) re-deriving that negative three iterations running,
                # because the goal's two declared parents never proved.
                a = []
                print(f"  target has no proved support "
                      f"({len(declared)} declared parent(s), none proved) -- "
                      f"skipping the attempt: it would be the bare baseline",
                      flush=True)
            elif support == prev_support and prev_attempts:
                # Identical support means an identical input, so the ledger
                # would return the recorded answer and `cost` would charge the
                # full budget for it again. Ask once, carry the answer.
                a = [{**r, "skipped_unchanged": True, "reused": True, "cpu": 0.0,
                      "wall": 0.0} for r in prev_attempts]
                print(f"  target support unchanged ({len(support)} lemma(s)); "
                      f"carrying the previous attempt", flush=True)
            else:
                a = attempt(problem, sketch.equations(support),
                            outdir=outdir / f"iter{i:02d}", budget=budget.final,
                            binary=binary, directions=directions, ledger=ledger,
                            channel=ch, support=support)
            # Captured before `prev_support` is overwritten, or the scorer reads
            # this iteration's support as if it were the previous one's.
            lost_support = bool(prev_support) and not support
            prev_support, prev_attempts = list(support), a
            c = cost(v["results"], a)
            spent, spent_new = spent + c["cpu"], spent_new + c["cpu_new"]
            proved = any(r["proved"] for r in a)

            state = state_of(problem, sketch, v["results"],
                             outdir / f"iter{i:02d}", iteration=i,
                             slow=budget.slow, history=history,
                             findings=findings, stalled=stalled,
                             approach=approach, approaches_tried=tried,
                             iterations_on_approach=i - approach_started,
                             attempts=a, prev_target=prev_target, spent=spent)

            # Progress is the probe the agent declared coming true, not a node
            # newly proved. Proving nodes was the only thing this loop counted,
            # and a run proved 27 of them across ten iterations without ever
            # nearing the goal. `inconclusive` therefore does NOT reset the
            # stall counter however many lemmas it verified.
            # Nothing preceded the first verification, so there is no edit to
            # judge. Scoring it would charge the drafted sketch with a stall it
            # cannot have earned.
            if prev_nodes:
                outcome = score_outcome(
                    probe, target=state.target, nodes=state.nodes,
                    prev_nodes=prev_nodes, slow=budget.slow,
                    applied=last_applied, rejected=last_rejected,
                    support_lost=lost_support)
                print(f"  outcome: {outcome['outcome']} -- {outcome['why']}",
                      flush=True)
                if outcome["outcome"] in ("solved", "productive"):
                    stalled, inconclusive_run = 0, 0
                else:
                    stalled += 1
                    inconclusive_run += 1
                    print(f"  STALLED: {stalled} iteration(s) without "
                          f"productive progress ({v['n_proved']} of "
                          f"{v['n_nodes']} nodes proved)", flush=True)
            else:
                outcome = {"outcome": "baseline", "why": "the first "
                           "verification; no edits preceded it", "probe": {}}
            best_proved = max(best_proved, v["n_proved"])
            prev_target, prev_nodes = state.target, state.nodes
            # The target as it was for the sketch that was JUDGED. A rollback
            # rebuilds `state` from the restored sketch, which is right for the
            # agent and wrong for the record: one trajectory has an outcome
            # reading "the target lost all of its proved support" beside a
            # target row showing a healthy two-lemma attempt, because the two
            # described different sketches.
            judged_target = state.target
            # Both counters are recomputed from this iteration's own evidence,
            # so the agent is told about a stall in the turn it happened rather
            # than one turn late.
            state = replace(state, outcome=outcome, stalled=stalled)
            (outdir / f"sketch.{i:02d}.json").write_text(
                json.dumps(sketch.to_json(), indent=2) + "\n")

            timeline_steps.append({"label": f"iter {i}", "sketch": sketch,
                                   "results": v["results"],
                                   "note": (f"{v['n_proved']}/{v['n_nodes']} nodes, "
                                            f"{spent:.0f}s CPU")})
            results_of_last = v["results"]

            # A regression closes this branch instead of the run. The edits made
            # the target harder to reach, and the sketch that preceded them is
            # the one worth carrying, so restore it and tell the agent what was
            # undone. An agent that had to do this by hand produced a sketch
            # identical to two iterations earlier, and the cycle detector -- not
            # the mathematics -- ended the run.
            if outcome["outcome"] == "regressed" and prev_sketch is not None:
                undone = diff(sketch, prev_sketch)
                sketch = prev_sketch
                findings = tuple(findings) + (reviewlib.Finding(
                    "regression", _goal_of(sketch) or "?", reviewlib.REJECT,
                    f"{outcome['why']}. The sketch was restored to the one "
                    f"before those edits; propose a different route rather "
                    f"than re-applying them.",
                    {"reverted": undone["n_edits"],
                     "added_back": undone["added"],
                     "removed_again": undone["removed"]}),)
                print(f"  REVERTED {undone['n_edits']} edit(s) after a "
                      f"regression", flush=True)
                # The state must describe the sketch that now EXISTS. Handing
                # the agent the reverted-away sketch while review runs against
                # the restored one puts the two out of step: a model proposed a
                # node because its state said it was absent, and review rejected
                # it as a duplicate because it had just been restored. Rebuild
                # from the restored sketch's own last results.
                state = state_of(problem, sketch, prev_results,
                                 outdir / f"iter{i:02d}", iteration=i,
                                 slow=budget.slow, history=history,
                                 findings=findings, stalled=stalled,
                                 approach=approach, approaches_tried=tried,
                                 iterations_on_approach=i - approach_started,
                                 attempts=prev_attempts_before,
                                 prev_target=None, outcome=outcome, spent=spent)
                state = replace(state, outcome=outcome, stalled=stalled)

            proposed = [] if proved else list(agent.act(state))
            probe, hypothesis = _probe_of(proposed)
            actions, findings = reviewlib.review(
                proposed, reviewlib.context_for(problem, sketch))
            _report(findings)
            rec = {"iter": i, "digest": digest, "proved": proved,
                   "cpu_spent": round(spent, 1), "cpu_new": round(spent_new, 1),
                   "n_proved": v["n_proved"], "n_nodes": v["n_nodes"],
                   "missing": v["missing"],
                   "slow": [n.name for n in state.slow()],
                   "failing": [n.name for n in state.failing()],
                   "diffs": state.diffs, "actions": actions,
                   "findings": [f.to_json() for f in findings],
                   "stalled": stalled, "approach": approach,
                   # the sketch that was judged, not the one a rollback restored
                   "target": judged_target, "outcome": outcome,
                   "target_after_rollback": (state.target
                                             if state.target is not judged_target
                                             else None),
                   "contact": state.contact,
                   "probe": probe, "hypothesis": hypothesis,
                   "sources": list(state.sources)}
            batch.append_record(traj, rec)
            history.append(rec)
            print(f"iter {i}: {v['n_proved']}/{v['n_nodes']} nodes, "
                  f"{'PROVED' if proved else 'not proved'}, "
                  f"{spent:.1f}s CPU charged ({spent_new:.1f}s new), "
                  f"{len(actions)} action(s)", flush=True)

            if proved:
                break
            if not actions:
                if proposed:
                    # Review withheld the whole batch. That is not the agent
                    # declining to continue, and reporting it as such ends a run
                    # on a harness artifact -- the same class of false ending as
                    # the cycle detector firing on a revert. The agent has not
                    # yet had a turn with these findings, so give it one; the
                    # sketch is unchanged, so `seen` still catches a real circle
                    # on the iteration after this.
                    print(f"  all {len(proposed)} proposed edit(s) were "
                          f"withheld by review -- the agent gets the findings "
                          f"and another turn", flush=True)
                    # Accounting has to reflect THIS turn, or the next scoring
                    # judges a batch that never ran against the one before it.
                    last_applied, last_rejected = 0, len(proposed)
                    retry_after_rejection = True
                    continue
                stop_reason = "the agent proposed no further edits"
                break
            if total_cpu and spent_new >= total_cpu:
                print(f"  stopping: {spent_new:.1f}s new >= total_cpu "
                      f"{total_cpu}", flush=True)
                break

            # A loop can spin without spending any prover time, and when it does
            # it spins invisibly: one run burned six model calls and six
            # iterations at a constant `cpu_new` because every redraft raised in
            # `apply` and nothing ever ran. Every real iteration verifies at
            # least one node or attempts the target, so no new CPU across three
            # consecutive turns means the loop is not working, not that the
            # problem is hard. Say so rather than running out the budget.
            idle = 0 if spent_new > last_new else idle + 1
            last_new = spent_new
            if idle >= 3:
                stop_reason = (f"no prover work in {idle} consecutive "
                               f"iterations ({spent_new:.1f}s new CPU "
                               f"throughout) -- the loop is spinning")
                print(f"  {stop_reason}", flush=True)
                break

            # The approach budget was advisory: it printed and hoped the model
            # would obey a system-prompt rule. One run then spent ten iterations
            # and 11,647 prover-seconds on a single route. At the limit, or after
            # two consecutive inconclusive turns, only a redraft is accepted --
            # small edits cannot rescue a decomposition that is aimed wrong,
            # they can only make it bigger.
            # The trigger is the approach budget alone. Two consecutive
            # inconclusive turns was tried and is far too tight: under the new
            # scorer a turn is inconclusive whenever the probed node did not
            # move, which is the normal case early in a decomposition, so it
            # ended runs at two iterations. `stalled` still carries that
            # information to the agent, which is where the softer signal belongs.
            spent_approach = i - approach_started
            if (spent_approach >= APPROACH_BUDGET
                    and not any(x.get("op") == "redraft" for x in actions)):
                why = f"{spent_approach} iterations on approach {approach!r}"
                held = [x.get("op") for x in actions]
                findings = tuple(findings) + (reviewlib.Finding(
                    "controller", approach or "(unnamed)", reviewlib.REJECT,
                    f"{why}: only a `redraft` is accepted now. {len(held)} "
                    f"edit(s) {held} were withheld. Name a route genuinely "
                    f"different from everything in approaches_already_tried.",
                    {"withheld": held}),)
                print(f"  CONTROLLER: {why} -- withholding {len(held)} "
                      f"non-redraft edit(s)", flush=True)
                _report(findings[-1:])
                stop_reason = ("approach exhausted and the agent did not "
                               "redraft")
                print(f"  {stop_reason}", flush=True)
                break

            before, applied, rejected = sketch, [], 0
            for act in actions:
                try:
                    sketch = apply(sketch, act, annot=annot)
                    applied.append(act)
                except (ValueError, KeyError) as e:
                    # One malformed edit must not end a run that has already
                    # spent thousands of prover-seconds. Report, skip, continue.
                    rejected += 1
                    print(f"  rejected {act.get('op')} "
                          f"{act.get('name')!r}: {e}", flush=True)
                    findings = tuple(findings) + (reviewlib.Finding(
                        "apply", act.get("name", "?"), reviewlib.REJECT,
                        f"the edit was invalid and was not applied: {e}"),)
            d = diff(before, sketch)
            # Rotate the approach only for a redraft that applied AND changed
            # something. One that raised was skipped, and one that reproduced
            # the same sketch took no new route -- recording either would claim
            # a change the sketch never made.
            for act in ([a for a in applied if a.get("op") == "redraft"][-1:]
                        if d["n_edits"] else []):
                tried = tried + [{"approach": approach or "(unnamed)",
                                  "iterations": i - approach_started,
                                  "peak_proved": best_proved}]
                approach, approach_started = act.get("approach", "") or approach, i
                stalled, best_proved, inconclusive_run = 0, -1, 0
                print(f"  REDRAFT -> {approach!r}", flush=True)
            if not d["n_edits"]:
                if rejected:
                    # Every edit was invalid, so the sketch is unchanged -- but
                    # the agent now knows why and has not had a turn to use
                    # that. Stopping here would end the run on a fixable
                    # mistake; `seen` still catches a genuine circle.
                    print(f"  {rejected} edit(s) rejected, none applied -- "
                          f"the agent gets the findings and another turn",
                          flush=True)
                    retry_after_rejection = True
                    continue
                stop_reason = "the agent's edits left the sketch unchanged"
                print(f"  {stop_reason}", flush=True)
                break
            # Carried into the next iteration so the scorer can judge these
            # edits, and so a regression has something to fall back to.
            prev_sketch, prev_results = before, v["results"]
            prev_attempts_before = a
            last_applied, last_rejected = len(applied), rejected
            print(f"  applied {d['n_edits']} edit(s): +{len(d['added'])} "
                  f"-{len(d['removed'])} ~{len(d['restated'])} "
                  f"parents:{len(d['reparented'])}", flush=True)

            # ---- controller: parents the certificates did not cite ----
            # After the agent's edits, so both land in the sketch the NEXT
            # iteration verifies, and the `state` this iteration showed still
            # describes the sketch that was actually run. Judging comes first:
            # this iteration's rows are the measurement of last iteration's
            # drop.
            restores, kept, reverted = probation_verdicts(probations,
                                                          v["results"])
            for p, best in kept:
                was = "?" if p.cpu is None else f"{p.cpu:.1f}s"
                now = "?" if best.get("cpu") is None else f"{best['cpu']:.1f}s"
                print(f"  parent drop on {p.node} stands: {was} -> {now} "
                      f"without {list(p.dropped)}", flush=True)
            for p, why in reverted:
                probation_done.add(p.node)
                findings = tuple(findings) + (reviewlib.Finding(
                    "controller", p.node, reviewlib.NOTE,
                    f"{why}, so its parents were put back. The proof of "
                    f"{p.node} did not cite them, but the search needs them; "
                    f"do not drop them again.",
                    {"restored": list(p.dropped)}),)
                print(f"  RESTORED {p.node}'s parents: {why}", flush=True)
            probations = [p for p in probations
                          if p.node not in {q.node for q, _ in kept}
                          and p.node not in {q.node for q, _ in reverted}]

            drops, new_probations = probation_drops(
                # The target of the sketch as it is NOW: `goal` was read before
                # the agent's edits, and an edit that moves the sink would let
                # the drop strip the new target -- the one node it must not
                # touch.
                sketch, v["results"], target=_target_node(sketch, problem),
                probe_node=(probe or {}).get("node"),
                active={p.node for p in probations}, done=probation_done,
                iteration=i)
            for act in restores + drops:
                try:
                    sketch = apply(sketch, act, annot=annot)
                    controller_edited = True
                except (ValueError, KeyError) as e:
                    # A drop is an optimisation, never a reason to end a run.
                    print(f"  controller edit on {act.get('name')!r} skipped: "
                          f"{e}", flush=True)
                    new_probations = [p for p in new_probations
                                      if p.node != act.get("name")]
            for p in new_probations:
                findings = tuple(findings) + (reviewlib.Finding(
                    "controller", p.node, reviewlib.NOTE,
                    f"{p.node} proved in {'?' if p.cpu is None else f'{p.cpu:.1f}s'}"
                    f" and its proof never cited {list(p.dropped)}, so those "
                    f"parents were dropped to see whether the search is faster "
                    f"without them. They go back automatically if it is not.",
                    {"dropped": list(p.dropped)}),)
                print(f"  DROPPED {list(p.dropped)} from {p.node} "
                      f"(uncited by its proof; on probation)", flush=True)
            probations += new_probations
    finally:
        traj.close()

    # The approach still running when the loop ended is part of the history;
    # without this the last one -- often the only one -- is missing from the
    # record a later run reads to avoid repeating a route.
    if len(history) > approach_started:
        tried = tried + [{"approach": approach or "(unnamed)",
                          "iterations": len(history) - approach_started,
                          "peak_proved": best_proved}]
    usage = getattr(agent, "usage", None)
    if usage is not None and usage.calls:
        print(f"\n  agent total: {pricing.render(usage)}", flush=True)
    out = {"problem": problem, "proved": proved, "cpu_total": round(spent, 1),
           # What this sketch costs from cold vs what this run actually spent.
           # They differ by thousands of seconds once the ledger starts serving
           # repeats, and quoting one for the other misstates both.
           "cpu_new": round(spent_new, 1),
           "iterations": len(history), "history": history,
           "stop_reason": stop_reason or ("proved" if proved else "budget"),
           "usage": usage.to_json() if usage is not None else None,
           "approaches_tried": tried,
           "sketches_tried": seen, "final_sketch": sketch.to_json()}
    (outdir / "loop.json").write_text(json.dumps(out, indent=2) + "\n")
    # A loop's blueprint is a trajectory: it already produced one sketch per
    # iteration, and the edits between them are the record of what it decided.
    blueprint.write_for_run(
        sketch, results_of_last, outdir, run_dir=outdir / f"iter{len(history)-1:02d}",
        timeline=timeline_steps,
        title=f"{problem} — loop",
        subtitle=(f"{len(history)} iteration(s) · "
                  f"{'proved' if proved else 'not proved'} · {spent:.0f}s CPU"))
    return out
