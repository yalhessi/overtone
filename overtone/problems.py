"""Reading TPTP problems: locating them, resolving includes, extracting equations.

Everything here is about the bytes of a `.p` file. Term-level operations live in
`overtone.terms`; twee output parsing lives in `overtone.proofs`.
"""
import re
from functools import lru_cache
from pathlib import Path

from overtone import config
from overtone.terms import alpha, safe_term, subtrees, symbols

SPC_UEQ = re.compile(r"^%\s*SPC\s*:\s*CNF_(UNS|SAT|UNK|OPN)_\w*_UEQ\s*$")
RATING = re.compile(r"^%\s*Rating\s*:\s*([0-9.]+)")
# The header block ends at the first non-comment line; stop there rather than
# scanning whole problem files.
HEADER_END = re.compile(r"^\s*[^%\s]")
INCLUDE = re.compile(r"include\(\s*'([^']+)'\s*\)")


@lru_cache(maxsize=1)
def _index() -> dict:
    """Map problem stem -> path, built with one rglob.

    Lazy on purpose: at import time this would run once per pool worker at sweep
    startup. TPTP problem names are unique, so a dict is equivalent to the
    previous `next(rglob(...))` while costing one traversal instead of one per
    lookup -- `find_donor` used to pay a full rglob per candidate donor.
    """
    return {p.stem: p for p in (config.tptp_root() / "Problems").rglob("*.p")}


def problem_path(name: str) -> Path:
    """Locate a TPTP problem by bare name, e.g. ROB034-1."""
    hit = _index().get(name)
    if hit is None:
        raise FileNotFoundError(f"{name}.p not found under TPTP_ROOT/Problems")
    return hit


def read_with_includes(path: Path) -> str:
    """Problem text with `include('Axioms/...')` files appended."""
    text = path.read_text(errors="replace")
    root = config.tptp_root()
    for inc in INCLUDE.findall(text):
        p = root / inc
        if p.exists():
            text += "\n" + p.read_text(errors="replace")
    return text


def cnf_clauses(text):
    """Yield (role, body) for each cnf(...) clause, matching parens properly.

    A regex cannot do this: clause bodies contain nested parentheses, so any
    non-greedy `\\)` stops inside the first term and silently truncates it.
    """
    for m in re.finditer(r"cnf\s*\(", text):
        i, depth = m.end(), 1
        while i < len(text) and depth:
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
            i += 1
        parts = text[m.end():i - 1].split(",", 2)
        if len(parts) == 3:
            yield parts[1].strip(), parts[2].strip()


def equations(path: Path, roles=("axiom", "hypothesis")):
    """Unit equation strings for the given clause roles, includes resolved."""
    out = []
    for role, body in cnf_clauses(read_with_includes(path)):
        if role not in roles:
            continue
        body = re.sub(r"\s+", " ", body).strip()
        while body.startswith("(") and body.endswith(")"):
            body = body[1:-1].strip()
        # unit equations only: disjunctions and negations are not UEQ material
        if "!=" in body or "=" not in body or "|" in body or "~" in body:
            continue
        out.append(body)
    return out


def problem_symbols(path: Path) -> set:
    """(name, arity) of every function/constant occurring in the problem."""
    syms = set()
    for eq in equations(path, roles=("axiom", "hypothesis", "negated_conjecture")):
        for side in eq.split("=", 1):
            t = safe_term(side.strip())
            if t is not None:
                symbols(t, syms)
    return syms


def axiom_sets(path: Path) -> list:
    """Per-axiom sets of alpha-normalised subtrees, for `terms.similarity`."""
    sets = []
    for eq in equations(path):
        lhs, rhs = eq.split("=", 1)
        s = set()
        for side in (lhs, rhs):
            t = safe_term(side.strip())
            if t is not None:
                subtrees(alpha(t), s)
        if s:
            sets.append(s)
    return sets


def ueq_scan(problems_dir: Path | None = None):
    """Yield (name, domain, status, rating) for every UEQ problem on disk.

    Reads each problem's own `% SPC :` header rather than TPTP's tptp2T tool, so
    it runs offline and cannot drift from the distribution actually installed.
    """
    root = problems_dir or (config.tptp_root() / "Problems")
    for path in sorted(root.rglob("*.p")):
        status = rating = None
        try:
            with open(path, "r", errors="replace") as f:
                for line in f:
                    if not line.strip():
                        continue
                    if HEADER_END.match(line):
                        break
                    m = SPC_UEQ.match(line.rstrip())
                    if m:
                        status = m.group(1)
                        continue
                    m = RATING.match(line)
                    if m:
                        rating = float(m.group(1))
        except OSError:                                           # noqa: BLE001
            continue
        if status:
            yield path.stem, path.parent.name, status, rating
