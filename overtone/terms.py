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
    return parse_error(s)[0]


def parse_error(s):
    """(term, reason) -- `safe_term` with the reason it failed.

    A caller scanning a corpus wants to skip the clause; a caller reviewing a
    proposed node has to tell the model what to fix, and "it did not parse" is
    not actionable. One agent proposed `associator(X,Y,Z) = additive_identity`
    as one side of an equation: the `=` is not a token of this grammar, so it
    was dropped, the leftover `additive_identity` made the parse short, and the
    node went to the prover -- which rejected it in 0.003s and reported the same
    "failed" a genuinely hard lemma reports.
    """
    toks = tokenize(s or "")
    if not toks:
        return None, "empty"
    if "=" in (s or ""):
        return None, ("contains `=`; a node's lhs and rhs are each a single "
                      "term, and the equation between them is the node itself. "
                      "An implication between two equations cannot be stated as "
                      "one equation")
    try:
        t, i = parse(toks)
    except (IndexError, ValueError):
        return None, "unbalanced parentheses or a missing argument"
    if i != len(toks):
        return None, (f"trailing tokens after a complete term: "
                      f"{' '.join(toks[i:])!r}")
    return t, None


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


def eq_key(lhs, rhs):
    """Identity of an equation, insensitive to variable names and orientation.

    Two equations are the same fact whether twee prints `a = b` or `b = a`, and
    whichever variable names it happened to pick -- so comparing them needs both
    normalisations. Sorting the two alpha-keys gives that in one step.

    Used for axiom containment (`problems.contains_axioms`) and for matching a
    proof's lemmas against a sketch's nodes (`agent.dag.mined_parents`), which
    previously carried its own private copy of this.
    """
    return tuple(sorted((alpha_key(lhs), alpha_key(rhs))))


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


def symbols_in(text: str) -> set:
    """Lowercase-initial identifiers in a term string: its function symbols.

    TPTP variables are uppercase-initial, so anything lowercase is a function or
    constant. Shared by `dag.grounding_errors` and the signature reviewer on
    purpose: if the two disagreed about what counts as a symbol, review would
    pass a node that then aborts the whole run when verification rejects it.
    """
    return set(re.findall(r"\b([a-z_][A-Za-z0-9_]*)\b", text or ""))
