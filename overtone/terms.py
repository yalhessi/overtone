"""TPTP prefix terms: parsing, alpha-normalisation, symbols, similarity.

Pure functions over term strings and nested tuples. Terms are represented as
`("f", arg, ...)` for applications and a bare `str` for variables and constants;
uppercase-initial names are variables, per TPTP CNF.

Note the Otter/EQP translator in `overtone/otter.py` deliberately does not share
this grammar -- Otter is infix with its own variable convention, so a common
parser would serve neither well.
"""
import re

VAR = re.compile(r"^[A-Z][A-Za-z0-9_]*$")


def tokenize(s):
    return re.findall(r"[A-Za-z0-9_$]+|[(),]", s)


def parse(tokens, i=0):
    """Parse name | name(t, ...) into nested tuples: ('f', arg, ...)."""
    name = tokens[i]
    i += 1
    if i < len(tokens) and tokens[i] == "(":
        args, i = [], i + 1
        while tokens[i] != ")":
            arg, i = parse(tokens, i)
            args.append(arg)
            if tokens[i] == ",":
                i += 1
        return (name, *args), i + 1
    return name, i


def term(s):
    return parse(tokenize(s))[0]


def safe_term(s):
    """Parse or return None.

    TPTP carries clause shapes this grammar does not cover (propositional atoms,
    $-constants, arithmetic); skip them rather than abort a whole corpus scan.
    """
    try:
        toks = tokenize(s)
        if not toks:
            return None
        t, i = parse(toks)
        return t if i == len(toks) else None
    except (IndexError, ValueError):
        return None


def unparse(t):
    if isinstance(t, str):
        return t
    return f"{t[0]}({', '.join(unparse(a) for a in t[1:])})"


def fresh_vars():
    i = 0
    while True:
        yield f"V{i + 1}"
        i += 1


def alpha(t, mapping=None, fresh=None):
    """Rename variables by first occurrence so alpha-equal terms compare equal."""
    if mapping is None:
        mapping, fresh = {}, fresh_vars()
    if isinstance(t, str):
        if VAR.match(t):
            if t not in mapping:
                mapping[t] = next(fresh)
            return mapping[t]
        return t
    return (t[0], *(alpha(a, mapping, fresh) for a in t[1:]))


def alpha_key(s):
    """A string that is equal for alpha-equivalent terms.

    Replaces `ladder.norm`, which mapped every variable to `*` and so wrongly
    equated `f(X,Y)` with `f(X,X)`. Unparseable input falls back to a
    whitespace-normalised string rather than None: lemma sides come from twee's
    own output and must not be silently dropped from a comparison.
    """
    t = safe_term(s)
    if t is None:
        return re.sub(r"\s+", "", s)
    return unparse(alpha(t))


def symbols(t, out=None):
    """Function/constant symbols of a term as (name, arity); variables excluded."""
    if out is None:
        out = set()
    if isinstance(t, str):
        if not VAR.match(t):
            out.add((t, 0))
        return out
    out.add((t[0], len(t) - 1))
    for a in t[1:]:
        symbols(a, out)
    return out


def subtrees(t, out=None):
    if out is None:
        out = set()
    out.add(t)
    if not isinstance(t, str):
        for a in t[1:]:
            subtrees(a, out)
    return out


def similarity(sets1, sets2):
    """Twitch's structural similarity: mean directional best-match Jaccard.

    Inputs are lists of subtree sets, one per axiom (see `problems.axiom_sets`).
    Subtrees should already be alpha-normalised so that axioms differing only in
    variable naming compare equal.
    """
    if not sets1 or not sets2:
        return 0.0

    def jac(a, b):
        return len(a & b) / len(a | b) if a | b else 1.0

    def direction(xs, ys):
        return sum(max(jac(x, y) for y in ys) for x in xs) / len(xs)

    return (direction(sets1, sets2) + direction(sets2, sets1)) / 2


def merged(sets):
    """Union of per-axiom subtree sets, for a cheap whole-problem comparison."""
    out = set()
    for s in sets:
        out |= s
    return out
