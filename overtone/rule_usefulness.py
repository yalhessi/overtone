"""Which rules does twee derive, and which ever get used in the proof it finds?

twee --print-score logs every derived rule as "(score) N. lhs -> rhs". The proof
it eventually prints references those same numbers ("by lemma N", "Lemma N:").
The difference is wasted work, and the question is whether anything cheaply
computable at derivation time separates the two sets.
"""
import re, statistics, sys
from collections import Counter
from pathlib import Path

RULE = re.compile(r'^\((\d+\.?\d*)\)\s+(\d+)\.\s+(.*)$')
USED_REF = re.compile(r'by lemma (\d+)')
LEMMA_HDR = re.compile(r'^Lemma (\d+):')


def analyse(path):
    rules, used = {}, set()
    in_proof = False
    for line in Path(path).read_text(errors="ignore").splitlines():
        if line.startswith("The conjecture is true") or line.startswith("Here is a proof"):
            in_proof = True
        m = RULE.match(line)
        if m and not in_proof:
            score, num, body = float(m.group(1)), int(m.group(2)), m.group(3)
            rules[num] = {"score": score, "len": len(body), "body": body}
        if in_proof:
            for r in USED_REF.findall(line):
                used.add(int(r))
            h = LEMMA_HDR.match(line)
            if h:
                used.add(int(h.group(1)))
    return rules, used


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


if __name__ == "__main__":
    groups = {
        "A0 hinted ROB proofs": sorted(Path("logs/A0_rob_reproduction").glob("*_hinted_output.txt")),
        "rerun base proofs (GRP)": sorted(Path("logs").glob("*rerun_GRP*/*_base_output.txt"))[:400],
        "rerun base proofs (LAT)": sorted(Path("logs").glob("*rerun_LAT*/*_base_output.txt"))[:200],
        "rerun base proofs (COL)": sorted(Path("logs").glob("*rerun_COL*/*_base_output.txt"))[:200],
    }
    for label, paths in groups.items():
        summarise(paths, label)
