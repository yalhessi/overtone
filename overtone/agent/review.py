"""Review proposed edits before spending the prover on them.

The loop was propose -> verify -> diagnose. An agent run then spent 4,300s of
7,205s CPU on four nodes that were not theorems, and repeated the same class of
error across three iterations because a false statement and a hard one are
reported identically: "unproven". Four other nodes in the same run were verbatim
copies of the problem's own axioms, which prove in 0.0s and are reported as
successes, so nothing flagged the waste.

Both are review failures, not prover failures. So: propose -> REVIEW -> verify.

Three rules keep this from becoming a second, worse validator.

**Cheap before expensive.** The prover costs 60-300s per node; these checks cost
microseconds. Anything decidable statically is decided here.

**Refutation only, never certification.** A reviewer may return `reject` when it
can demonstrate a problem, or say nothing. It may not bless a node. In
particular a theory-specific reviewer that decides truth in some *weaker* theory
must not treat "not provable there" as "false" -- most real lemmas need the
problem's own axioms, and rejecting those would remove exactly the nodes worth
having.

**Nothing is dropped silently.** Every finding is returned, recorded in the
trajectory, and shown to the agent next turn. A filter the agent cannot see is a
filter it will keep tripping over.

Reviewers are registered rather than hardcoded, so a theory can contribute its
own without this module knowing anything about that theory.
"""
from dataclasses import dataclass, field

from overtone.terms import eq_key, parse_error, symbols, symbols_in

# Verdicts, in descending severity. Only `reject` withholds an edit.
REJECT, WARN, NOTE = "reject", "warn", "note"


@dataclass(frozen=True)
class Finding:
    reviewer: str
    node: str
    verdict: str
    reason: str
    data: dict = field(default_factory=dict)

    def to_json(self):
        return {"reviewer": self.reviewer, "node": self.node,
                "verdict": self.verdict, "reason": self.reason, **self.data}


@dataclass(frozen=True)
class Context:
    """What a reviewer may look at. Deliberately small."""
    problem: str
    axioms: frozenset = frozenset()      # eq_key of each axiom
    goal: str = ""                       # name of the goal node
    sketch_keys: frozenset = frozenset()  # eq_key of each existing node
    node_names: frozenset = frozenset()  # names an edit may legally cite
    axiom_names: dict = field(default_factory=dict)   # eq_key -> axiom node name
    symbols: frozenset = frozenset()     # function symbols the problem has
    arities: dict = field(default_factory=dict)       # symbol -> arity it has there
    node_names_by_key: dict = field(default_factory=dict)  # eq_key -> node name
    parents_of: dict = field(default_factory=dict)    # node name -> its parents


def _eq(action):
    lhs, rhs = action.get("lhs"), action.get("rhs")
    return eq_key(lhs, rhs) if lhs and rhs else None


# ------------------------------------------------------------------ reviewers
# Each takes (action, ctx) and returns findings. Theory-agnostic ones first.

def well_formed(action, ctx):
    """Each side must be one complete term, using the problem's own arities.

    The cheapest check here and the one that was missing. An agent proposed a
    node whose sides were `associator(X,Y,Z) = additive_identity` and
    `multiply(multiply(X,Y),Z) = multiply(X,multiply(Y,Z))` -- an implication
    dressed as an equation. Nothing caught it: `=` is not a token of the term
    grammar, so `safe_term` returned None, `alpha_key` fell back to a stripped
    string, and every `eq_key`-based reviewer compared that string against
    others and found no match. Twee rejected the input in 0.003s and the loop
    recorded `failed`, which is what a hard lemma also reports -- so the agent
    subdivided it, then removed it, and the run ended on the cycle detector
    having done no mathematics.

    Arity is the same class of error one step subtler: `associator(X,Y)` parses
    perfectly and is still not a term of this signature. `within_the_signature`
    only compares symbol names, so it passes.
    """
    out = []
    for side in ("lhs", "rhs"):
        text = action.get(side)
        if text is None:
            continue
        t, why = parse_error(text)
        if t is None:
            out.append(Finding("well_formed", action.get("name", "?"), REJECT,
                               f"{side} is not a single well-formed term: {why}",
                               {"side": side, "text": text}))
            continue
        if not ctx.arities:
            continue                      # no signature known; no opinion
        for name, arity in sorted(symbols(t)):
            want = ctx.arities.get(name)
            if want is not None and want != arity:
                out.append(Finding(
                    "well_formed", action.get("name", "?"), REJECT,
                    f"{side} applies `{name}` to {arity} argument(s); "
                    f"{ctx.problem} uses it with {want}",
                    {"side": side, "symbol": name, "arity": arity,
                     "expected": want}))
    return out


def restates_an_axiom(action, ctx):
    """A node equal to an axiom is already supplied to every other node.

    It proves in 0.0s and reads as a success, so nothing else in the loop
    notices. One agent draft spent four of its eleven nodes this way.
    """
    k = _eq(action)
    if k and k in ctx.axioms:
        cite = ctx.axiom_names.get(k)
        where = f" -- cite the existing node `{cite}`" if cite else ""
        return [Finding("restates_an_axiom", action.get("name", "?"), REJECT,
                        "this is one of the problem's own axioms, already "
                        f"supplied to every node{where}", {"axiom": cite})]
    return []


def duplicates_a_node(action, ctx):
    """The same equation twice is two names for one lemma, and doubles its cost
    as a parent everywhere it is used.

    It must name WHICH node, because a rejection alone silently breaks edges:
    a model proposed an existing lemma under a new name, review dropped it, and
    then every node citing that new name lost the parent -- injecting the wrong
    edges FINDINGS calls more costly than missing ones, while the lemma sat in
    the sketch the whole time. `review` reads `existing` to rewrite those
    references instead.
    """
    k = _eq(action)
    if k and k in ctx.sketch_keys:
        cite = ctx.node_names_by_key.get(k)
        where = f" -- it is `{cite}`; cite that name" if cite else ""
        return [Finding("duplicates_a_node", action.get("name", "?"), REJECT,
                        f"an existing node already states this equation{where}",
                        {"existing": cite})]
    return []


def restates_the_goal(action, ctx):
    """A node equal to the conjecture decomposes nothing.

    Variable identifications of the goal are the same failure one step removed:
    an instance of an open conjecture is still open. This catches only the exact
    case, which is the one that is decidable.
    """
    k = _eq(action)
    if k and ctx.goal and k == ctx.sketch_goal_key:
        return [Finding("restates_the_goal", action.get("name", "?"), REJECT,
                        "this restates the conjecture; a sketch cannot "
                        "decompose a goal into itself")]
    return []


def size(action, ctx):
    """Report how big a node is. A measurement, not a verdict.

    Node size predicts cost more sharply than placement does: in this project
    two ~6-term identities proved in 8.6s while a ~12-term one, provably true in
    every ring, did not prove at all in 120s. The threshold is theory-specific,
    so this reports the number and lets policy or the agent judge.
    """
    lhs, rhs = action.get("lhs") or "", action.get("rhs") or ""
    n = (lhs + rhs).count("(")
    if n:
        return [Finding("size", action.get("name", "?"), NOTE,
                        f"{n} function applications", {"symbols": n})]
    return []


def within_the_signature(action, ctx):
    """A node may only speak the problem's own language.

    A symbol the problem does not have is a definitional extension: nothing in
    the axioms constrains it, so whatever the node says is not about this
    theory. `dag.verify` refuses such a sketch outright, which would abort a
    whole run; catching it here withholds the one node and tells the agent why,
    so the run continues.
    """
    if not ctx.symbols:
        return []                        # no signature known; no opinion
    lhs, rhs = action.get("lhs"), action.get("rhs")
    new = sorted(symbols_in(f"{lhs} {rhs}") - set(ctx.symbols))
    if new:
        return [Finding("within_the_signature", action.get("name", "?"), REJECT,
                        f"uses {new}, which {ctx.problem} does not have; a node "
                        f"outside the problem's signature is a new definition, "
                        f"not a consequence of its axioms", {"unknown": new})]
    return []


# `well_formed` runs first: every other reviewer compares `eq_key`s, and an
# unparseable side makes that comparison meaningless rather than false.
REVIEWERS = [well_formed, restates_an_axiom, duplicates_a_node,
             restates_the_goal, within_the_signature, size]


def register(fn):
    """Add a reviewer. Theory-specific checks attach here, not in the loop."""
    if fn not in REVIEWERS:
        REVIEWERS.append(fn)
    return fn


def _load_theory_reviewers():
    """Register the theory-specific reviewers that ship with this project.

    Deliberately here rather than left to each caller. The original design said
    a theory should attach its own reviewer so this module need not know about
    it -- and the result was that nothing ever called `register`, so the
    free-ring check was written, tested, and never once ran in a real loop. A
    reviewer that no production path loads is not a reviewer.

    This is safe because such a reviewer must have no opinion outside its own
    signature: `freering.reviewer` returns nothing when a term does not parse in
    its language, so registering it globally cannot affect another theory.
    """
    from overtone import freering
    register(freering.reviewer)


_load_theory_reviewers()


# ---------------------------------------------------------------------- entry

def repair(action, ctx, known=None, alias=None):
    """(repaired action, findings). Fix what is fixable rather than refusing.

    Only one repair so far, and it is the one that matters: a parent naming
    something that is not a node. Models reach for axiom names, and one reached
    for the *problem* name -- which raised out of `apply` and ended a run that
    had already spent 4,800 prover-seconds. Discarding the whole node over one
    bad reference throws away good work, so the reference is dropped and the
    node kept.

    Repair happens for every caller, not just the drafting one. That asymmetry
    is what let the crash through: the draft path dropped unknown parents and
    the iterate path did not.

    `known` is the set of legal names, which GROWS as a batch is applied: a
    draft is emitted in dependency order, so a node citing one proposed two
    entries earlier is correct and must not have that parent stripped.
    """
    action, findings = _split_equation(action)
    names = ctx.node_names if known is None else known
    parents = action.get("parents")
    if not parents or not names:
        return action, findings
    # Rewrite before deciding anything is unknown: a parent naming a node that
    # review rejected as a duplicate still refers to a real lemma, under the
    # name that lemma already has.
    if alias:
        renamed = [alias.get(x, x) for x in parents]
        if renamed != list(parents):
            was = [x for x in parents if x in alias]
            action = {**action, "parents": renamed}
            parents = renamed
            findings = findings + [Finding(
                "repair", action.get("name", "?"), WARN,
                f"parent(s) {was} name lemmas the sketch already has under "
                f"other names; rewired to {[alias[x] for x in was]} rather than "
                f"dropping the edge", {"rewired": was})]
    bad = [x for x in parents if x not in names]
    if not bad:
        return action, findings
    good = [x for x in parents if x not in bad]
    return ({**action, "parents": good},
            findings + [Finding("repair", action.get("name", "?"), WARN,
                     f"dropped parent(s) {bad}: not nodes of this sketch. "
                     f"Parents name other nodes -- axioms are nodes too, but "
                     f"only under their own names.", {"dropped": bad})])


# Where an action carries node statements. `add_node` and `restate` ARE the
# statement; `subdivide` and `redraft` carry lists of them. Reviewing only the
# first two made every check inert for an agent that used `subdivide`: one run
# introduced 32 nodes through 23 subdivides and zero add_nodes, so nothing was
# ever checked -- four axiom restatements and seven false lemmas walked through.
NODE_FIELD = {"add_node": None, "restate": None,
              "subdivide": "intermediates", "redraft": "nodes"}


def review(actions, ctx, reviewers=None):
    """(kept actions, findings). Only `reject` withholds an edit.

    A rejected edit is still returned as a finding, so the agent is told what
    was dropped and why. Withholding without saying so is how a loop teaches an
    agent nothing.

    A rejected node inside a carrier drops just that node, not the whole action:
    losing an entire subdivide because one of its intermediates restates an
    axiom would throw away the rest of the work.
    """
    reviewers = REVIEWERS if reviewers is None else reviewers
    kept, findings = [], []
    # Grows as the batch is walked: a draft lists nodes in dependency order, so
    # a parent may legitimately name something proposed earlier in this batch.
    known = set(ctx.node_names)
    # A name a model proposed that turned out to BE an existing node, mapped to
    # that node's real name. Rejecting a duplicate outright used to delete every
    # edge pointing at it, which injects wrong edges -- FINDINGS: more costly
    # than missing ones -- while the lemma was in the sketch the whole time.
    alias = {}
    for action in actions:
        action, fixes = repair(action, ctx, known, alias)
        findings += fixes
        op = action.get("op")
        if op not in NODE_FIELD:
            kept.append(action)
            continue

        field_name = NODE_FIELD[op]
        if field_name is None:                    # the action is the statement
            mine = [f for r in reviewers for f in r(action, ctx)]
            findings += mine
            if any(f.verdict == REJECT for f in mine):
                dup = next((f.data.get("existing") for f in mine
                            if f.reviewer == "duplicates_a_node"
                            and f.data.get("existing")), None)
                if dup and action.get("name"):
                    alias[action["name"]] = dup
                continue
            kept.append(action)
            if action.get("name"):
                known.add(action["name"])
            continue

        original = list(action.get(field_name) or [])
        # A redraft that proposes NO new lemmas is not a new approach. One run
        # redrafted with `nodes: []`, keeping the five nodes that had already
        # proved and pointing the goal at one of them -- every one an accelerant
        # (`associator(X,X,Y)=0`, `commutator(X,X)=0`, the flexible law), which
        # FINDINGS records cannot flip a problem on its own. The loop counted it
        # as a route change because deleting four nodes is a non-empty diff, so
        # it reset the stall counter and bought four more iterations on a sketch
        # strictly smaller than the one that had just failed.
        if op == "redraft" and not original:
            findings.append(Finding(
                "review", action.get("approach") or op, REJECT,
                "a redraft must propose new lemma nodes. This one proposes "
                "none, so it only deletes -- keeping what already proved is a "
                "retreat to the subset that was already not enough, not a "
                "different route. Design the new decomposition as a whole."))
            continue
        surviving = []
        for node in original:
            probe = {"op": "add_node", **node}
            probe, fixes = repair(probe, ctx, known, alias)
            findings += fixes
            mine = [f for r in reviewers for f in r(probe, ctx)]
            findings += mine
            if any(f.verdict == REJECT for f in mine):
                # A duplicate is not a lost lemma, it is a renamed one. Record
                # the mapping so later nodes citing the proposed name are
                # rewired to the node that already states it.
                dup = next((f.data.get("existing") for f in mine
                            if f.reviewer == "duplicates_a_node"
                            and f.data.get("existing")), None)
                if dup and probe.get("name"):
                    alias[probe["name"]] = dup
                continue
            surviving.append({k: v for k, v in probe.items() if k != "op"})
            if probe.get("name"):
                known.add(probe["name"])
        # A carrier whose every node was rejected is no longer an edit: a
        # subdivide that inserts nothing, or a redraft that only deletes.
        if original and not surviving:
            findings.append(Finding("review", action.get("name", op), REJECT,
                                    f"every node in this {op} was rejected, so "
                                    f"the edit was dropped rather than applied "
                                    f"as a deletion"))
            continue
        action = {**action, field_name: surviving}
        # A redraft's `goal_parents` and `keep` are node references too, and
        # they were the only ones `repair` never touched. That cost a whole run:
        # a draft proposed five nodes, `sandwich_shift` was rightly rejected for
        # restating the goal, the other four survived -- and `goal_parents` still
        # named the rejected one, so `apply` raised on an unknown parent and the
        # ENTIRE draft was discarded. The run began with a bare goal and spent
        # four of its first five iterations testing nothing.
        if op == "redraft":
            action, more = _repair_refs(action, known, set(ctx.node_names),
                                        alias)
            findings += more
            # Last, so it sees the aliased and repaired parent lists.
            action, more = _close_keep(action, set(ctx.node_names),
                                       ctx.parents_of)
            findings += more
        kept.append(action)
    return kept, findings


def _split_equation(action):
    """(action, findings). Recover a node whose `lhs` holds the whole equation.

    A persistent model habit, and the single most common way a good node is
    lost: `lhs: "associator(X,Y,Y) = additive_identity"`. It appeared seven
    times across two iterations of one run and again seven times in the next,
    every time costing the node. `well_formed` rejects it correctly -- it is not
    a term -- so the repair has to come first.

    Three recoverable shapes, and one that is not:

    * `rhs` missing. The right half is the node's other side.
    * `rhs` present and equal to the right half. The model said the same thing
      twice; the split is *confirmed* rather than guessed. This is the common
      case and the earlier version of this repair refused it, because it bailed
      whenever `rhs` was set at all.
    * `rhs` present and the right half is not a term -- a truncation like
      `"associator(...) =?"`. The `rhs` field is the authoritative one.
    * `rhs` present, the right half IS a term, and they differ. Two different
      claims about the same side, and nothing here can say which was meant, so
      it stays a rejection.

    Two `=` signs are the implication case and always stay rejected.
    """
    lhs, rhs = action.get("lhs"), action.get("rhs")
    if not lhs or lhs.count("=") != 1:
        return action, []
    left, _, right = lhs.partition("=")
    left, right = left.strip(), right.strip()
    if not left:
        return action, []

    if not rhs:
        if not right:
            return action, []
        new, why = right, "`rhs` was missing"
    elif right == rhs.strip():
        new, why = rhs.strip(), "`rhs` already repeated the right half"
    elif parse_error(right)[0] is None:
        new, why = rhs.strip(), f"the text after `=` ({right!r}) is not a term"
    else:
        return action, []                 # two different claims; cannot choose
    return ({**action, "lhs": left, "rhs": new},
            [Finding("repair", action.get("name", "?"), WARN,
                     f"`lhs` held the whole equation ({why}), so it was split "
                     f"into lhs={left!r} and rhs={new!r}. A node is two terms; "
                     f"the `=` between them is the node itself, not part of "
                     f"either side.", {"lhs": left, "rhs": new})])


def _close_keep(action, existing, parents_of=None):
    """Pull into `keep` any existing node the redraft still depends on.

    Review and `apply` disagreed about what a redraft's parents may name.
    Review checks against the CURRENT sketch, so a parent naming any existing
    node passes. `apply` then rebuilds the sketch from `keep` plus the proposed
    nodes and DELETES everything else -- so a parent naming a real node that the
    model simply did not list in `keep` becomes an unknown parent, and the whole
    redraft raises.

    That deadlocked a run completely: six consecutive iterations proposed a
    waypoint citing `assoc_prod_flexible_rewrite`, a node that existed and was
    not in `keep`; every redraft raised; the sketch never changed; the approach
    never rotated, because rotation requires an applied redraft; and the loop
    span for six iterations on `retry_after_rejection` with **zero new prover
    work** and six wasted model calls.

    Keeping a node the new decomposition cites is what the model meant -- it
    named it as a parent. Silence here would drop the edge instead.
    """
    nodes = list(action.get("nodes") or [])
    proposed = {n.get("name") for n in nodes if n.get("name")}
    keep = list(action.get("keep") or [])
    needed, seen = [], set(keep) | proposed
    refs = [p for n in nodes for p in (n.get("parents") or [])]
    refs += list(action.get("goal_parents") or [])
    # Transitively: a node pulled into `keep` brings its own parents with it, or
    # IT ends up with dangling parents and the redraft raises just the same one
    # level down. Fixpoint over the ancestor closure.
    parents_of = parents_of or {}
    queue = list(refs)
    while queue:
        name = queue.pop()
        if name in seen or name not in existing:
            continue                  # already kept, proposed here, or unknown
        seen.add(name)
        needed.append(name)
        queue += parents_of.get(name, ())
    if not needed:
        return action, []
    return ({**action, "keep": keep + needed},
            [Finding("repair", action.get("approach") or "redraft", WARN,
                     f"added {needed} to `keep`: your new nodes cite them as "
                     f"parents, and a redraft deletes every existing node not "
                     f"kept, which would have left those parents dangling and "
                     f"the whole redraft unapplied", {"kept": needed})])


def _repair_refs(action, known, existing, alias=None):
    """Drop unresolvable `goal_parents` / `keep` references from a redraft.

    Same rule as `repair`: a bad reference loses that reference, not the whole
    edit. `goal_parents` may name a surviving proposed node or an existing one;
    `keep` may only name an existing one, since it selects what to carry over.
    """
    out, findings = dict(action), []
    for field, legal, what in (("goal_parents", known, "a node"),
                               ("keep", existing, "an EXISTING node")):
        refs = action.get(field)
        if not refs:
            continue
        # Same rewrite as `repair`: a rejected duplicate is a renamed lemma, and
        # the goal must still be wired to it.
        if alias:
            refs = [alias.get(x, x) for x in refs]
            out[field] = refs
        bad = [x for x in refs if x not in legal]
        if not bad:
            continue
        kept_refs = [x for x in refs if x not in bad]
        out[field] = kept_refs
        # Dropping EVERY goal parent leaves the goal connected to nothing, so
        # the target has no support and is never attempted -- four straight
        # iterations of one run went that way while 24 lemmas sat proved and
        # unused. Withholding the whole redraft over it was tried and is WORSE:
        # a draft lost two nodes out of a good set, one of them the only named
        # goal parent, and the entire decomposition was discarded, putting the
        # run back to a bare goal. That is the more expensive failure of the two.
        # So the edit stands and the loop makes the orphaned goal loud every
        # turn instead (`_orphan_finding`), which the model can fix with one
        # `set_parents` without losing any work.
        if field == "goal_parents" and not kept_refs:
            findings.append(Finding(
                "repair", action.get("approach") or "redraft", WARN,
                f"every goal parent you named ({bad}) was rejected earlier in "
                f"this batch, so the goal is left with NO parents: nothing "
                f"will be supplied to the target and it will not be attempted. "
                f"Set its parents next turn from the nodes that did survive.",
                {"field": field, "dropped": bad, "orphaned": True}))
            continue
        findings.append(Finding(
            "repair", action.get("approach") or "redraft", WARN,
            f"dropped {field} {bad}: each must name {what} -- a node rejected "
            f"by review is not in the sketch, and naming it would make the "
            f"whole redraft fail to apply", {"field": field, "dropped": bad}))
    return out, findings


def context_for(problem, sketch, goal=None):
    """Build a Context from the problem and the sketch as it currently stands."""
    from overtone import problems

    path = problems.problem_path(problem)
    named = problems.named_axioms(path)
    axiom_names = {eq_key(l, r): n for n, (l, r) in named.items()}
    axioms = frozenset(axiom_names)
    # A given node is the axiom itself, not a duplicate of it.
    by_key = {eq_key(l, r): n for n, (l, r, _) in sketch.nodes.items()
              if n not in getattr(sketch, "given", ())}
    keys = frozenset(by_key)
    # The goal is deliberately NOT an alias target. A node restating the
    # conjecture is rejected by `restates_the_goal`, and rewiring references to
    # it would make the goal its own parent -- a cycle, from a repair.
    goal_name = goal or next((n for n in sketch.nodes if n.endswith("goal")), "")
    by_key = {k: n for k, n in by_key.items() if n != goal_name}
    goal = goal or next((n for n in sketch.nodes if n.endswith("goal")), "")
    sig = problems.problem_symbols(path)
    # A symbol used at two arities in one problem has no single right answer, so
    # record neither rather than reject against an arbitrary pick.
    counts = {}
    for n, a in sig:
        counts.setdefault(n, set()).add(a)
    ctx = Context(problem=problem, axioms=axioms, goal=goal, sketch_keys=keys,
                  node_names=frozenset(sketch.nodes), axiom_names=axiom_names,
                  symbols=frozenset(n for n, _ in sig), node_names_by_key=by_key,
                  parents_of={n: list(p) for n, (_, _, p) in sketch.nodes.items()},
                  arities={n: next(iter(a)) for n, a in counts.items()
                           if len(a) == 1})
    # `restates_the_goal` needs the goal's own key; carried as an attribute so
    # Context stays a plain record of what reviewers may read.
    object.__setattr__(ctx, "sketch_goal_key",
                       eq_key(*sketch.nodes[goal][:2]) if goal in sketch.nodes
                       else None)
    return ctx
