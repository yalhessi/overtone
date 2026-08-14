"""The free non-associative ring, for inventing waypoints and checking algebra.

Every statement in these theories expands into a formal sum of signed monomials
-- binary trees over the variables -- because `associator` and `commutator` are
*defined* by axioms and multiplication distributes over addition. That expansion
is a normal form, so equality of two statements is decidable here in
microseconds, with no prover.

Two uses, both earned the hard way:

**Checking.** Hand-drafted nodes in this project have been wrong repeatedly, and
each error cost a prover run to discover -- one cost a whole iteration. `expand`
settles in microseconds whether two statements are the same equation.

**Inventing.** A lemma that expands to 0 holds in *every* ring, so it is sound by
construction, needs no alternativity, and cannot be an accident of this problem.
Teichmuller is exactly such an identity and is the most useful node in the
RNG033-8 sketch. `express` finds more of them: give it a defect -- how far a
familiar associative law is from holding -- and it solves for that defect over a
basis of associator terms, exactly.

The limit is worth stating plainly: this decides identities true in ALL rings. It
says nothing about statements needing alternativity or Moufang, which is most
lemmas. It validates a rearrangement; it does not validate a theorem.
"""
from collections import Counter
from fractions import Fraction

__all__ = ["V", "mul", "add", "neg", "assoc", "comm", "expand", "same",
           "express", "to_twee"]


def _norm(c):
    return Counter({k: v for k, v in c.items() if v})


def V(name):
    """A variable."""
    return Counter({name: 1})


def mul(p, q):
    o = Counter()
    for a, sa in p.items():
        for b, sb in q.items():
            o[(a, b)] += sa * sb
    return _norm(o)


def neg(p):
    return Counter({k: -v for k, v in p.items()})


def add(*ps):
    o = Counter()
    for p in ps:
        o.update(p)
    return _norm(o)


def assoc(a, b, c):
    """(a,b,c) = (ab)c - a(bc), the associator as RNG003-0.ax defines it."""
    return add(mul(mul(a, b), c), neg(mul(a, mul(b, c))))


def comm(a, b):
    """[a,b] = ba - ab, the commutator as RNG003-0.ax defines it."""
    return add(mul(b, a), neg(mul(a, b)))


def expand(lhs, rhs):
    """`lhs - rhs` as a normal form. Empty means the equation holds in any ring."""
    return add(lhs, neg(rhs))


def same(lhs1, rhs1, lhs2, rhs2):
    """Do two equations say the same thing? Exact, and no prover involved."""
    return expand(lhs1, rhs1) == expand(lhs2, rhs2)


def express(defect, basis):
    """Solve `defect = sum c_i * basis_i` exactly, or None if unsolvable.

    `basis` is [(label, element)]. Returns [(label, coefficient)] for the nonzero
    coefficients. Exact rational elimination -- floating point would make a
    near-miss look like an identity, which is the failure mode this exists to
    prevent.
    """
    labels = [l for l, _ in basis]
    elems = [e for _, e in basis]
    keys = sorted({k for t in [defect] + elems for k in t}, key=str)
    rows = [[Fraction(e.get(k, 0)) for e in elems] + [Fraction(defect.get(k, 0))]
            for k in keys]
    n, piv, r = len(elems), [], 0
    for c in range(n):
        p = next((i for i in range(r, len(rows)) if rows[i][c]), None)
        if p is None:
            continue
        rows[r], rows[p] = rows[p], rows[r]
        f = rows[r][c]
        rows[r] = [v / f for v in rows[r]]
        for i in range(len(rows)):
            if i != r and rows[i][c]:
                g = rows[i][c]
                rows[i] = [a - g * b for a, b in zip(rows[i], rows[r])]
        piv.append(c)
        r += 1
        if r == len(rows):
            break
    if any(all(v == 0 for v in row[:n]) and row[n] != 0 for row in rows):
        return None                      # defect is outside the basis's span
    sol = [Fraction(0)] * n
    for i, c in enumerate(piv):
        sol[c] = rows[i][n]
    return [(labels[i], sol[i]) for i in range(n) if sol[i]]


def to_twee(p, var=str.upper):
    """A normal form back as a twee term, or None when it is empty (zero).

    Positive monomials first, then the negated ones, so the result reads as a
    sum rather than as a difference of two large sums.
    """
    def term(t):
        return var(t) if isinstance(t, str) else \
            f"multiply({term(t[0])},{term(t[1])})"

    pieces = []
    for k, v in sorted(p.items(), key=lambda kv: str(kv[0])):
        for _ in range(abs(int(v))):
            pieces.append(term(k) if v > 0 else f"additive_inverse({term(k)})")
    if not pieces:
        return "additive_identity"
    e = pieces[0]
    for t in pieces[1:]:
        e = f"add({e},{t})"
    return e


# ------------------------------------------------------------------- reviewer

_SIGNATURE = {"add", "multiply", "additive_inverse", "associator", "commutator"}


# The additive identity IS zero in the ring, and zero is the empty normal form.
# Without this the parser rejects any term naming it and the reviewer returns no
# opinion: seven nodes of one run went unchecked for exactly this reason, several
# of them members of the false-lemma family the reviewer exists to flag.
ZERO = "additive_identity"


def _parse(t, env):
    t = t.strip()
    if t in env:
        return env[t]
    if t == ZERO:
        return Counter()
    if "(" not in t:
        raise ValueError(t)
    head, rest = t.split("(", 1)
    args, depth, cur = [], 0, ""
    for ch in rest[:-1]:
        if ch == "," and depth == 0:
            args.append(cur)
            cur = ""
        else:
            depth += (ch == "(") - (ch == ")")
            cur += ch
    args.append(cur)
    p = [_parse(a, env) for a in args]
    return {"add": lambda: add(*p), "multiply": lambda: mul(*p),
            "associator": lambda: assoc(*p), "commutator": lambda: comm(*p),
            "additive_inverse": lambda: neg(p[0])}[head]()


# --------------------------------------------------------------- generation
# Everything above decides whether a statement holds in EVERY ring. That is the
# wrong question for a target like RNG029-5, whose four decisive lemmas are all
# theory-specific -- none of them expands to zero. What follows works with the
# problem's OWN identities instead: read them off its axioms, polarize them,
# close under bounded consequence, and ask whether the target's residual is an
# integer combination of what comes out.
#
# The integer part is not a detail. `express` solves over the rationals and will
# happily return a coefficient of 1/2, which assumes the ring has no 2-torsion --
# an assumption the alternative-ring axioms do not make. A certificate has to be
# integral to mean anything.


def parse(text, env=None):
    """A twee term as a normal form. `_parse` with the variable env inferred.

    TPTP variables are uppercase-initial, so anything else is a function symbol
    or the additive identity. Raises on a term outside this signature, like
    `_parse` -- callers that want silence use `safe_parse`.
    """
    from overtone.terms import VAR, safe_term, subtrees

    if env is None:
        t = safe_term(text)
        if t is None:
            raise ValueError(f"not a term: {text!r}")
        env = {s: V(s) for s in subtrees(t)
               if isinstance(s, str) and VAR.match(s)}
    return _parse(text, env)


def safe_parse(text, env=None):
    try:
        return parse(text, env)
    except (ValueError, KeyError, IndexError, TypeError):
        return None


def variables(p):
    """The variable names occurring in a normal form."""
    from overtone.terms import VAR

    out = set()
    for mono in p:
        stack = [mono]
        while stack:
            t = stack.pop()
            if isinstance(t, str):
                if VAR.match(t):
                    out.add(t)
            else:
                stack.extend(t)
    return out


def degree(p):
    """The largest number of variable occurrences in any monomial."""
    def d(t):
        return 1 if isinstance(t, str) else sum(d(x) for x in t)
    return max((d(m) for m in p), default=0)


def substitute(p, env):
    """Evaluate every monomial under `env`, extended linearly.

    Substitution is a ring homomorphism on the free ring, so it commutes with
    the normal form: a variable may be replaced by any element, including a sum,
    which is what polarization needs.
    """
    def ev(t):
        if isinstance(t, str):
            return env.get(t, V(t))
        return mul(ev(t[0]), ev(t[1]))

    out = Counter()
    for mono, coeff in p.items():
        term = ev(mono)
        for k, v in term.items():
            out[k] += coeff * v
    return _norm(out)


def polarize(p, var, fresh):
    """`p(var -> var + fresh) - p(var) - p(fresh)`: the polar form in `var`.

    If `p = 0` is an identity of the theory then so are all three terms, so the
    combination is a consequence -- and it is a *new* one whenever `p` is
    nonlinear in `var`. This is how the alternating laws arise from the
    alternative ones: polarizing `associator(X,X,Y)` in `X` gives
    `associator(X,Y,Z) + associator(Y,X,Z)`, which is `alt12_additive`, a node
    of the successful sketch that agent runs repeatedly fail to prove.
    """
    both = substitute(p, {var: add(V(var), V(fresh))})
    return add(both, neg(p), neg(substitute(p, {var: V(fresh)})))


def theory_identities(problem):
    """`[(axiom name, residual)]` for the axioms this normal form does NOT encode.

    An axiom that expands to zero -- the associator and commutator definitions,
    distributivity, additive associativity and commutativity -- is already built
    into `mul`/`add`/`assoc`/`comm`, so it carries no information here and is
    dropped. What survives is the theory's actual content: for RNG003-0 that is
    the two alternative laws, and they are exactly the axioms whose consequences
    the drafting model keeps failing to find.
    """
    from overtone import problems

    out = []
    for name, (lhs, rhs) in problems.named_axioms(
            problems.problem_path(problem)).items():
        l, r = safe_parse(lhs), safe_parse(rhs)
        if l is None or r is None:
            continue                      # outside this signature; no opinion
        res = expand(l, r)
        if res:
            out.append((name, res))
    return out


def _renamings(src_vars, targets):
    """Every map from `src_vars` into `targets`, identifications included.

    Identifying two variables is a specialisation, which is sound for an
    identity -- if `p = 0` for all values then it holds when two are equal.
    """
    import itertools

    src = sorted(src_vars)
    for combo in itertools.product(sorted(targets), repeat=len(src)):
        yield dict(zip(src, combo))


def consequences(identities, target_vars, max_degree, limit=4000):
    """Bounded closure of `identities` under the operations that preserve `= 0`.

    Three moves, each sound for an identity and each raising degree by at most
    one: rename or identify variables, multiply on the left by a variable, and
    multiply on the right. Polarization is applied first, since it is the move
    that creates genuinely new identities rather than instances of old ones.

    Bounded by the target's own degree, because a consequence larger than the
    thing it is meant to certify cannot appear in a cancelling combination
    without another consequence to cancel against -- and the search is
    exponential in the bound.
    """
    seen, out = set(), []

    def offer(label, p):
        """Record `p` if it is new and small enough. Returns whether to CONTINUE.

        Not whether it was added -- conflating the two made the first duplicate
        abort the whole closure, which capped generation at 18 elements and
        never reached the target's degree at all.
        """
        if p and degree(p) <= max_degree:
            key = tuple(sorted((str(k), v) for k, v in p.items()))
            if key not in seen:
                seen.add(key)
                out.append((label, p))
        return len(out) < limit

    # polarize every repeated variable before anything else
    seeded = []
    for name, res in identities:
        seeded.append((name, res))
        used = variables(res)
        # An uppercase-initial name, or `variables` will not see it as a
        # variable and the renaming pass will treat it as a constant.
        fresh = next(f"P{i}" for i in range(99) if f"P{i}" not in used)
        for v in sorted(used):
            pol = polarize(res, v, fresh)
            if pol:
                seeded.append((f"polarize({name},{v})", pol))

    for name, res in seeded:
        for m in _renamings(variables(res), target_vars):
            shown = ",".join(f"{k}->{m[k]}" for k in sorted(m))
            env = {k: V(v) for k, v in m.items()}
            if not offer(f"{name}[{shown}]", substitute(res, env)):
                return out
    # then left/right multiplication, over what the renamings produced
    base = list(out)
    for label, p in base:
        for v in sorted(target_vars):
            if not offer(f"{v}*{label}", mul(V(v), p)):
                return out
            if not offer(f"{label}*{v}", mul(p, V(v))):
                return out
    # ... and substitution of one variable by a PRODUCT. Multiplying a degree-3
    # identity by a variable only ever yields a monomial of shape (1,3) or
    # (3,1); RNG029-5's residual contains `(xy)(zx)`, which is shape (2,2), so
    # without this move the target's own monomials are not even in the basis's
    # support and no certificate can exist for reasons that say nothing about
    # the mathematics.
    for name, res in seeded:
        vs = sorted(variables(res))
        for v in vs:
            for a in sorted(target_vars):
                for b in sorted(target_vars):
                    env = {v: mul(V(a), V(b))}
                    for m in _renamings([x for x in vs if x != v], target_vars):
                        env2 = dict(env, **{k: V(w) for k, w in m.items()})
                        shown = ",".join(f"{k}->{m[k]}" for k in sorted(m))
                        lbl = f"{name}[{v}->{a}*{b}{',' + shown if shown else ''}]"
                        if not offer(lbl, substitute(res, env2)):
                            return out
    return out


def monomials(var_names, d):
    """Every product of `d` variables, all bracketings.

    `[(label, element, twee term)]`. The twee term travels with the element
    because a generated node has to be *written down*: the normal form is a bag
    of monomials, and `to_twee` on the expansion of `alt12` produces a
    twelve-summand term where `add(associator(X,Y,Z),associator(Y,X,Z))` is what
    the sketch wants. Reconstructing the syntax afterwards would mean guessing
    which bracketing produced which monomial; carrying it costs nothing.
    """
    if d == 1:
        return [(v, V(v), v) for v in sorted(var_names)]
    out = []
    for k in range(1, d):
        for la, a, ta in monomials(var_names, k):
            for lb, b, tb in monomials(var_names, d - k):
                label = f"({la}{lb})" if d > 2 else f"{la}{lb}"
                out.append((label, mul(a, b), f"multiply({ta},{tb})"))
    return out


def associator_terms(var_names, d):
    """Degree-`d` expressions built from ONE associator: `[(label, elem, twee)]`.

    Universal by construction -- these are just terms, true of any ring -- so a
    decomposition over them assumes nothing about the theory. That is what makes
    the result usable: it converts a target into an obligation about associators
    without smuggling in the axioms that are supposed to discharge it.
    """
    out = []
    for a in range(1, d - 1):
        for b in range(1, d - a):
            cdeg = d - a - b
            if cdeg < 1:
                continue
            for la, ea, ta in monomials(var_names, a):
                for lb, eb, tb in monomials(var_names, b):
                    for lc, ec, tc in monomials(var_names, cdeg):
                        out.append((f"({la},{lb},{lc})", assoc(ea, eb, ec),
                                    f"associator({ta},{tb},{tc})"))
    # ... and an associator of single variables, multiplied by a monomial
    for lt, et, tt in (monomials(var_names, d - 3) if d > 3 else []):
        for x in sorted(var_names):
            for y in sorted(var_names):
                for z in sorted(var_names):
                    A, tA = assoc(V(x), V(y), V(z)), f"associator({x},{y},{z})"
                    out.append((f"{lt}*({x},{y},{z})", mul(et, A),
                                f"multiply({tt},{tA})"))
                    out.append((f"({x},{y},{z})*{lt}", mul(A, et),
                                f"multiply({tA},{tt})"))
    seen, uniq = set(), []
    for label, p, twee in out:
        if not p:
            continue
        key = tuple(sorted((str(k), v) for k, v in p.items()))
        if key not in seen:
            seen.add(key)
            uniq.append((label, p, twee))
    return uniq


def associator_basis(var_names, d):
    """`associator_terms` without the syntax, for callers that only solve."""
    return [(l, p) for l, p, _ in associator_terms(var_names, d)]


def render_compact(p, var_names=None):
    """`p` written as a short sum of associator terms, or None.

    `to_twee` renders the expansion, which for `alt12` is twelve summands of
    products; this renders `add(associator(X,Y,Z),associator(Y,X,Z))`. That
    difference decides whether a generated node is readable, and whether the
    nodes a model is shown look like the ones a person would write.
    """
    if not p:
        return "additive_identity"
    names = sorted(var_names or variables(p))
    terms = associator_terms(names, degree(p))
    cert = certificate(p, [(l, e) for l, e, _ in terms])
    if not cert.get("coefficients"):
        return None
    twee = {l: t for l, _, t in terms}
    pieces = []
    for label, coeff in sorted(cert["coefficients"].items()):
        for _ in range(abs(coeff)):
            pieces.append(twee[label] if coeff > 0
                          else f"additive_inverse({twee[label]})")
    out = pieces[0]
    for t in pieces[1:]:
        out = f"add({out},{t})"
    return out


def decompose(lhs, rhs, extra=()):
    """The target as a short integer combination of associator expressions.

    The point of the whole generation path. RNG029-5's residual comes back as
    **two terms** -- `(x,y,zx) - x*(y,z,x)` -- so the conjecture holds exactly
    when `associator(x,y,zx) = x * associator(y,z,x)`, and that reduction is
    universal: no alternativity, no theory content, nothing retrieved. It is a
    waypoint of the kind eight agent runs failed to invent, obtained from the
    goal's syntax alone.

    Solving in the raw monomial basis instead gives a 52-term identity with
    coefficients past 100, which certifies the target and suggests nothing. The
    basis is what makes the answer a decomposition rather than a tautology.
    """
    target = expand(parse(lhs), parse(rhs))
    if not target:
        return {"target": target, "terms": None,
                "note": "the statement is universal; nothing to decompose"}
    names = sorted(variables(target))
    basis = list(associator_basis(names, degree(target))) + list(extra)
    cert = certificate(target, basis)
    if not cert.get("coefficients"):
        return {"target": target, "terms": None, "basis": len(basis),
                "note": cert.get("reason") or "outside the span",
                "outside": cert.get("outside", [])}
    by = dict(basis)
    return {"target": target, "basis": len(basis),
            "terms": sorted(cert["coefficients"].items(),
                            key=lambda kv: (-abs(kv[1]), kv[0])),
            "elements": {k: by[k] for k in cert["coefficients"]}}


def certificate(target, basis):
    """Express `target` as a combination of `basis`, or explain why not.

    Returns a dict: `coefficients` (label -> Fraction) when the residual is in
    the rational span, `integral` saying whether every coefficient is a whole
    number, and `outside` naming the monomials no basis element can reach.

    **The integrality flag is the load-bearing part.** A certificate with a
    coefficient of 1/2 proves `2 * target = ...`, which gives `target` only in a
    ring without 2-torsion -- an assumption the alternative-ring axioms do not
    make. `express` above solves over the rationals and is fine for its job
    (checking a hand-written statement); a *generated* certificate has to say
    whether it is honest over the integers, and a caller that ignores this would
    manufacture unsound waypoints.

    Sparse column elimination, because the dense form is a 459x660 system on
    RNG029-5 and pure-Python dense elimination over `Fraction` does not finish.
    Each basis element touches a handful of monomials, so fill-in stays low.
    """
    support = set(target)
    for _, p in basis:
        support |= set(p)
    reach = set()
    for _, p in basis:
        reach |= set(p)
    outside = sorted((str(m) for m in set(target) - reach))
    if outside:
        return {"coefficients": None, "integral": False, "outside": outside,
                "n_basis": len(basis)}

    order = sorted(support, key=str)
    rank = {m: i for i, m in enumerate(order)}
    pivots, kernel = _lattice([p for _, p in basis], rank)
    coeffs, why = _solve_integral(dict(target), pivots, rank)
    if coeffs is not None:
        coeffs = _shorten(coeffs, kernel)
        named = {basis[i][0]: c for i, c in sorted(coeffs.items()) if c}
        return {"coefficients": named, "integral": True, "outside": [],
                "n_basis": len(basis)}
    # Not in the integer span. Say whether it is in the RATIONAL span, because
    # the two failures mean different things: outside ℚ too means the bounded
    # closure is simply short, while inside ℚ and outside ℤ means the target
    # follows only after dividing, i.e. only in a torsion-free ring.
    return {"coefficients": None, "integral": False, "outside": [],
            "rational": _rational_span(target, basis), "reason": why,
            "n_basis": len(basis)}


def _lattice(cols, rank):
    """Column-style Hermite form of the integer lattice spanned by `cols`.

    `{pivot monomial: (column, combination of original columns)}`, all integer.
    Insertion is the extended-gcd step: where a new column and a pivot both hit
    the same monomial, replace the pivot by their gcd combination and clear the
    new column, so the lattice is preserved exactly and nothing is divided.
    """
    pivots, kernel = {}, []
    for i, p in enumerate(cols):
        col, combo = dict(p), {i: 1}
        while col:
            m = min(col, key=lambda k: rank[k])
            if m not in pivots:
                if col[m] < 0:
                    col = {k: -v for k, v in col.items()}
                    combo = {k: -v for k, v in combo.items()}
                pivots[m] = (col, combo)
                break
            pcol, pcombo = pivots[m]
            a, b = pcol[m], col[m]
            g, s, t = _egcd(a, b)
            npcol = _lin(s, pcol, t, col)
            npcombo = _lin(s, pcombo, t, combo)
            col = _lin(a // g, col, -(b // g), pcol)
            combo = _lin(a // g, combo, -(b // g), pcombo)
            pivots[m] = (npcol, npcombo)
        else:
            # The column reduced to nothing, so this combination of basis
            # elements is zero: a kernel vector, and the only lever for turning
            # the arbitrary lattice point the elimination lands on into a SHORT
            # certificate. Without these the answer is a 55-term identity with
            # coefficients past 100, which certifies the target and suggests no
            # decomposition at all.
            if combo:
                kernel.append(combo)
    return pivots, kernel


def _solve_integral(target, pivots, rank):
    """Reduce `target` through the lattice, or say where it fails."""
    col, combo = dict(target), {}
    while col:
        m = min(col, key=lambda k: rank[k])
        if m not in pivots:
            return None, f"no lattice element reaches {m}"
        pcol, pcombo = pivots[m]
        if col[m] % pcol[m]:
            return None, (f"{col[m]} is not divisible by {pcol[m]} at {m}: the "
                          f"residual is reachable only after dividing")
        f = col[m] // pcol[m]
        col = _lin(1, col, -f, pcol)
        combo = _lin(1, combo, -f, pcombo)
    return {k: -v for k, v in combo.items()}, ""


def _cost(c):
    """Prefer few terms, then small coefficients. A certificate is a proposed
    decomposition, so its length is the thing that matters."""
    return (sum(1 for v in c.values() if v), sum(abs(v) for v in c.values()))


def _shorten(coeffs, kernel, rounds=6):
    """Greedily add kernel vectors while that makes the certificate smaller.

    The elimination lands on an arbitrary point of the solution lattice. Any
    multiple of any kernel vector may be added without changing what is
    certified, so this walks toward a short one. Greedy rather than LLL: cheap,
    and the question here is whether a compact certificate exists at all, not
    whether this is the shortest possible.
    """
    best = {k: v for k, v in coeffs.items() if v}
    for _ in range(rounds):
        improved = False
        for kv in kernel:
            for step in (1, -1):
                trial, cur = best, _cost(best)
                while True:
                    nxt = _lin(1, trial, step, kv)
                    if _cost(nxt) >= cur:
                        break
                    trial, cur = nxt, _cost(nxt)
                if trial is not best:
                    best, improved = trial, True
    return best


def _rational_span(target, basis):
    """Whether the residual is in the rational span -- a diagnostic only."""
    return express(target, basis) is not None


def _egcd(a, b):
    if not b:
        return (abs(a), 1 if a >= 0 else -1, 0)
    old_r, r = a, b
    old_s, s, old_t, t = 1, 0, 0, 1
    while r:
        q = old_r // r
        old_r, r = r, old_r - q * r
        old_s, s = s, old_s - q * s
        old_t, t = t, old_t - q * t
    if old_r < 0:
        old_r, old_s, old_t = -old_r, -old_s, -old_t
    return old_r, old_s, old_t


def _lin(ca, a, cb, b):
    out = {k: ca * v for k, v in a.items()}
    for k, v in b.items():
        out[k] = out.get(k, 0) + cb * v
    return {k: v for k, v in out.items() if v}


def reviewer(action, ctx):
    """Report whether a proposed node holds in EVERY ring.

    A note, except against a claim. Non-universal is the normal case -- most
    useful lemmas need the problem's own axioms, and rejecting them would remove
    exactly the nodes worth having, so "not provable in the weaker theory" must
    never read as "false". What the agent lacked was the *information*: it
    proposed four nodes as pure expansions of the associator definition and
    distributivity, which would make them universal, and all four were not. It
    was never told, so it repeated the error for three iterations.

    The one rejection is a CONTRADICTION: the node declares
    `justification="universal"` and expansion leaves a residue. That is not this
    reviewer deciding the node is false -- it is the node's own stated grounds
    failing a check those grounds are exactly strong enough to settle. A node
    that claims nothing is still only ever noted.
    """
    from overtone.agent.review import NOTE, REJECT, Finding

    lhs, rhs = action.get("lhs"), action.get("rhs")
    if not (lhs and rhs):
        return []
    env = {c: V(c.lower()) for c in "VWXYZ"}
    try:
        residue = expand(_parse(lhs, env), _parse(rhs, env))
    except (ValueError, KeyError, IndexError, TypeError):
        # TypeError is the arity case: `associator(X,Y)` splits into a known
        # head with the wrong number of arguments, so the lambda raises rather
        # than the dict lookup. A reviewer that raises ends a run that may have
        # spent thousands of prover-seconds, and this one's contract is to have
        # no opinion on anything outside its language.
        return []
    universal = not residue
    if universal:
        return [Finding("free_ring", action.get("name", "?"), NOTE,
                        "holds in every ring (sound by construction)",
                        {"universal": True, "residue": 0})]
    if action.get("justification") == "universal":
        return [Finding("free_ring", action.get("name", "?"), REJECT,
                        f"declared `universal`, but expanding the definitions "
                        f"leaves {len(residue)} monomial(s), so it is not an "
                        f"identity of every ring. Either the algebra is wrong "
                        f"-- fix the statement rather than subdividing it -- or "
                        f"it is `theory_specific`, which is the normal and "
                        f"acceptable case.",
                        {"universal": False, "residue": len(residue),
                         "claimed": "universal"})]
    return [Finding("free_ring", action.get("name", "?"), NOTE,
                    f"needs the theory's own axioms: {len(residue)} "
                    f"monomials remain after expanding definitions",
                    {"universal": False, "residue": len(residue)})]
