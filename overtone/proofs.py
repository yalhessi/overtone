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

