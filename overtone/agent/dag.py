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
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from overtone import runner
from overtone.agent import hints as hintlib
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
    """

    def __init__(self, nodes):
        self.nodes = dict(nodes)
        self.validate()

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
        self.layers()          # raises on a cycle

    def layers(self):
        """Topological layers; every node follows all of its parents."""
        done, out, remaining = set(), [], dict(self.nodes)
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

    def equations(self, names):
        return [(self.nodes[n][0], self.nodes[n][1]) for n in names]

    def to_json(self):
        """`{name: {lhs, rhs, parents}}` -- JSON-safe, order preserved.

        A sketch used to exist only as a Python literal in a script. The runner
        revises one across iterations and has to persist it in between, and a
        trajectory records the sketch at every step.
        """
        return {n: {"lhs": l, "rhs": r, "parents": list(p)}
                for n, (l, r, p) in self.nodes.items()}

    @classmethod
    def from_json(cls, obj):
        return cls({n: (v["lhs"], v["rhs"], list(v.get("parents", [])))
                    for n, v in obj.items()})


def channel_for(names, sketch, node, override=None):
    """"axioms" or "hints" for this set of supporting lemmas.

    Axioms when the set is small and is exactly this node's recorded parents;
    hints otherwise. See the module docstring -- an axiom forms critical pairs
    with every rule, which a precise handful earns and a loose bag does not.
    """
    if override:
        return override
    if not names:
        return "axioms"                       # nothing either way; keep it simple
    if len(names) > AXIOM_MAX:
        return "hints"
    return "axioms" if set(names) == set(sketch.nodes[node][2]) else "hints"


def _job(a):
    """Module-level so it pickles into a process pool."""
    problem, node, lhs, rhs, eqs, channel, direction, budget, outdir, binary = a
    tag = f"{node}.{direction[2:]}"
    kw, flags = {}, [*BASE_FLAGS, direction]
    if channel == "axioms":
        kw["extra_axioms"] = eqs
    else:
        terms = []
        for l, r in eqs:
            terms += [t for t in (l, r) if "(" in t and t not in terms]
        kw["hints"] = terms
        if terms:
            flags = [*BASE_FLAGS, *hintlib.HINT_FLAGS, direction]
    path = runner.write_problem(problem, Path(outdir) / f"{tag}.p",
                                goal=(lhs, rhs), goal_prefix="sk_dag_",
                                axiom_prefix="parent", **kw)
    r = runner.run(path, flags, budget, problem=problem, binary=binary)
    # Keep the output either way. A failed run is the more informative one: with
    # --all-lemmas it still lists everything derived before the budget ran out,
    # and those are the candidate missing nodes. `assoc_def_add` -- worth 18x on
    # assoc_add_1 -- was read off exactly this kind of listing.
    suffix = "out" if r.proved else "fail.out"
    (Path(outdir) / f"{tag}.{suffix}").write_text(r.output)
    # Full precision, not 1 dp: these rows are summed over hundreds of runs to
    # report what a problem cost, and rounding first accumulates error. Readers
    # that display a time format it themselves.
    return {"node": node, "direction": direction, "channel": channel,
            "n_support": len(eqs), "result": r.status, "proved": r.proved,
            "cpu": r.cpu, "wall": r.wall}


def verify(problem, sketch: Sketch, *, outdir: Path, budget=600, budgets=None,
           scope="parents", channel=None, directions=DIRECTIONS, workers=8,
           binary: str | None = None, known=(), prior_results=(),
           retry_standalone=True):
    """Prove every node, in topological order, each in the scope its edges imply.

    A node whose parents did not prove is skipped rather than attempted without
    them -- attempting it anyway is what produced the "6 of 19 failed" reading
    that scope later explained away.

    `retry_standalone` re-attempts a failed node with nothing supplied, and it
    is on by default because the alternative was measured and is expensive.
    `teichmuller` was drafted with five parents, three of them (trilinearity) not
    on its derivation path at all; it needs none of them and proves in 3.3s from
    the bare axioms, took 358.6s given just the two sign lemmas, and timed out at
    900s given all five. One mis-drafted edge then blocked six downstream nodes.
    The prover's soundness catches a wrong *statement*; nothing catches a wrong
    *edge*, so the cost of one extra run per failure buys the only check there is.

    `known` names nodes already proved by an earlier run, so a resumed run
    re-verifies nothing; pass that run's `results` as `prior_results` so the
    merged record stays complete. `budgets` overrides `budget` per node. `channel` forces
    a channel; leaving it None applies `channel_for`, which is the point of the
    DAG.
    """
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    budgets = budgets or {}
    # Carry the earlier run's rows forward. Without this a resumed run writes a
    # dag.json describing only the nodes it re-ran, and anything reading it --
    # the blueprint, for one -- reports every other node as never attempted.
    results = list(prior_results)
    proved = {n: {"cpu": None, "direction": None, "n_support": 0,
                  "channel": "cached"} for n in known if n in sketch.nodes}
    if proved:
        print(f"resuming: {len(proved)} node(s) already proved", flush=True)

    for depth, layer in enumerate(sketch.layers(), start=1):
        runnable = [n for n in layer if n not in proved
                    and all(p in proved for p in sketch.nodes[n][2])]
        skipped = [n for n in layer if n not in runnable and n not in proved]
        print(f"layer {depth}: {len(runnable)} node(s)"
              + (f", skipped {skipped}" if skipped else ""), flush=True)
        jobs = []
        for n in runnable:
            names = sketch.scope(n, scope)
            ch = channel_for(names, sketch, n, channel)
            lhs, rhs, _ = sketch.nodes[n]
            for d in directions:
                jobs.append((problem, n, lhs, rhs, sketch.equations(names), ch,
                             d, budgets.get(n, budget), str(outdir), binary))
        if not jobs:
            continue
        with ProcessPoolExecutor(max_workers=min(len(jobs), workers)) as pool:
            res = list(pool.map(_job, jobs))
        results += res

        # Guard: anything that failed in scope gets one standalone attempt,
        # because a wrong edge is indistinguishable from a hard lemma otherwise.
        retry = [n for n in runnable
                 if not any(r["node"] == n and r["proved"] for r in res)
                 and retry_standalone and sketch.nodes[n][2]]
        if retry:
            print(f"  retrying standalone: {retry}", flush=True)
            rjobs = [(problem, n, *sketch.nodes[n][:2], [], "axioms", d,
                      budgets.get(n, budget), str(outdir), binary)
                     for n in retry for d in directions]
            with ProcessPoolExecutor(max_workers=min(len(rjobs), workers)) as pool:
                rres = list(pool.map(_job, rjobs))
            for r in rres:
                r["scope_retry"] = True
            results += rres
            res += rres

        for n in runnable:
            best = min((r for r in res if r["node"] == n and r["proved"]),
                       key=lambda r: r["cpu"], default=None)
            if best:
                proved[n] = best
                flag = "  (standalone retry -- check this node's edges)" \
                    if best.get("scope_retry") else ""
                print(f"  {n:<18} PROVED {best['direction']:<18} "
                      f"{best['cpu']:>7.1f}s  {best['n_support']} as "
                      f"{best['channel']}{flag}", flush=True)
            else:
                print(f"  {n:<18} unproven in both directions", flush=True)

    out = {"problem": problem, "scope": scope, "channel": channel or "auto",
           "n_nodes": len(sketch.nodes), "n_proved": len(proved),
           "proved": {k: v["cpu"] for k, v in proved.items()},
           "missing": [n for n in sketch.nodes if n not in proved],
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
            directions=DIRECTIONS, workers=2, label="final"):
    """Run the problem's own file with `equations` appended as axioms.

    The final phase `verify` lacks. It was written twice -- in
    `scripts/transfer_dag._final` and in `ladder.run_ladder` -- and both did the
    same thing: take what has been proved and attack the real conjecture with it.

    The problem file is not modified. `runner.write_problem` copies it and adds
    the equations, so what is proved is the problem as TPTP states it, not a
    restatement of it.
    """
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    jobs = [(problem, direc, tuple(equations), budget, str(outdir), binary, label)
            for direc in directions]
    with ProcessPoolExecutor(max_workers=min(len(jobs), workers)) as pool:
        return list(pool.map(_attempt_job, jobs))


def _attempt_job(a):
    problem, direction, eqs, budget, outdir, binary, label = a
    tag = f"{label}.{direction[2:]}"
    path = runner.write_problem(problem, Path(outdir) / f"{tag}.p",
                                extra_axioms=list(eqs), axiom_prefix="lemma")
    r = runner.run(path, [*BASE_FLAGS, direction], budget, problem=problem,
                   binary=binary)
    suffix = "out" if r.proved else "fail.out"
    (Path(outdir) / f"{tag}.{suffix}").write_text(r.output)
    return {"node": label, "direction": direction, "channel": "axioms",
            "n_support": len(eqs), "result": r.status, "proved": r.proved,
            "cpu": r.cpu, "wall": r.wall}


def cost(*row_lists):
    """Total prover time across any number of result lists, failures included.

    The number a per-problem pipeline reports. Everything spent counts: failed
    nodes, standalone retries, both goal directions, and the final attempts --
    not just the runs that happened to succeed.
    """
    rows = [r for rl in row_lists for r in (rl or ())]
    return {"cpu": round(sum(r.get("cpu") or 0.0 for r in rows), 1),
            "wall": round(sum(r.get("wall") or 0.0 for r in rows), 1),
            "n_runs": len(rows),
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
