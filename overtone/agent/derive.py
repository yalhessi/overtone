"""Build a starting sketch from a problem's own axioms and its conjecture.

Eight agent runs on RNG029-5 drafted accelerants and never a waypoint: universal
generic lemmas proved 12/12, structural ones 7/12, and `goal_contact.both` sat
frozen at 152 across two independent runs. The model is not going to invent the
decomposition, and it does not have to -- for a target in this signature the
decomposition is computable from the goal's syntax.

What this produces on RNG029-5, all verified against the problem's own axioms:

    associator additive in each argument   universal, expands to 0    ~30s each
    associator(X+Y,X+Y,Z) = 0             instance of an axiom         0.01s
    alt12 / alt23                         polarization of the axioms   0.02s
    associator cyclic                     certificate over alt12/23    0.01s
    the bridge                            decomposition of the goal    unproven
    the conjecture                        given the bridge              6.7s

so the model opens on a sketch where the scaffold is proved and exactly one
obligation is named, instead of on a bare goal it has repeatedly failed to
decompose. The bridge is where the mathematics actually is: the alternating laws
span *twice* the Moufang residual over the integers and not the residual itself.

**Scope, stated plainly.** The normal form is the free non-associative ring, so
this covers ring-signature problems and nothing else. The *shape* -- polarize the
axioms, name the lemmas each derivation uses, decompose the goal over universal
terms -- is signature-agnostic; a second theory needs its own normaliser.

Nothing here reads a donor, a stored sketch, or `scripts/rng_dag.py`. Every node
is derived from the problem file.
"""
from overtone import freering as F, problems
from overtone.agent.dag import Sketch

# Operators the free-ring normal form knows how to expand, with their arities.
# An additivity lemma is emitted per argument, and kept only if it expands to
# zero -- so a symbol that is not really multilinear contributes nothing.
DEFINED = {"associator": 3, "commutator": 2}

VARS = ("X", "Y", "Z", "W", "V")


def _apply(op, args):
    return f"{op}({','.join(args)})"


def additivity(op, arity):
    """`[(name, lhs, rhs)]` -- the operator is additive in each argument.

    Universal: it follows from distributivity and the operator's definition, so
    it needs no theory content. These are what an expansion of a polarized axiom
    actually rewrites with, and supplying them is what takes `alt12` from
    unproven at 60s to 0.02s.
    """
    out = []
    for i in range(arity):
        base = list(VARS[:arity])
        fresh = VARS[arity]
        left = list(base)
        left[i] = f"add({base[i]},{fresh})"
        a, b = list(base), list(base)
        b[i] = fresh
        lhs = _apply(op, left)
        rhs = f"add({_apply(op, a)},{_apply(op, b)})"
        if not F.expand(F.parse(lhs), F.parse(rhs)):     # universal, or drop it
            out.append((f"{op}_add_{i + 1}", lhs, rhs))
    return out


def _repeated(term):
    """`(op, variable, [argument indices])` for a variable repeated in `op(...)`.

    Read off the term's ASSOCIATOR form, not the axiom as written. RNG003-0
    states left-alternativity as `multiply(multiply(X,X),Y) = multiply(X,...)`,
    whose head is `multiply`; the same identity over associator terms is
    `associator(X,X,Y)`, where the repetition and the argument positions are
    visible and are exactly what the additivity lemmas key on.

    Only the direct-argument case: a variable nested deeper needs more than
    additivity to expand, and pretending otherwise would emit a node with
    parents that cannot discharge it -- the wrong-edge failure this project
    measures as costlier than a missing one.
    """
    from overtone.terms import VAR

    if isinstance(term, str) or term[0] not in DEFINED:
        return None
    args = term[1:]
    for v in sorted({a for a in args if isinstance(a, str) and VAR.match(a)}):
        at = [i for i, a in enumerate(args) if a == v]
        if len(at) > 1:
            return term[0], v, at
    return None


def polarizations(problem, add_names):
    """Nodes for each axiom that polarizes, with the parents its derivation uses.

    Two nodes per axiom: the instance the polarization substitutes into -- which
    is a direct instantiation of the axiom and proves in 0.01s -- and the polar
    form itself, whose parents are that instance plus the additivity lemmas for
    exactly the argument positions the repeated variable occupies.

    Naming the parents is the point. `alt12_additive` is unproven at 60s and
    proves in 0.02s given these three, and no drafting run has ever found them;
    the derivation knows them because it used them.
    """
    from overtone.terms import safe_term, unparse

    out = []
    for name, (lhs, rhs) in problems.named_axioms(
            problems.problem_path(problem)).items():
        residual = F.expand(F.safe_parse(lhs) or {}, F.safe_parse(rhs) or {})
        if not residual:
            continue                       # definitional, already in the form
        compact = F.render_compact(residual)
        hit = _repeated(safe_term(compact) if compact else None)
        if not hit:
            continue
        op, v, at = hit
        fresh = next(x for x in VARS if x not in F.variables(residual))

        args = list(safe_term(compact)[1:])
        for i in at:
            args[i] = ("add", v, fresh)
        lin = f"lin_{name}"
        out.append((lin, _apply(op, [unparse(x) for x in args]),
                    "additive_identity", []))

        polar = F.render_compact(F.polarize(residual, v, fresh))
        if polar is None:
            continue
        parents = [lin] + [n for n in add_names.get(op, [])
                           if int(n.rsplit("_", 1)[1]) - 1 in at]
        out.append((f"{name}_polar", polar, "additive_identity", parents))
    return out


def symmetries(op, arity, proved, var_names=("X", "Y", "Z")):
    """Argument permutations of `op` that follow from what is already proved.

    `associator_cyclic` arrives this way: it is `+1*alt12[X,Y,Z] -1*alt23[Y,X,Z]`,
    a two-term integer certificate over the polarizations, so it is derived
    rather than recalled. Only permutations with a certificate are emitted, and
    each carries the lemmas its certificate cites as its parents.
    """
    import itertools

    if arity != 3 or not proved:
        return []
    basis = []
    for label, elem in proved:
        for m in F._renamings(F.variables(elem), var_names):
            basis.append((f"{label}[{','.join(m[k] for k in sorted(m))}]",
                          F.substitute(elem, {k: F.V(w) for k, w in m.items()})))
    seen, uniq = set(), []
    for label, p in basis:
        key = tuple(sorted((str(k), v) for k, v in p.items()))
        if p and key not in seen:
            seen.add(key)
            uniq.append((label, p))

    out = []
    base = list(var_names)
    for perm in itertools.permutations(range(3)):
        if perm == (0, 1, 2):
            continue
        other = [base[i] for i in perm]
        lhs, rhs = _apply(op, base), _apply(op, other)
        target = F.expand(F.parse(lhs), F.parse(rhs))
        cert = F.certificate(target, uniq)
        if not cert.get("coefficients"):
            continue
        cites = sorted({c.split("[")[0] for c in cert["coefficients"]})
        out.append((f"{op}_perm_{''.join(str(i) for i in perm)}",
                    lhs, rhs, cites))
    return out


def derive_sketch(problem, goal=None):
    """`(Sketch, notes)` -- the problem's axioms plus everything derivable.

    The goal node is the conjecture, copied from the problem file, and its only
    parent is the bridge: the goal's own residual written over universal
    associator terms. On RNG029-5 that residual is two terms, so the conjecture
    reduces to one obligation and follows from it in 6.7s.
    """
    goal = goal or f"{problem.lower()}_goal"
    sketch = Sketch.from_problem(problem, goal=goal)
    nodes, notes = dict(sketch.nodes), []

    add_names = {}
    for op, arity in DEFINED.items():
        if op not in {n for n, _ in problems.problem_symbols(
                problems.problem_path(problem))}:
            continue
        for name, lhs, rhs in additivity(op, arity):
            nodes[name] = (lhs, rhs, [])
            add_names.setdefault(op, []).append(name)
            notes.append(f"{name}: {op} is additive in argument "
                         f"{name.rsplit('_', 1)[1]} (universal)")

    polar = []
    for name, lhs, rhs, parents in polarizations(problem, add_names):
        if name in nodes:
            continue
        nodes[name] = (lhs, rhs, parents)
        notes.append(f"{name}: {'axiom instance' if name.startswith('lin_') else 'polarization'}"
                     + (f", from {parents}" if parents else ""))
        if not name.startswith("lin_"):
            polar.append((name, F.expand(F.parse(lhs), F.parse(rhs))))

    for op, arity in DEFINED.items():
        for name, lhs, rhs, cites in symmetries(op, arity, polar):
            if name in nodes:
                continue
            nodes[name] = (lhs, rhs, cites)
            notes.append(f"{name}: certificate over {cites}")

    conj = problems.conjecture(problems.problem_path(problem))
    d = F.decompose(conj[0], conj[1])
    if d.get("terms"):
        elements = d["elements"]
        names = sorted(F.variables(d["target"]))
        twee = {l: t for l, _, t in F.associator_terms(names,
                                                       F.degree(d["target"]))}
        pos = [l for l, c in d["terms"] if c > 0 for _ in range(c)]
        neg = [l for l, c in d["terms"] if c < 0 for _ in range(-c)]
        if len(d["terms"]) == 2 and len(pos) == 1 and len(neg) == 1:
            lhs, rhs = twee[pos[0]], twee[neg[0]]         # A = B reads better
        else:
            lhs = F.render_compact(d["target"], names)
            rhs = "additive_identity"
        # Not every derived lemma: handing the bridge all eleven claims is the
        # loose-bag-as-axioms configuration measured here as ruinous, and rule 3
        # asks for few and exact. Two mechanical filters, both defensible
        # without knowing the proof: drop the `lin_*` instances, which are
        # scaffolding for the polarizations rather than content, and drop any
        # lemma about a defined operator the bridge does not mention -- RNG029-5
        # loses both commutator lemmas that way. The model prunes further with
        # `set_parents`, and `unused_support` will name the dead ones the moment
        # the bridge proves.
        speaks = {op for op in DEFINED if op in lhs or op in rhs}
        support = sorted(
            n for n in nodes
            if n not in sketch.given and n != goal and not n.startswith("lin_")
            and any(op in nodes[n][0] or op in nodes[n][1] for op in speaks))
        nodes["bridge"] = (lhs, rhs, support)
        l, r, _ = nodes[goal]
        nodes[goal] = (l, r, ["bridge"])
        notes.append(f"bridge: the goal over {len(d['terms'])} universal "
                     f"associator term(s); the conjecture follows from it")
    return Sketch(nodes, given=sketch.given), notes
