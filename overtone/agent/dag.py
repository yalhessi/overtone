"""A sketch as a dependency DAG, and verification in the scope its edges imply.

Replaces the flat lemma list that `sketch.py` and `ladder.py` produce. The list
was not merely less expressive -- it made the two most consequential decisions
unrepresentable, and both were being made wrongly.

**Scope.** `alt12_additive` follows in four rewrite steps from five lemmas that
had all verified. Proved standalone it timed out at 300s and needed 592.5s at a
larger budget; given exactly those five parents as axioms it proves in 0.2s, and
in the goal direction that otherwise times out, in 0.0s. Roughly 3000x for
information we already held and were discarding. Supplying all thirteen verified
lemmas instead of the five is no better (0.1s), so scope follows the *direct
parents* -- `"closure"` exists to be measured against, not because it is
expected to win.

Standalone remains right for donor ladders, and that is not a contradiction: a
donor rung came from a real proof and is reachable from the axioms by
construction, while a drafted rung is drafted precisely because it is not.
`ladder.py` measured 94.3s standalone against 324.9s chained over 20 donor rungs.
The distinction the old flag could not draw is *which kind of rung this is*, and
a node with no parents recorded is exactly the donor case.

**Channel.** On the same two lemmas, hints did essentially nothing: `alt12` never
proved from any hint configuration, and its five parents as hints (>600.7s) were
worse than supplying nothing (592.5s). That inverts MVA005-1, where 20 lemmas as
axioms timed out and the identical set as hints proved in 173.6s.

Both are real. An axiom joins the rewrite system and forms critical pairs with
every existing rule -- ruinous for a large approximate set, decisive for a small
exact one. So the channel follows from whether the lemmas are *known to be the
parents of this goal*, which is a property of the sketch's structure, not of its
size. `channel_for` reads that structure; `AXIOM_MAX` is only a guard against a
pathologically large parent set.

TPTP supplies an independent instance of the same effect. RNG025-4 and RNG025-5
have the same conjecture and the same axiom include; RNG025-5 adds seven true,
relevant sign lemmas as axioms. Same screen, build, budget and direction:
RNG025-4 proves in 371.9s, RNG025-5 times out, and still times out at 4000s.
"""
import hashlib
import json
import re
import time
import multiprocessing as mp
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path

from overtone import proofs
from overtone import runner
from overtone.agent import hints as hintlib
from overtone.agent import ledger as ledgerlib
from overtone.runner import BASE_FLAGS

# Both goal directions, always. Three trilinearity lemmas prove under
# --flatten-goal and time out under the other; a single-direction run concluded
# from that failure that the subdivision was mathematically wrong. It was not.
DIRECTIONS = ("--no-flatten-goal", "--flatten-goal")

# Above this many lemmas, prefer hints even when they are genuine parents.
# Not pinned by measurement: 13 as axioms is fine (0.1s) and 20 as axioms times
# out, and those are different problems, so the boundary lies somewhere in
# between and may not be a size boundary at all.
AXIOM_MAX = 13


class Sketch:
    """Named equations plus the edges saying which proves which.

    `nodes` maps name -> (lhs, rhs, parents). A node with no parents is a claim
    that it follows from the problem's own axioms; that is the donor-ladder case
    and reduces to standalone verification.

    `given` names nodes that are the problem's OWN axioms rather than claims.
    They are never proved -- they are true by assumption and twee already has
    them from the problem file. They exist so the problem has one canonical
    shape in the DAG: without them an agent invents its own encoding of the
    axioms, and one drafted four nodes that were verbatim copies of axioms,
    proving them in 0.0s for nothing. With them, an agent cites an axiom by name
    instead of restating it, and a lemma's derivation records which axioms it
    rests on.
    """

    def __init__(self, nodes, given=()):
        self.nodes = dict(nodes)
        self.given = frozenset(given)
        self.validate()

    @classmethod
    def from_problem(cls, problem, goal="goal"):
        """The canonical seed: every axiom as a given node, plus the goal.

        Axiom nodes keep their TPTP names, so `parents: ["commutator"]` -- which
        is what an agent reaches for unprompted -- means exactly what it looks
        like.
        """
        from overtone import problems
        path = problems.problem_path(problem)
        nodes, given = {}, []
        for name, (lhs, rhs) in problems.named_axioms(path).items():
            nodes[name] = (lhs, rhs, [])
            given.append(name)
        conj = problems.conjecture(path)
        nodes[goal] = (conj[0], conj[1], [])
        return cls(nodes, given)

    def is_given(self, name):
        return name in self.given

    def claims(self):
        """Node names that are claims -- everything that is not an axiom."""
        return [n for n in self.nodes if n not in self.given]

    @classmethod
    def from_lemmas(cls, lemmas):
        """A flat lemma list, i.e. every node claims to follow from the axioms.

        What `proofs.lemmas` and the donor path produce. Verification of such a
        sketch is standalone, which is what the donor ladder measured as correct.
        """
        return cls({f"lemma_{n}": (lhs, rhs, []) for n, lhs, rhs in lemmas})

    def validate(self):
        for name, (_, _, parents) in self.nodes.items():
            unknown = [p for p in parents if p not in self.nodes]
            if unknown:
                raise ValueError(f"{name}: unknown parents {unknown}")
            if name in self.given and parents:
                raise ValueError(f"{name} is an axiom and cannot have parents")
        unknown = sorted(self.given - set(self.nodes))
        if unknown:
            raise ValueError(f"given names no such node: {unknown}")
        self.topological()     # raises on a cycle

    def topological(self):
        """Every node after all of its parents, as one flat list. Raises on a cycle.

        Two jobs, and neither is a tier: the acyclicity check, and the order
        `verify` offers nodes to the pool in.

        Validation used to call `layers()` for its side effect -- correctness
        riding on a *layout* helper, so a change to how the blueprint ranks nodes
        could have quietly stopped checking the DAG. And scheduling used to walk
        those layers with a barrier between them, which is a far stronger
        promise than anything needs: nothing waits here, so the only guarantee
        the order has to make is that a parent is OFFERED before its child. That
        is what lets a child's proof be grounded the moment it lands instead of
        retroactively.
        """
        done, out = set(self.given), sorted(self.given)
        remaining = {n: v for n, v in self.nodes.items() if n not in self.given}
        while remaining:
            ready = sorted(n for n, (_, _, ps) in remaining.items()
                           if all(p in done for p in ps))
            if not ready:
                raise ValueError(f"cycle among {sorted(remaining)}")
            out += ready
            done |= set(ready)
            for n in ready:
                del remaining[n]
        return out

    def layers(self, with_axioms=True):
        """Topological layers. **Layout only** -- nothing schedules on these.

        Layer assignment is most of a Sugiyama pass, which is why
        `blueprint._positions` wants it: rank the nodes, order within a rank by
        parent barycentre, draw. That is a legitimate use and the only one left.

        It is deliberately NOT how verification is scheduled. A barrier per layer
        idles the pool whenever a layer is narrower than `workers`, makes every
        node wait on the slowest member of the tier above it, and -- because a
        node only ran once all its parents had proved -- let a single failed
        ancestor remove an entire subtree, the goal included, without anything
        saying so. `topological` is the scheduling order; `grounding` is what
        replaced the barrier's soundness guarantee.

        The problem's axioms still form layer 0 -- a tier of their own rather
        than being mixed in with parentless claims, which they resemble
        structurally and differ from completely: a claim at that position is
        something to prove, an axiom is something assumed.
        """
        done = set(self.given)
        out = [sorted(self.given)] if (with_axioms and self.given) else []
        remaining = {n: v for n, v in self.nodes.items() if n not in self.given}
        while remaining:
            ready = sorted(n for n, (_, _, ps) in remaining.items()
                           if all(p in done for p in ps))
            if not ready:
                raise ValueError(f"cycle among {sorted(remaining)}")
            out.append(ready)
            done |= set(ready)
            for n in ready:
                del remaining[n]
        return out

    def scope(self, name, how="parents"):
        """Which other nodes accompany `name`.

        "none" reproduces standalone verification, "parents" the direct parents,
        "closure" every ancestor. Closure is 8 lemmas more than parents on the
        alternative-ring sketch and no faster, so it is here to be measured.
        """
        if how == "none":
            return []
        if how == "parents":
            return list(self.nodes[name][2])
        if how != "closure":
            raise ValueError(f"unknown scope {how!r}")
        seen, stack = [], list(self.nodes[name][2])
        while stack:
            n = stack.pop()
            if n not in seen:
                seen.append(n)
                stack += self.nodes[n][2]
        return seen

    def equations(self, names, skip_given=True):
        """(lhs, rhs) for each name. Axiom nodes are dropped by default.

        An axiom is already in the problem file, so supplying it again as a
        parent would state it twice -- changing the input bytes, and so the
        ledger key, for a run that is semantically identical. Citing an axiom as
        a parent is documentation of a derivation, not a request to re-supply it.
        """
        return [(self.nodes[n][0], self.nodes[n][1]) for n in names
                if not (skip_given and n in self.given)]

    def to_json(self):
        """`{name: {lhs, rhs, parents}}` -- JSON-safe, order preserved.

        A sketch used to exist only as a Python literal in a script. The runner
        revises one across iterations and has to persist it in between, and a
        trajectory records the sketch at every step.
        """
        return {n: {"lhs": l, "rhs": r, "parents": list(p),
                    **({"given": True} if n in self.given else {})}
                for n, (l, r, p) in self.nodes.items()}

    def digest(self) -> str:
        """Identity of this sketch, for detecting that a loop has gone in a circle.

        Over *statements*, not names. A node is its equation and its parents'
        equations; what it is called is a label the prover never sees. Hashing
        names let one agent run circle for nine iterations: the same two nodes
        failed at iterations 1-4, came back renamed `..._zeroed` and failed at
        5-7, and reverted at 8-9, and every rename read as a fresh sketch.

        Parent *order* is kept, because it decides the order equations enter
        twee and therefore the search, exactly as in the run ledger. Two
        sketches differing only in how a parent list is ordered are different
        questions and must not be mistaken for a repeat. `eq_key` is
        orientation- and alpha-insensitive for the same reason it is everywhere
        else here: `a = b` and `b = a` under renamed variables are one fact.
        """
        import hashlib
        from overtone.terms import eq_key
        key = {n: eq_key(l, r) for n, (l, r, _) in self.nodes.items()}
        canon = json.dumps(sorted(
            [list(key[n]), [list(key[p]) for p in p_], n in self.given]
            for n, (_, _, p_) in self.nodes.items()))
        return hashlib.sha256(canon.encode()).hexdigest()[:16]

    @classmethod
    def from_json(cls, obj):
        return cls({n: (v["lhs"], v["rhs"], list(v.get("parents", [])))
                    for n, v in obj.items()},
                   given=[n for n, v in obj.items() if v.get("given")])


def grounding_errors(sketch: Sketch, problem) -> list:
    """Ways `sketch` assumes more than `problem` does. Empty means it does not.

    Every node must follow from the problem's own axioms -- a subset of them is
    fine, more is not. Two ways a sketch can quietly stop being about the
    problem, both of which this rejects:

    **An assumption that is not an axiom.** `given` marks a node as true without
    proof. If that node is not actually one of the problem's axioms, the sketch
    has introduced a new one, and everything downstream is a theorem of a
    stronger theory than the problem states. That is exactly how RNG027-10 and
    RNG029-10 were briefly claimed and then withdrawn -- an unchecked assumption
    turns lemmas into hypotheses without anything looking wrong.

    **A symbol the problem does not have.** A node naming a function outside the
    problem's signature is a definitional extension, not a consequence: nothing
    in the axioms constrains it, so the node says nothing about this theory.

    Checked before any prover time, because both faults produce results that
    look perfectly good and are about the wrong theory.
    """
    from overtone import problems
    from overtone.terms import eq_key, symbols_in

    path = problems.problem_path(problem) if isinstance(problem, str) else problem
    errs = []

    axioms = problems.axiom_equations(path)
    for n in sorted(sketch.given):
        lhs, rhs, _ = sketch.nodes[n]
        if eq_key(lhs, rhs) not in axioms:
            errs.append(f"{n} is marked given but is not an axiom of {problem}; "
                        f"a sketch may use a subset of the problem's axioms, "
                        f"never a new one")

    known = {name for name, _ in problems.problem_symbols(path)}
    for n, (lhs, rhs, _) in sorted(sketch.nodes.items()):
        new = sorted(symbols_in(f"{lhs} {rhs}") - known)
        if new:
            errs.append(f"{n} uses symbol(s) {new} that {problem} does not have; "
                        f"a node outside the problem's signature is a new "
                        f"definition, not a consequence of its axioms")
    return errs


def unproved_ancestors(sketch: Sketch, name, proved):
    """Ancestors of `name` that did not prove, dependency order, nearest first.

    Empty means every ancestor is established. This was `loop._blocking`, and it
    was named for the schedule: a node whose parents had not proved was never
    scheduled at all, so one failed ancestor silently took a whole subtree out
    of the run. The scheduler no longer works that way -- every claim is
    attempted -- so what this answers now is what a node's proof would still be
    resting on, which is the question the goal findings ask and the fallback
    `grounding` uses to continue a chain through a node that never proved.
    """
    proved, seen, out = set(proved or ()), set(), []
    stack = list(sketch.nodes[name][2])
    while stack:
        n = stack.pop(0)
        if n in seen or n in proved or n in sketch.given:
            continue
        seen.add(n)
        out.append(n)
        stack += sketch.nodes[n][2]
    return out


def frontier_depth(sketch: Sketch, goal, grounded):
    """Hops from `goal` to the furthest node on its route that is not grounded.

    0 means the frontier is at the conjecture itself: everything the goal rests
    on is established and only the goal is open. 1 means one obligation stands
    between them, 2 that the obligation now rests on something open in turn.

    This is the structural successor to `proxy_contact`'s artifact depth, and it
    exists because the scheduler change would otherwise silence that signal.
    The measurement it has to preserve: two derived-sketch runs both opened at
    depth 1 -- one obligation, running and failing -- subdivided it at iteration
    0 into intermediates that did not prove, went to depth 2, and neither
    recovered in nine and ten further iterations.

    The old depth read that off *which artifact produced a contact number*,
    which worked only because a node with unproved parents was never scheduled
    and so left no artifact. Every claim runs now, so the goal almost always has
    an artifact and that depth would sit at 0 through exactly the edit it was
    built to catch. Counting the hops instead measures the same thing directly
    and depends on nothing about which searches happened to leave a file.

    Grounded ancestors are not traversed: grounding is a least fixed point, so
    everything above a grounded node is grounded too and can add no depth.
    """
    if not goal or goal not in sketch.nodes:
        return None
    ground, seen, best = set(grounded or ()), {goal: 0}, 0
    queue = [goal]
    while queue:
        n = queue.pop(0)
        for p in sketch.nodes[n][2]:
            if p in sketch.given or p in ground:
                continue
            d = seen[n] + 1
            if seen.get(p, -1) >= d:
                continue
            seen[p] = d
            best = max(best, d)
            queue.append(p)
    return best


def grounding(sketch: Sketch, results, proved=()):
    """-> (grounded names, {node: assumptions it still rests on, nearest first}).

    The soundness the layer barrier used to enforce by accident, stated instead.
    A node is **grounded** when it proved and everything its proof rests on is
    grounded, back to the problem's own axioms; a node that proved but rests on
    something unproved is **conditional** -- a real implication, and not yet a
    theorem of this problem.

    What a node rests on is read from the run that actually happened, never from
    its declared parents. Three ways those differ, and each one would ground or
    condemn the wrong node:

      * **The hints channel adds nothing to the axiom set.** A hint steers the
        search; it is not assumed. A hints-channel proof therefore assumes
        nothing and is grounded outright.
      * **`Sketch.equations` drops `given` nodes**, because an axiom is already
        in the problem file and re-supplying it would state it twice. So a
        declared axiom parent is never an assumption, and `support` -- the
        post-filter list carried on the job -- is the only list that says what
        the prover really received.
      * **A proof that never cites a supplied lemma is a proof without it.** The
        certificate is a derivation; if it does not use an assumption, the
        statement follows from the rest. So a node whose certificate names none
        of its ungrounded support is grounded on what remains.

    That last one is the one that fails silently. `used_support is None` means
    *not attributed* -- a failed run, the hint channel, an artifact that is gone
    -- and must never be read as "used nothing"; only a non-None value may
    narrow what a node depends on. `_support_usage` documents the same rule at
    the point the field is produced.

    The verdict is read from `blueprint.best_row`, the same row a node's status
    and timing come from. Reading a different one would let a node be grounded
    on one direction's support and timed on the other's, and the two directions
    of one node routinely differ in both.

    Least fixed point, so nothing grounds itself and a cycle -- which `validate`
    already forbids -- could not either. `proved` names nodes an earlier run
    established, which arrive with no rows and are trusted exactly as `verify`
    already trusts them.
    """
    from overtone.agent import blueprint

    ground = set(sketch.given)
    rows_by = {}
    for r in results or ():
        rows_by.setdefault(r.get("node"), []).append(r)

    # What each node that proved would have to assume. Absent from `need`
    # entirely means it did not prove, which is a different thing from assuming
    # nothing and is why the chain walk below falls back to declared parents.
    need = {}
    for name in sketch.nodes:
        if name in ground:
            continue
        best = blueprint.best_row(rows_by.get(name, ()))
        if best is None:
            if name in proved:
                need[name] = ()        # established by an earlier run
            continue
        support = list(best.get("support") or ())
        if best.get("channel") != "axioms":
            support = []               # hints join no axiom set
        used = best.get("used_support")
        need[name] = tuple(support if used is None
                           else [s for s in support if s in used])

    changed = True
    while changed:
        changed = False
        for name, assumed in need.items():
            if name not in ground and all(a in ground for a in assumed):
                ground.add(name)
                changed = True

    conditional = {}
    for name, assumed in need.items():
        if name in ground:
            continue
        seen, chain, stack = set(), [], list(assumed)
        while stack:
            a = stack.pop(0)
            if a in seen or a in ground:
                continue
            seen.add(a)
            chain.append(a)
            # A node that never proved has no `need` entry, so the chain
            # continues through what it was DECLARED to rest on -- otherwise the
            # walk stops at the first dead assumption and reports a shorter
            # dependency than the sketch actually claims.
            stack += list(need[a] if a in need else sketch.nodes[a][2])
        conditional[name] = tuple(chain)
    return ground, conditional


def channel_for(names, sketch, node, override=None, *, on_route=False):
    """"axioms" or "hints" for this set of supporting lemmas.

    Axioms when the set is small and is exactly this node's recorded parents;
    hints otherwise. See the module docstring -- an axiom forms critical pairs
    with every rule, which a precise handful earns and a loose bag does not.

    `on_route` says the caller already knows these names lie on the node's
    declared route, so only the size test applies. The target attempt needs it:
    its support is the goal's declared parents INTERSECTED with what has proved,
    so while the sketch is incomplete that set is a strict subset and the
    equality test sends it to the hint channel -- where FINDINGS records it is
    worth nothing. An incomplete exact set is not a loose bag. The measured
    distinction is precision, not completeness: five exact parents as axioms
    were worth ~3000x over none, and the same five as hints were worth less than
    supplying nothing.
    """
    if override:
        return override
    if not names:
        return "axioms"                       # nothing either way; keep it simple
    if len(names) > AXIOM_MAX:
        return "hints"
    if on_route:
        return "axioms"
    return "axioms" if set(names) == set(sketch.nodes[node][2]) else "hints"


def _job(j):
    """One prover invocation. Module-level so it pickles into a process pool.

    Takes a dict, not a tuple. A positional job tuple silently half-applied a
    signature change twice -- once reaching a live run as an unpickling error --
    because adding a field means editing every construction site and missing one
    is invisible until something executes.
    """
    problem, node = j["problem"], j["node"]
    lhs, rhs, eqs = j["lhs"], j["rhs"], j["eqs"]
    channel, direction, budget = j["channel"], j["direction"], j["budget"]
    outdir, binary = j["outdir"], j.get("binary")
    reuse, ledger = j.get("reuse", True), j.get("ledger")
    cancel = j.get("cancel")
    # Names for `eqs`, positionally aligned with it. See `_support_usage`: this
    # is the post-`skip_given` list, and only it can resolve a `parent_N`.
    support = list(j.get("support") or ())
    # Artifacts are addressed by the run's own identity, computed below, so two
    # invocations differing in anything that identity captures -- which equations
    # were supplied, in what order, under which flags and build -- cannot land in
    # the same file. Naming by node and direction alone let a standalone retry
    # destroy the parented run it was retrying, in both RNG033-8 iterations, and
    # made a later comparison of the two searches silently compare two copies of
    # the same one.
    stem = f"{node}.{direction[2:]}"
    kw, flags = {}, [*BASE_FLAGS, direction]
    # The two channels are not alternatives, and the reference implementation
    # says why. `Twee.addHint` puts a hint into `st_hints`, a separate index
    # that only ever reaches `CP.score`; hints never become rules. So a hint
    # carries NO deductive power -- it cannot rewrite anything -- and it cannot
    # enlarge the search either, because it forms no critical pairs. What it
    # does is make a matching subterm look smaller: `score` charges `hint_cost`
    # instead of the term's structure, which at factor 0.5 against
    # `cfg_funweight = 1` is roughly half, so the critical pair is picked
    # sooner.
    #
    # That is the whole asymmetry. A lemma the proof NEEDS has to be an axiom.
    # A lemma that merely might help costs critical pairs against every rule as
    # an axiom, and only misdirected priority as a hint. So an arm can supply a
    # small set as axioms and keep the rest steering, which is what `hint_eqs`
    # is for.
    hint_eqs = list(j.get("hint_eqs") or ())
    if channel == "axioms":
        kw["extra_axioms"] = eqs
    else:
        hint_eqs = list(eqs) + hint_eqs
    if hint_eqs:
        terms = []
        for l, r in hint_eqs:
            terms += [x for x in (l, r) if "(" in x and x not in terms]
        if terms:
            kw["hints"] = terms
            flags = [*BASE_FLAGS, *hintlib.HINT_FLAGS, direction]
    # Per-node search options -- a term ordering, say. They go last so a node can
    # override a BASE_FLAGS default, and they are part of the ledger key below,
    # so adding one to a single node re-runs that node and leaves every other
    # node's recorded proof reusable. That scoping is the point: a lemma proved
    # under one ordering is still a theorem, and it enters a downstream run as
    # axiom text, so the ordering that found it has no bearing there.
    flags = [*flags, *j.get("extra_flags", ())]
    # Write first, key the bytes, then name the artifact by that key: identity
    # is over what was actually handed to twee and cannot drift from the
    # arguments that produced it.
    tmp = Path(outdir) / f".{stem}.building.p"
    runner.write_problem(problem, tmp, goal=(lhs, rhs), goal_prefix="sk_dag_",
                         axiom_prefix="parent", **kw)
    key = ledgerlib.key_for(tmp, flags, binary)
    tag = f"{stem}.{ledgerlib.short(key)}"
    path = Path(outdir) / f"{tag}.p"
    tmp.replace(path)
    if reuse:
        prior = ledgerlib.lookup(key, budget, ledger=ledger)
        if prior is not None:
            row = {"node": node, "direction": direction, "channel": channel,
                   "n_support": len(eqs), "result": prior.get("result"),
                   "proved": bool(prior.get("proved")),
                   "cpu": prior.get("cpu") or 0.0,
                   "wall": prior.get("wall") or 0.0, "reused": True,
                   "key": key, "input": str(path),
                   **_prior_artifact(prior)}
            # A reused row is attributed from the recorded artifact, which is the
            # same search by construction. Without this a node keeps its support
            # evidence for one iteration and loses it the moment the ledger
            # starts answering -- which is every iteration after the first.
            return {**row, **_support_usage(support, channel, row["proved"],
                                            row.get("output"))}
    r = runner.run(path, flags, budget, problem=problem, binary=binary,
                   cancel=cancel)
    # Keep the output either way. A failed run is the more informative one: with
    # --all-lemmas it still lists everything derived before the budget ran out,
    # and those are the candidate missing nodes. `assoc_def_add` -- worth 18x on
    # assoc_add_1 -- was read off exactly this kind of listing.
    out_path = Path(outdir) / f"{tag}.{'out' if r.proved else 'fail.out'}"
    out_path.write_text(r.output)
    # Full precision, not 1 dp: these rows are summed over hundreds of runs to
    # report what a problem cost, and rounding first accumulates error. Readers
    # that display a time format it themselves.
    row = {"node": node, "direction": direction, "channel": channel,
           "n_support": len(eqs), "result": r.status, "proved": r.proved,
           "cpu": r.cpu, "wall": r.wall, "key": key,
           "input": str(path), "output": str(out_path)}
    # A cancelled run answered nothing. Recording it would let reuse skip a
    # question that was never resolved.
    if r.status != "Cancelled":
        ledgerlib.record(key, row, budget, ledger=ledger)
    # After the ledger write, not before: the recorded fields are fixed by
    # `ledger.record` and attribution is derived from the artifact, so it is
    # this run's reading of the record rather than part of it.
    row.update(_support_usage(support, channel, r.proved, out_path))
    return row


def _support_usage(support, channel, proved, out_path):
    """Which of the supplied support lemmas the proof certificate names.

    The index mapping is the part that breaks silently. twee's `parent_N` is a
    1-based index into `extra_axioms`, which is what `Sketch.equations` returned
    -- and that drops `given` nodes (an axiom is already in the problem file, so
    re-supplying it would state it twice). So `parent_N` does NOT index a node's
    declared parents whenever any of them is an axiom, and resolving it against
    `sketch.nodes[n][2]` attributes usage to the wrong lemma. `support` is
    therefore the filtered list actually handed to the prover, carried on the
    job so the two cannot drift apart.

    Attribution is reported only where it means something:

      * the run proved -- a failed run prints no certificate;
      * the axioms channel -- hints are not named in a proof at all, and a hint
        that never fired is a different measurement (`proofs.hint_firings`);
      * the artifact is on disk -- a reused row can name a file that is gone.

    Everywhere else both keys are None, which reads as "not attributed" and must
    not be confused with "used nothing". Nothing here is evidence that dropping
    an unused parent is FASTER: it says only that this certificate did not cite
    it. Removing an axiom changes the rewrite system twee searches, and
    `agent/ledger.py` exists because that is a different search with its own
    outcome. Treat an unused parent as a hypothesis to test, not a liability.
    """
    if not support:
        return {"support": list(support), "used_support": None,
                "unused_support": None}
    out = {"support": list(support), "used_support": None,
           "unused_support": None}
    if not proved or channel != "axioms" or not out_path:
        return out
    try:
        text = Path(out_path).read_text(errors="ignore")
    except OSError:
        return out
    used = proofs.used_supports(text, count=len(support))
    if used is None:
        return out
    out["used_support"] = [n for i, n in enumerate(support, start=1)
                           if i in used]
    out["unused_support"] = [n for i, n in enumerate(support, start=1)
                             if i not in used]
    return out


def _prior_artifact(prior):
    """The recorded artifact for a reused row, only if it is still there.

    A reused verdict is sound -- the ledger key is over the exact bytes handed to
    twee. The recorded *path* is not: rows written before artifacts were
    identity-addressed can name a file that a later run overwrote, which is the
    confusion that made two different searches look identical. A missing or
    unverifiable artifact is reported as absent rather than handed on as though
    it were this run's own.
    """
    out = prior.get("output")
    if out and Path(out).exists():
        return {"output": out}
    return {"output": None, "artifact_missing": True}


def _direction_worker(j, direction, cancel, q):
    """One direction, in its own process, reporting through `q`."""
    try:
        q.put(_job({**j, "direction": direction, "cancel": cancel}))
    except Exception as e:                                        # noqa: BLE001
        q.put({"node": j["node"], "direction": direction, "channel": j["channel"],
               "n_support": len(j["eqs"]), "result": f"Error: {e}",
               "proved": False, "cpu": 0.0, "wall": 0.0,
               "support": list(j.get("support") or ()),
               "used_support": None, "unused_support": None})


def _node_job(j):
    """Race a node's goal directions, and stop the loser the moment one proves.

    A node needs only one direction to succeed, and the other then burns its
    whole budget for nothing -- and it is the *losing* arm the layer waits on.
    `right_moufang_a` reported 0.5s while its layer waited 300.3s, and across one
    RNG029-5 run the reported times summed to 346.5s against 1799.7s waited.

    Each direction gets its own process, not a thread: `runner.run` measures CPU
    as a RUSAGE_CHILDREN delta, which is process-wide, so two twee children in
    one process would each be charged the other's time. Cancellation is
    cooperative through a shared event, which needs no signals and cannot orphan
    a grandchild.
    """
    directions = j["directions"]
    if len(directions) == 1:
        return [_job({**j, "direction": directions[0]})]

    if not j.get("race", True):
        # Inline: same verdict, sequentially, so a substituted runner stays
        # observable in-process. `_map_nodes` picks this at workers<=1; it costs
        # the loser's budget when the first guess is wrong, which is why it is
        # not the production path.
        rows = []
        for d in directions:
            rows.append(_job({**j, "direction": d}))
            if rows[-1].get("proved"):
                break
        return rows

    ctx = mp.get_context("fork")
    cancel, q = ctx.Event(), ctx.Queue()
    procs = [ctx.Process(target=_direction_worker, args=(j, d, cancel, q),
                         daemon=True) for d in directions]
    for p in procs:
        p.start()
    rows = []
    try:
        for _ in directions:
            row = q.get()
            rows.append(row)
            if row.get("proved"):
                cancel.set()          # the others stop; their rows still arrive
    finally:
        for p in procs:
            p.join(timeout=30)
            if p.is_alive():
                p.terminate()
    # A cancelled run answered nothing, so it is not a result -- only the rows
    # that reached a verdict are reported.
    return [r for r in rows if r.get("result") != "Cancelled"] or rows


def _support_worker(j, cancel, q):
    """One (assumption set, direction) attempt, reporting through `q`."""
    try:
        row = _job({**j, "cancel": cancel})
    except Exception as e:                                        # noqa: BLE001
        row = {"node": j["node"], "direction": j["direction"],
               "channel": j["channel"], "n_support": len(j["eqs"]),
               "result": f"Error: {e}", "proved": False, "cpu": 0.0,
               "wall": 0.0, "support": list(j.get("support") or ()),
               "used_support": None, "unused_support": None}
    q.put({**row, "label": j["label"]})


def steer_split(eqs, steer):
    """What an arm supplying `eqs` as axioms should also carry as hints.

    Everything in `steer` the arm did NOT promote, compared as equations rather
    than by identity so the same lemma reached from the pool and from the arm's
    own set is recognised as one. A lemma must not appear in both channels: as an
    axiom it already rewrites, and hinting it again only re-scores a subterm the
    rule has usually consumed by then.
    """
    picked = {(l, r) for l, r in eqs}
    return [e for e in steer if tuple(e) not in picked]


def race_support(problem, lhs, rhs, candidates, *, outdir: Path, budget=300,
                 directions=DIRECTIONS, workers=8, binary=None, ledger=None,
                 reuse=True, channel="axioms", node="probe",
                 steer=()):
    """Attempt one statement under many assumption sets, stopping at the first proof.

    Which lemmas a node is given decides whether it proves at all, the space is
    combinatorial, and the signal is close to binary. `right_moufang` proves in
    197.8s from exactly three lemmas and times out if any one is removed OR if a
    fourth true, universal, 0.0s lemma is added; `middle_moufang`, one hop away,
    tolerates additions at 2x and is 27s FASTER without one of its recorded
    parents. Nothing about a lemma predicts which it will be, and the certificate
    cannot steer the choice: the parent worth dropping there is one the proof
    CITES, so `unused_support` cannot see it (FINDINGS). Measurement is the only
    way through, and several sets at once is the only affordable measurement.

    **Everything stops at the first proof.** The remaining arms are answering a
    question that no longer has value -- the same argument the goal-direction
    race already makes, where a losing arm burned its whole budget for nothing.
    Cancellation is cooperative through one `mp.Event` shared by every arm, so a
    set still queued when the winner lands never starts and one in flight is
    killed. Forked processes rather than a pool, for the two reasons `_node_job`
    gives: an Event cannot be pickled into a `ProcessPoolExecutor`, and
    `runner.run` measures CPU as a RUSAGE_CHILDREN delta, which is process-wide
    and would charge every arm the others' time.

    `candidates` is `[(label, [names], [(lhs, rhs), ...])]` -- what to call the
    set, the node names for attribution, and the equations to supply.

    -> (winning label or None, rows). A cancelled arm answered nothing, so it is
    dropped from the rows and never recorded in the ledger, as in `_node_job`.
    """
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for label, names, eqs in candidates:
        for direction in directions:
            # The label names the ARTIFACT, and an assumption set of eighteen
            # lemmas joins into 359 characters -- past NAME_MAX at 255, so
            # `_job` raised OSError, `_support_worker` turned it into an Error
            # row with cpu 0.0, and the caller reported "did not prove". A crash
            # indistinguishable from a negative is the worst failure this
            # harness can have, so long labels are hashed for the filename and
            # kept whole for the report.
            tag = label if len(label) <= 80 else \
                f"{label[:40]}~{hashlib.sha256(label.encode()).hexdigest()[:10]}"
            # Everything in `steer` that this arm did NOT promote to axioms
            # still goes in as a hint. The arm then chooses which lemmas get
            # deductive power, and the rest keeps steering for free -- no
            # critical pairs, only priority. That makes over-inclusion cheap in
            # one direction and lets an arm be wrong without being ruinous.
            rest = steer_split(eqs, steer)
            jobs.append({
                "problem": problem, "node": f"{node}.{tag}", "label": label,
                "lhs": lhs, "rhs": rhs, "eqs": list(eqs), "hint_eqs": rest,
                "support": list(names), "channel": channel,
                "direction": direction, "budget": budget,
                "outdir": str(outdir), "binary": binary,
                "reuse": reuse, "ledger": ledger})

    ctx = mp.get_context("fork")
    cancel, q = ctx.Event(), ctx.Queue()
    pending, running, rows = list(jobs), [], []
    started = received = 0
    winner = None
    try:
        while True:
            # Reap FIRST. Dead workers left in `running` keep the pool looking
            # full, and then nothing new starts while nothing is outstanding --
            # which is a spin, not a wait.
            running = [p for p in running if p.is_alive()]
            while (pending and len(running) < max(1, workers)
                   and not cancel.is_set()):
                j = pending.pop(0)
                p = ctx.Process(target=_support_worker, args=(j, cancel, q),
                                daemon=True)
                p.start()
                running.append(p)
                started += 1
            if received >= started:
                # Nothing outstanding: the field is exhausted, or the winner has
                # already stopped it.
                if not pending or cancel.is_set():
                    break
                time.sleep(0.05)      # a worker has reported and not yet exited
                continue
            row = q.get()
            received += 1
            rows.append(row)
            if row.get("proved") and winner is None:
                winner = row["label"]
                cancel.set()
                print(f"  WON by {winner} in {row['cpu']:.1f}s "
                      f"({row['direction']}); stopping "
                      f"{len(pending) + len(running) - 1} other attempt(s)",
                      flush=True)
    finally:
        for p in running:
            p.join(timeout=30)
            if p.is_alive():
                p.terminate()
    return winner, [r for r in rows if r.get("result") != "Cancelled"]


def _route_to(sketch: Sketch, target):
    """`target` and every ancestor of it, or empty when there is no target."""
    if not target or target not in sketch.nodes:
        return frozenset()
    seen, stack = {target}, list(sketch.nodes[target][2])
    while stack:
        n = stack.pop()
        if n not in seen:
            seen.add(n)
            stack += sketch.nodes[n][2]
    return frozenset(seen)


def _priority(name, sketch, proved, route):
    """Sort key for the next node to start. Lower goes first.

    A **priority, not a gate**. Every claim is attempted; this only decides the
    order when there are more of them than there are workers.

    Ready first -- every parent already proved -- because that node's result is
    grounded the moment it lands, where a speculative one has to wait for its
    assumptions and may never be worth anything. Then the target's own route,
    so a run with more claims than slots spends the box on the conjecture rather
    than on whatever sorts first alphabetically. Name last, to stay
    deterministic: two runs of the same sketch must schedule the same way or
    nothing about them is comparable.
    """
    ready = all(p in proved for p in sketch.nodes[name][2])
    return (0 if ready else 1, 0 if name in route else 1, name)


def _run_nodes(jobs, workers, sketch, *, proved=(), route=frozenset(), on_row=None):
    """Run per-node jobs, keeping `workers` slots full until nothing is left.

    The scheduler. There is no barrier and no readiness gate: every job is run,
    and `_priority` only picks which one starts next. A slot that frees is
    refilled immediately, and `proved` grows as rows land, so a node whose
    parents have just proved jumps ahead of one still resting on assumptions.

    Inline at `workers <= 1` is not an optimisation. A ProcessPoolExecutor puts
    the work behind a pickling boundary where no test can substitute
    `runner.run`, so a changed `_job` signature surfaces only as an unpickling
    error in a live run -- which is exactly how a stale 10-tuple job site
    reached a real invocation. The sequential path runs the same priority order
    so the two agree on more than the final verdict.
    """
    pending = {j["node"]: j for j in jobs}
    proved, out = set(proved or ()), []

    def settle(node, rows):
        out.extend(rows)
        if any(r.get("proved") for r in rows):
            proved.add(node)
        if on_row:
            on_row(node, rows)

    def nxt():
        return min(pending, key=lambda n: _priority(n, sketch, proved, route))

    if workers <= 1:
        while pending:
            n = nxt()
            settle(n, _node_job({**pending.pop(n), "race": False}))
        return out

    in_flight = {}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        while pending or in_flight:
            while pending and len(in_flight) < workers:
                n = nxt()
                in_flight[pool.submit(_node_job, pending.pop(n))] = n
            done, _ = wait(in_flight, return_when=FIRST_COMPLETED)
            for fut in done:
                settle(in_flight.pop(fut), fut.result())
    return out


def verify(problem, sketch: Sketch, *, outdir: Path, budget=600, budgets=None,
           node_flags=None, scope="parents", channel=None, directions=DIRECTIONS,
           workers=8,
           binary: str | None = None, known=(), prior_results=(),
           reuse=True, ledger=None, prefer=None, target=None):
    """Prove every node, each in the scope its edges imply, keeping the pool full.

    **Every claim is attempted.** A node whose parents have not proved is run
    anyway, and its result recorded as *conditional*: a proof of the implication,
    not yet a theorem of the problem. `grounding` sorts the two apart at the end
    and only grounded nodes count.

    That replaces a rule that skipped such a node entirely, and the rule was
    buying less than it looked. It could not make a result sounder -- `scope`
    supplies a node's declared parents whether or not they proved, so the input
    bytes, the ledger key and the verdict are identical either way; all it
    decided was *when* the question got asked. What it cost was severe: one
    failed ancestor removed a whole subtree from the run, and when that subtree
    contained the goal there was no attempt, no artifact, and no goal contact,
    so the loop's only veto went quiet. One run spent nine iterations that way.
    Asking early is free whenever the parent eventually proves -- the ledger
    answers the second time -- and when it never proves, the failed search is
    still the listing candidates are mined from.

    Scheduling is a priority, not a barrier (`_priority`, `_run_nodes`): ready
    nodes first, then the target's route, and a slot that frees is refilled at
    once. Pass `target` to bias toward the conjecture when there are more claims
    than workers.

    **A failed node is not re-attempted standalone.** It was, for a real reason:
    the prover's soundness catches a wrong *statement* and nothing catches a
    wrong *edge*, and `teichmuller` -- drafted with five parents, three of them
    trilinearity and off its derivation path -- proves in 3.3s from the bare
    axioms, takes 358.6s given two of them and times out at 900s given all five,
    blocking six downstream nodes. But the retry answered that at the wrong
    price and in the wrong shape. Across the 84 archived `dag.json` files it ran
    81 fresh searches for 8620.8s of prover time, of which 8532.8s (99.0%)
    proved nothing; and dropping *every* parent cannot say WHICH edge is wrong,
    which is the actual question. It also contradicts this project's first rule,
    that budget is a diagnostic and not a resource -- it re-spent the whole
    budget that had just failed. `scripts/retry_cost.py` is that measurement,
    kept because the `scope_retry` rows it reads exist only in the archive.

    What replaces it is evidence, not another search. A proved run's certificate
    names the support it used, so `_support_usage` reports the parents it did
    not; the agent tests a suspected edge itself with `set_parents` and a
    declared probe, and `agent/loop.py` puts an unused parent on probation and
    measures the drop. Explicit `scope="none"` and naturally parentless nodes
    are untouched: those are the experiment control arm and the donor-ladder
    shape, not a fallback.

    `known` names nodes already proved by an earlier run, so a resumed run
    re-verifies nothing; pass that run's `results` as `prior_results` so the
    merged record stays complete.

    `reuse` consults `agent/ledger.py` before every invocation, so an identical
    question already asked is answered from the record rather than re-run --
    `rng033_goal` was verified standalone at 300s, failed, and then re-run
    identically at 900s. Identity is over the input bytes and the exact
    invocation, never over meaning, because twee searches a reordered axiom list
    differently. Pass `reuse=False` to force everything. `budgets` overrides
    `budget` per node, and `node_flags` appends extra twee flags per node --
    scoping a search option to the one node that needs it, so the rest of the
    sketch keeps its recorded proofs. `channel` forces a channel; leaving it None
    applies `channel_for`, which is the point of the DAG.
    """
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    budgets = budgets or {}
    node_flags = node_flags or {}
    # Carry the earlier run's rows forward. Without this a resumed run writes a
    # dag.json describing only the nodes it re-ran, and anything reading it --
    # the blueprint, for one -- reports every other node as never attempted.
    results = list(prior_results)
    proved = {n: {"cpu": None, "direction": None, "n_support": 0,
                  "channel": "cached"} for n in known if n in sketch.nodes}
    if proved:
        print(f"resuming: {len(proved)} node(s) already proved", flush=True)
    # The problem's own axioms are true by assumption and twee already has them.
    # They enter the DAG so the problem has one canonical shape and an agent can
    # cite an axiom instead of restating it -- not so we can prove tautologies.
    for n in sketch.given:
        proved.setdefault(n, {"cpu": 0.0, "direction": None, "n_support": 0,
                              "channel": "given"})
    if sketch.given:
        print(f"axioms: {len(sketch.given)} node(s), assumed not proved",
              flush=True)
    bad = grounding_errors(sketch, problem)
    if bad:
        raise ValueError("this sketch assumes more than the problem does:\n  "
                         + "\n  ".join(bad))

    jobs = []
    for n in sketch.topological():
        if n in proved or n in sketch.given:
            continue
        names = sketch.scope(n, scope)
        ch = channel_for(names, sketch, n, channel)
        lhs, rhs, _ = sketch.nodes[n]
        # Try the direction that worked for this node before, when anything
        # knows. Direction is strongly node-dependent -- trilinearity proves
        # only under --flatten-goal and the alternating laws only under the
        # other -- so no global order is right, and a wrong first guess costs
        # a whole budget.
        order = list(directions)
        pref = (prefer or {}).get(n)
        if pref in order:
            order.remove(pref)
            order.insert(0, pref)
        # `equations` drops given axioms, so this is the list the prover
        # actually receives and the only one a `parent_N` can be resolved
        # against. Built once and carried on the job, because computing it
        # twice is how the two would come to disagree.
        supplied = [m for m in names if m not in sketch.given]
        jobs.append({"problem": problem, "node": n, "lhs": lhs, "rhs": rhs,
                     "eqs": sketch.equations(names), "support": supplied,
                     "channel": ch,
                     "directions": order, "budget": budgets.get(n, budget),
                     "outdir": str(outdir), "binary": binary,
                     "extra_flags": tuple(node_flags.get(n, ())),
                     "reuse": reuse, "ledger": ledger})

    print(f"verifying {len(jobs)} claim(s) on {workers} worker(s)", flush=True)

    def report(n, rows):
        best = min((r for r in rows if r["proved"]),
                   key=lambda r: r["cpu"], default=None)
        if best is None:
            print(f"  {n:<18} unproven in both directions", flush=True)
            return
        proved[n] = best
        # Name the parents the certificate never cited. They are the candidates
        # for a `set_parents` experiment, and saying so where the proof is
        # reported is what makes them visible at all; the old line here reported
        # only that a standalone retry had won, which was one bit and was never
        # persisted.
        dead = best.get("unused_support")
        flag = f"  ({len(dead)} unused: {dead})" if dead else ""
        print(f"  {n:<18} PROVED {best['direction']:<18} "
              f"{best['cpu']:>7.1f}s  {best['n_support']} as "
              f"{best['channel']}{flag}", flush=True)

    results += _run_nodes(jobs, workers, sketch, proved=set(proved),
                          route=_route_to(sketch, target), on_row=report)

    # Grounded only after everything has landed. A node can be conditional when
    # its own run finishes and grounded ten minutes later when the assumption
    # proves, and nothing has to re-run for that: both runs were handed the same
    # equations, so the verdict was always about the same question.
    ground, conditional = grounding(sketch, results, proved=set(proved))
    claims = set(sketch.claims())
    if conditional:
        print(f"conditional: {len(conditional)} node(s) proved on unproved "
              f"assumptions -- implications, not yet theorems", flush=True)
        for n in sorted(conditional):
            print(f"  {n:<18} assumes {list(conditional[n])}", flush=True)

    out = {"problem": problem, "scope": scope, "channel": channel or "auto",
           # Claims only: an axiom is not an achievement, and counting them
           # would inflate every ratio a run reports.
           "n_nodes": len(sketch.claims()),
           # Grounded only, deliberately. Every ratio in `runs/` and
           # `docs/FINDINGS.md` was computed when a node could not prove without
           # its parents, and letting conditional results into this number would
           # flatter a run whose assumptions never discharge.
           "n_proved": len(claims & ground),
           "n_given": len(sketch.given),
           "n_conditional": len(claims & set(conditional)),
           "proved": {k: v["cpu"] for k, v in proved.items() if k in ground},
           "grounded": {k: v["cpu"] for k, v in proved.items() if k in ground},
           "all_proved": {k: v["cpu"] for k, v in proved.items()},
           "conditional": {n: list(a) for n, a in sorted(conditional.items())},
           "missing": [n for n in sketch.claims() if n not in ground],
           "results": results}
    (outdir / "dag.json").write_text(json.dumps(out, indent=2) + "\n")
    return out


def mined_parents(sketch, node, proof_text, *, include_self=False):
    """Which sketch nodes this node's own proof actually derived or used.

    The honest source of edges. Drafting them from theory adjacency is what put
    three trilinearity lemmas on `teichmuller`, which needs none of them and
    which they made unprovable at 900s. A proof, by contrast, states its
    dependencies: every `Lemma N: lhs = rhs` twee had to derive is a step the
    node genuinely needed, and any that matches an existing node is an edge we
    should have drawn.

    Matching is alpha-normalised and orientation-insensitive, since twee states
    a lemma in whichever direction its ordering prefers -- `neg_mult_r` comes
    back as `additive_inverse(multiply(X, Y)) = multiply(X, additive_inverse(Y))`.

    Returns (edges_to_existing_nodes, unmatched_lemmas). The second list is the
    more interesting one: those are steps the proof needed that the sketch does
    not name, i.e. candidate new nodes.
    """
    from overtone import proofs
    from overtone.terms import eq_key as key

    known = {}
    for name, (lhs, rhs, _) in sketch.nodes.items():
        if name != node or include_self:
            known[key(lhs, rhs)] = name

    edges, unmatched = [], []
    for n, lhs, rhs in proofs.lemmas(proofs.proof_section(proof_text)):
        hit = known.get(key(lhs, rhs))
        if hit and hit not in edges:
            edges.append(hit)
        elif not hit:
            unmatched.append((n, lhs, rhs))
    return edges, unmatched


def attempt(problem, equations, *, outdir: Path, budget=300, binary=None,
            directions=DIRECTIONS, workers=2, label="final", reuse=True,
            ledger=None, channel="axioms", support=()):
    """Run the problem's own file with `equations` supplied as `channel`.

    The final phase `verify` lacks. It was written twice -- in
    `scripts/transfer_dag._final` and in `ladder.run_ladder` -- and both did the
    same thing: take what has been proved and attack the real conjecture with it.

    The problem file is not modified. `runner.write_problem` copies it and adds
    the equations, so what is proved is the problem as TPTP states it, not a
    restatement of it.

    `channel` was hardcoded to "axioms" here while `verify` chose it per node
    through `channel_for`, so the run this whole method exists to make was the
    one run exempt from the method's own central finding. Two agent runs then
    spent 6,003.7s of 10,423.9s and 1,201.4s of 1,441.9s attempting the target
    with every verified node as an axiom -- the loose-bag configuration this
    module's docstring records as a timeout on MVA005-1 and as unboundedly bad
    on `teichmuller`. The caller now picks both the support set and the channel,
    and `support` carries the names so the row says what was supplied.
    """
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    jobs = [{"problem": problem, "direction": direc, "eqs": tuple(equations),
             "budget": budget, "outdir": str(outdir), "binary": binary,
             "label": label, "reuse": reuse, "ledger": ledger,
             "channel": channel, "support": tuple(support)}
            for direc in directions]
    with ProcessPoolExecutor(max_workers=min(len(jobs), workers)) as pool:
        return list(pool.map(_attempt_job, jobs))


def _attempt_job(j):
    """The final attempt, on the problem's own file. Dict-shaped, like `_job`."""
    problem, direction, eqs = j["problem"], j["direction"], j["eqs"]
    budget, outdir, binary = j["budget"], j["outdir"], j.get("binary")
    label, reuse, ledger = j["label"], j.get("reuse", True), j.get("ledger")
    channel, support = j.get("channel", "axioms"), j.get("support", ())
    stem = f"{label}.{direction[2:]}"
    flags = [*BASE_FLAGS, direction]
    # The same two channels `_job` offers, and for the same measured reason.
    kw = {}
    if channel == "axioms":
        kw["extra_axioms"] = list(eqs)
        kw["axiom_prefix"] = "lemma"
    else:
        terms = []
        for l, r in eqs:
            terms += [t for t in (l, r) if "(" in t and t not in terms]
        kw["hints"] = terms
        if terms:
            flags = [*BASE_FLAGS, *hintlib.HINT_FLAGS, direction]
    # Same identity-addressed naming as `_job`: an attempt with 18 lemmas and one
    # with 22 are different questions and must not share a filename.
    tmp = Path(outdir) / f".{stem}.building.p"
    runner.write_problem(problem, tmp, **kw)
    key = ledgerlib.key_for(tmp, flags, binary)
    tag = f"{stem}.{ledgerlib.short(key)}"
    path = Path(outdir) / f"{tag}.p"
    tmp.replace(path)
    if reuse:
        prior = ledgerlib.lookup(key, budget, ledger=ledger)
        if prior is not None:
            return {"node": label, "direction": direction, "channel": channel,
                    "n_support": len(eqs), "support": list(support),
                    "result": prior.get("result"),
                    "proved": bool(prior.get("proved")),
                    "cpu": prior.get("cpu") or 0.0,
                    "wall": prior.get("wall") or 0.0, "reused": True,
                    "key": key, "input": str(path),
                    **_prior_artifact(prior)}
    r = runner.run(path, flags, budget, problem=problem, binary=binary)
    out_path = Path(outdir) / f"{tag}.{'out' if r.proved else 'fail.out'}"
    out_path.write_text(r.output)
    row = {"node": label, "direction": direction, "channel": channel,
           "n_support": len(eqs), "support": list(support),
           "result": r.status, "proved": r.proved,
           "cpu": r.cpu, "wall": r.wall, "key": key,
           "input": str(path), "output": str(out_path)}
    # A cancelled run answered nothing. Recording it would let reuse skip a
    # question that was never resolved.
    if r.status != "Cancelled":
        ledgerlib.record(key, row, budget, ledger=ledger)
    return row


def cost(*row_lists):
    """Total prover time across any number of result lists, failures included.

    The number a per-problem pipeline reports. Everything spent counts: failed
    nodes, standalone retries, both goal directions, and the final attempts --
    not just the runs that happened to succeed.

    Two totals, because inside a loop they differ enormously. `cpu` is what this
    sketch costs from cold -- the honest per-problem figure, and the one to
    quote. `cpu_new` excludes ledger-reused rows: what the machine actually
    spent on this run. One agent iteration reported 601.7s of node time that was
    100% reuse, and another run's running total rose by 600.7s across an
    iteration whose two final attempts were both served from the ledger.
    Reporting only `cpu` tells an agent it has burned a budget it never touched;
    reporting only `cpu_new` understates what the decomposition costs anyone who
    reruns it from scratch.
    """
    rows = [r for rl in row_lists for r in (rl or ())]
    fresh = [r for r in rows if not r.get("reused")]
    return {"cpu": round(sum(r.get("cpu") or 0.0 for r in rows), 1),
            "cpu_new": round(sum(r.get("cpu") or 0.0 for r in fresh), 1),
            "wall": round(sum(r.get("wall") or 0.0 for r in rows), 1),
            "n_runs": len(rows), "n_new": len(fresh),
            "n_reused": len(rows) - len(fresh),
            "n_failed": sum(1 for r in rows if not r.get("proved"))}


def sibling_diff(sketch: Sketch, results, node, *, limit=3):
    """Nodes of similar shape that proved, and how their parents differ.

    Every wrong-edge fault found by hand this session was found this way, by
    comparing a failing node against one of the same shape that worked.
    `left_moufang_a` had been given `right_moufang` -- its mirror's parent --
    where it needed `left_moufang`, and that one substitution was a 300s timeout
    against 1.0s.

    Similarity is symbol-profile overlap on the statement, which is crude and
    sufficient: mirrored statements share a symbol profile exactly.
    """
    from overtone.terms import safe_term, symbols

    def profile(name):
        lhs, rhs, _ = sketch.nodes[name]
        out = set()
        for side in (lhs, rhs):
            t = safe_term(side)
            if t is not None:
                symbols(t, out)
        return out

    proved = {r["node"] for r in results if r.get("proved")}
    mine, parents = profile(node), set(sketch.nodes[node][2])
    if not mine:
        return []
    scored = []
    for other in sketch.nodes:
        if other == node or other not in proved:
            continue
        theirs = profile(other)
        j = len(mine & theirs) / len(mine | theirs) if theirs else 0.0
        if j <= 0.5:
            continue
        op = set(sketch.nodes[other][2])
        scored.append((round(j, 3), other, sorted(op - parents), sorted(parents - op)))
    scored.sort(key=lambda x: -x[0])
    out = []
    for j, n, add, rem in scored[:limit]:
        row = {"node": n, "similarity": j, "they_have_you_lack": add,
               "you_have_they_lack": rem}
        # An empty diff against a same-shape sibling is the loudest signal there
        # is, and the easiest to read past. It means the parents were copied from
        # that sibling rather than mirrored -- which is exactly what happened to
        # left_moufang_a, handed right_moufang where it needed left_moufang.
        if j >= 0.95 and not add and not rem:
            row["note"] = (f"identical parents to {n}, which has the same shape "
                           f"and proved. Parents copied from a mirror usually "
                           f"need mirroring too.")
        out.append(row)
    return out


def diff(before: Sketch, after: Sketch):
    """What changed between two revisions of a sketch.

    Four kinds of edit, which are exactly the ones that mattered when this was
    done by hand: a node appeared, a node went, a node's *statement* changed, or
    its parents did. The parent edits are the ones worth the most and the
    easiest to miss -- correcting one parent took `left_moufang_a` from a 300s
    timeout to 1.0s, and adding one node took `assoc_add_1` from 37.9s to 2.1s.

    Statements compare by `terms.eq_key`, so an alpha-rename is not an edit but
    a genuine restatement is. That distinction is the whole point: our
    `left_moufang` was silently restated away from RNG028-7's conjecture.
    """
    from overtone.terms import eq_key

    a, b = before.nodes, after.nodes
    added = [n for n in b if n not in a]
    removed = [n for n in a if n not in b]
    restated, reparented = [], []
    for n in b:
        if n not in a:
            continue
        if eq_key(a[n][0], a[n][1]) != eq_key(b[n][0], b[n][1]):
            restated.append({"node": n, "before": f"{a[n][0]} = {a[n][1]}",
                             "after": f"{b[n][0]} = {b[n][1]}"})
        old, new = set(a[n][2]), set(b[n][2])
        if old != new:
            reparented.append({"node": n, "gained": sorted(new - old),
                               "lost": sorted(old - new)})
    return {"added": added, "removed": removed, "restated": restated,
            "reparented": reparented,
            "n_edits": len(added) + len(removed) + len(restated) + len(reparented)}


def sketch_from_proof(proof_text, *, max_nodes=260, prefix="L"):
    """(Sketch, depth per node) from a twee proof's own lemma structure.

    The only proof -> DAG constructor there is, and it lived in a script. A
    proof states its dependencies: `Lemma N:` lines are nodes and `by lemma N`
    citations are edges, so this is a *recorded* structure rather than a guessed
    one -- which matters, since hand-drafted edges were wrong three times out of
    four, at costs from 18x to a blocked subtree.

    Depth is the proxy for "near the goal": on RNG027-5 the donor's proof ran
    234 lemmas deep and its goal cited exactly four, and those four flipped ten
    problems while all 234 in the hint channel flipped none.
    """
    from overtone import proofs

    section = proofs.proof_section(proof_text)
    stmt, cites, cur, buf = {}, {}, None, []

    def flush():
        if cur is not None:
            cites[cur] = {int(x) for x in proofs.USED_REF_RE.findall("\n".join(buf))}

    for line in section.splitlines():
        m = proofs.LEMMA_RE.match(line.strip())
        g = line.startswith("Goal ")
        if m or g:
            flush()
            cur = int(m.group(1)) if m else "GOAL"
            if m:
                stmt[cur] = (m.group(2).strip(), m.group(3).strip())
            buf = [line]
        else:
            buf.append(line)
    flush()

    depth = {}

    def go(n, seen=()):
        if n in depth:
            return depth[n]
        if n in seen:
            return 0                       # a cycle cannot happen in a proof
        ps = [p for p in cites.get(n, ()) if p in stmt]
        depth[n] = 1 + max([go(p, seen + (n,)) for p in ps] or [-1])
        return depth[n]

    for n in stmt:
        go(n)
    keep = sorted(stmt, key=lambda n: depth[n])[:max_nodes]
    nodes = {f"{prefix}{n}": (stmt[n][0], stmt[n][1],
                              [f"{prefix}{p}" for p in cites.get(n, ())
                               if p in keep and p != n])
             for n in keep}
    return Sketch(nodes), {f"{prefix}{n}": depth[n] for n in keep}
