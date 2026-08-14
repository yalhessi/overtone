"""Parsing twee's output.

Everything here takes twee stdout (or a file of it) and returns plain data.
Deliberately imports nothing from `overtone.terms`: proof parsing yields term
*strings*, and it is the caller's business whether to parse them. That keeps the
dependency graph acyclic and lets analysis code use one without the other.

The output shapes this understands:

    (21.714287) 1143. meet(X, X) -> X        a derived rule, from --print-score
    Lemma 22: join(X, meet(X, Y)) = X        a lemma in the printed proof
    = { by lemma 22 }                        a proof step citing one
    RESULT: Unsatisfiable (...)              the outcome
    HINT_FIRED 36 meet(rd(...), ...)         from the instrumented build
"""
import re
import statistics
from pathlib import Path

PROVED = ("Unsatisfiable", "Theorem")
SATURATED = ("Satisfiable", "CounterSatisfiable")

RESULT_RE = re.compile(r"^RESULT:\s*(\w+)", re.MULTILINE)
# Permissive counter, kept bit-compatible with the original: `n_rules` is a
# determinism invariant for scripts/variance.py, where a differing count is
# supposed to mean something other than twee changed.
RULE_COUNT_RE = re.compile(r"^\([\d.]+\)\s+\d+\.", re.MULTILINE)
# Richer parse of the same lines. Verified to agree with RULE_COUNT_RE on every
# one of the 316 saved *.out files.
RULE_RE = re.compile(r"^\((\d+\.?\d*)\)\s+(\d+)\.\s+(.*)$")
LEMMA_RE = re.compile(r"^Lemma (\d+): (.+?) = (.+?)\.\s*$")
LEMMA_HDR_RE = re.compile(r"^Lemma (\d+):")
USED_REF_RE = re.compile(r"by lemma (\d+)")
HINT_RE = re.compile(r"^HINT_FIRED (\d+) (.+)$", re.MULTILINE)

PROOF_MARKERS = ("The conjecture is true", "Here is a proof")


def parse_status(text: str, killed: bool = False) -> str:
    """The RESULT line's status.

    twee exits 0 whether or not it found a proof, so the exit code says nothing;
    only `Unsatisfiable`/`Theorem` mean a proof, and `Satisfiable`/
    `CounterSatisfiable` mean it saturated. See docs/FINDINGS.md.
    """
    m = RESULT_RE.search(text)
    if m:
        return m.group(1)
    return "Timeout" if killed else "NoResult"


def count_rule_lines(text: str) -> int:
    return len(RULE_COUNT_RE.findall(text))


def hint_firings(text: str) -> dict:
    """{hint term: times matched}, from the instrumented build only.

    Empty for stock twee. Note firing count is a poor proxy for a hint's value:
    on MVA005-1 the hints that fired 62-82M times were the dispensable ones and
    the hint that fired 36 times carried the proof (docs/FINDINGS.md).
    """
    return {h: int(n) for n, h in HINT_RE.findall(text)}


def lemmas(text: str):
    """(number, lhs, rhs) for each `Lemma N: lhs = rhs.` line, in proof order."""
    out = []
    for line in text.splitlines():
        m = LEMMA_RE.match(line.strip())
        if m:
            out.append((int(m.group(1)), m.group(2).strip(), m.group(3).strip()))
    return out


def proof_section(text: str) -> str:
    """The human-readable proof: axioms used, lemmas, and the goal's chain.

    twee prints the search trace first (one line per derived rule, tens of
    thousands of them) and the proof only at the end, so this is the small,
    interesting fraction -- typically well under a kilobyte where the trace is
    megabytes. Returns "" when the run did not prove anything.
    """
    start = -1
    for marker in PROOF_MARKERS:
        start = text.find(marker)
        if start != -1:
            break
    if start == -1:
        return ""
    end = text.find("RESULT:", start)
    body = text[start:end if end != -1 else None]
    return body.split("\n", 1)[-1].strip("\n")


def chain_terms(text: str):
    """Counter of the intermediate terms of the proof's rewrite chains.

    Each chain alternates a term line with a `= { by ... }` justification; the
    terms are the states the proof passes through, which is what Twitch harvests
    as hints. The `by` test is token-level rather than a substring test, so terms
    containing a symbol with `by` in its name are not silently dropped.
    """
    from collections import Counter
    proof = text.split(PROOF_MARKERS[0], 1)[-1]
    counts = Counter()
    for block in re.findall(r"Proof:(.*?)(?=(?:Lemma\s+\d+|RESULT|Goal|\Z))",
                            proof, re.DOTALL):
        for line in block.strip().splitlines():
            line = line.strip().replace("(peak)", "").strip()
            if not line or "=" in line or "by" in line.split()[:2]:
                continue
            counts[line] += 1
    return counts


def derived_rules(text: str):
    """Rules twee derived before the proof section: {number: {score, len, body}}."""
    rules = {}
    in_proof = False
    for line in text.splitlines():
        if line.startswith(PROOF_MARKERS):
            in_proof = True
        if in_proof:
            continue
        m = RULE_RE.match(line)
        if m:
            rules[int(m.group(2))] = {"score": float(m.group(1)),
                                      "len": len(m.group(3)),
                                      "body": m.group(3)}
    return rules


GOAL_RE = re.compile(r"^\s*Goal \d+ \([^)]*\):\s*(.+?)\s*=\s*(.+?)\.\s*$",
                     re.MULTILINE)
FLAT_RE = re.compile(r"^\s*Axiom \d+ \(flattening\):\s*(\w+)\s*=\s*(.+?)\.\s*$",
                     re.MULTILINE)
NAMED_RE = re.compile(r"^(.*?)\s*->\s*([a-z_]+\d+)$")


def _summands(term: str):
    """Top-level summands of an `add(...)` tree, plus the whole term."""
    out, stack = [], [term.strip()]
    while stack:
        t = stack.pop()
        out.append(t)
        if not t.startswith("add("):
            continue
        depth, split = 0, None
        for i, c in enumerate(t[4:-1], start=4):
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            elif c == "," and depth == 0:
                split = i
                break
        if split is not None:
            stack += [t[4:split].strip(), t[split + 1:-1].strip()]
    return out


def goal_contact(text: str) -> dict:
    """How much of the search touches each side of the goal, and both at once.

    Counting *source-level term shapes* in the output does not work and produced
    a wrong diagnosis that cost a full RNG033-8 iteration. `--flatten-goal`
    introduces a constant for each goal subterm and rewrites matching terms to it
    on sight, so the shape stops appearing literally; and twee names ground
    subterms in either mode. A grep for the shape therefore measures the naming
    convention, not the search.

    So resolve the names first -- flattening axioms and `<term> -> <name>` rules
    -- and count rules mentioning each side's terms or any alias of them.

    `both` is a veto, not an objective. Only a rule touching both sides can close
    the goal, and it is the one quantity RNG033-8's refinement moved in the wrong
    direction (162 -> 102) while every other count rose -- so a fall is evidence
    the edit hurt. A rise is not evidence it helped: on that same node, supplying
    no parents at all scores 371, the highest measured, and did not prove the goal
    at 300s.
    Maximising it drives a sketch toward the one configuration known to fail.
    """
    g = GOAL_RE.search(text)
    if not g:
        return {"lhs": 0, "rhs": 0, "both": 0, "rules": 0, "goal": None}
    sides = [_summands(g.group(1)), _summands(g.group(2))]
    rules = derived_rules(text)

    alias = {n: t for n, t in FLAT_RE.findall(text)}
    for r in rules.values():
        m = NAMED_RE.match(r["body"])
        if m and m.group(2) not in alias:
            alias[m.group(2)] = m.group(1)

    def expand(t, depth=8):
        while depth:
            nxt = re.sub(r"\b([a-z_]+\d+)\b",
                         lambda m: alias.get(m.group(1), m.group(1)), t)
            nxt = re.sub(r"\s+", "", nxt)
            if nxt == re.sub(r"\s+", "", t):
                return nxt
            t, depth = nxt, depth - 1
        return re.sub(r"\s+", "", t)

    tokens = []
    for side in sides:
        flat = {re.sub(r"\s+", "", s) for s in side}
        names = {n for n, t in alias.items() if expand(t) in flat}
        tokens.append(names | flat)

    def touches(body, toks):
        # A bare name needs word boundaries so `add2` does not match `add23`; a
        # compound term ends in `)` and `\b` after a paren never matches, so it
        # is a plain containment test. Without the split, the no-flatten runs --
        # where every goal term is compound -- silently scored zero.
        b = re.sub(r"\s+", "", body)
        return any(re.search(rf"\b{re.escape(t)}\b", b) if t.isidentifier()
                   else t in b for t in toks)

    bodies = [r["body"] for r in rules.values()]
    hit = [[touches(b, t) for b in bodies] for t in tokens]
    n_lhs, n_rhs = sum(hit[0]), sum(hit[1])
    return {"lhs": n_lhs, "rhs": n_rhs,
            "both": sum(a and b for a, b in zip(*hit)),
            "rules": len(bodies), "goal": (g.group(1), g.group(2)),
            # `--no-flatten-goal` never puts the goal into the rewrite system, so
            # no derived rule mentions it and every count here is 0 by
            # construction. Say so, rather than let a caller read that as "the
            # search is not reaching the goal" -- the two are indistinguishable
            # from the numbers alone.
            "goal_directed": bool(n_lhs or n_rhs)}


def used_lemma_refs(text: str) -> set:
    """Rule numbers the printed proof references."""
    used = set()
    in_proof = False
    for line in text.splitlines():
        if line.startswith(PROOF_MARKERS):
            in_proof = True
        if not in_proof:
            continue
        used.update(int(r) for r in USED_REF_RE.findall(line))
        h = LEMMA_HDR_RE.match(line)
        if h:
            used.add(int(h.group(1)))
    return used


def used_supports(text: str, prefix: str = "parent", count=None):
    """Which supplied support equations the printed proof actually used.

    `dag._job` writes a node's parents into the problem as `cnf(parent_1, axiom,
    ...)`, numbered from 1 in the order they were supplied, and twee echoes that
    name wherever it cites one: `Axiom 3 (parent_1): ...` in the proof's axiom
    listing and `= { by axiom 3 (parent_1) }` in a rewrite chain. Both forms
    parenthesise the name, which is what this matches -- a bare `parent_1`
    substring would also hit a term symbol of that name.

    Returns the 1-based indices, or **None** when there is no proof section at
    all. None and the empty set are different answers and the caller must not
    conflate them: None is "this run did not prove, so nothing can be
    attributed", the empty set is "it proved and used none of them", which is
    the interesting case. 164 of 307 parents supplied to the 154 proved runs on
    record were in that second category.

    Only the proof section is read. twee lists every axiom of the problem in its
    preamble, so scanning the whole output would report every parent as used.

    `count` is how many were supplied; with it, indices outside 1..count are
    dropped rather than returned as names the caller cannot resolve.
    """
    section = proof_section(text)
    if not section:
        return None
    rx = re.compile(r"\(" + re.escape(prefix) + r"_(\d+)\)")
    used = {int(n) for n in rx.findall(section)}
    if count is not None:
        used = {i for i in used if 1 <= i <= count}
    return used


def analyse(path):
    """(derived rules, used rule numbers) for a saved twee output file."""
    text = Path(path).read_text(errors="ignore")
    return derived_rules(text), used_lemma_refs(text)


def summarise(paths, label):
    tot_d = tot_u = 0
    used_scores, unused_scores = [], []
    used_pos, unused_pos = [], []          # derivation order, as a fraction of the run
    per_problem = []
    for p in paths:
        rules, used = analyse(p)
        if not rules or not used:
            continue
        used = {u for u in used if u in rules}
        if not used:
            continue
        n = len(rules)
        tot_d += n; tot_u += len(used)
        mx = max(rules)
        for num, r in rules.items():
            (used_scores if num in used else unused_scores).append(r["score"])
            (used_pos if num in used else unused_pos).append(num / mx)
        per_problem.append((Path(p).name, n, len(used), 100 * len(used) / n))

    if not per_problem:
        print(f"{label}: no parseable proofs"); return
    print(f"\n=== {label}: {len(per_problem)} proofs ===")
    print(f"rules derived: {tot_d:,}   used in proof: {tot_u:,}   "
          f"WASTE: {100*(1-tot_u/tot_d):.1f}%")
    q = lambda xs, f: statistics.quantiles(xs, n=100)[f-1] if len(xs) > 2 else float('nan')
    print(f"\nscore of USED rules  : median {statistics.median(used_scores):6.1f}  "
          f"p90 {q(used_scores,90):6.1f}  p99 {q(used_scores,99):6.1f}  max {max(used_scores):6.1f}")
    print(f"score of UNUSED rules: median {statistics.median(unused_scores):6.1f}  "
          f"p90 {q(unused_scores,90):6.1f}  p99 {q(unused_scores,99):6.1f}  max {max(unused_scores):6.1f}")
    print(f"derivation position (0=first,1=last): used median {statistics.median(used_pos):.2f}, "
          f"unused median {statistics.median(unused_pos):.2f}")

    # If we capped the score, how much work is saved and how many needed rules are lost?
    print(f"\n{'score cap':>10s} {'rules pruned':>13s} {'used rules lost':>16s}")
    allc = used_scores + unused_scores
    for cap in (q(used_scores, 90), q(used_scores, 99), max(used_scores)):
        pruned = sum(1 for s in allc if s > cap)
        lost = sum(1 for s in used_scores if s > cap)
        print(f"{cap:10.1f} {100*pruned/len(allc):12.1f}% {lost:9d} ({100*lost/len(used_scores):.2f}%)")

    worst = sorted(per_problem, key=lambda x: x[3])[:5]
    print("\nleast efficient proofs (derived -> used):")
    for name, n, u, pct in worst:
        print(f"  {name[:48]:48s} {n:6,} -> {u:4} ({pct:.2f}%)")

