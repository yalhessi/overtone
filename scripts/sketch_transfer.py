#!/usr/bin/env python3
"""Sketch transfer v0: donor-proof hints for resisted problems.

One iteration of the sketch loop in docs/SKETCH_LOOP.md, with no LLM in it:
the sketch is the proof of the most axiom-similar *solved* sibling problem
(from the baseline screen), and the hints are the intermediate terms of that
proof's rewrite chains -- the same extraction Twitch's veroff_hints method uses.

For each target it writes an example directory:

    examples/sketch_loop/<PROBLEM>/
      <PROBLEM>.p          the original problem, copied from TPTP
      sketch.md            donor, similarity, extraction and filtering record
      hints.tptp           the surviving hint clauses
      <PROBLEM>_hinted.p   original + hints, what twee actually runs
      result.json          baseline vs hinted outcome (after --run)

Guardrails from docs/FINDINGS.md are enforced, not advisory: hint sets are
capped in the 9-33 range where Twitch's wins live, --hint-skel-factor is 0.5
(factor 0 is pathological), hints whose symbols are absent from the target are
dropped or variabilised (inert-hint pitfall), and every hinted run is paired
with the recorded screen baseline.
"""
import argparse
import collections
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from overtone import twee                                        # noqa: E402
from overtone.terms import (VAR, safe_term, term, unparse, alpha, fresh_vars,   # noqa: E402
                            symbols, subtrees, similarity, merged)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "sketch_loop"
PROOFS = ROOT / "logs" / "screen" / "proofs"
HINT_FLAGS = ["--hint-skel-factor 0.5", "--hint-skel-cost 0"]
MAX_HINTS = 25          # stay inside the measured 9-33 sweet spot
# ------------------------------------------------------------------ problems

def read_with_includes(path: Path) -> str:
    text = path.read_text(errors="replace")
    for inc in re.findall(r"include\(\s*'([^']+)'\s*\)", text):
        p = Path(twee.env("TPTP_ROOT")) / inc
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
        inner = text[m.end():i - 1]
        parts = inner.split(",", 2)
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


def problem_symbols(path: Path):
    syms = set()
    for eq in equations(path, roles=("axiom", "hypothesis", "negated_conjecture")):
        for side in eq.split("=", 1):
            t = safe_term(side.strip())
            if t is not None:
                symbols(t, syms)
    return syms


def axiom_sets(path: Path):
    sets = []
    for eq in equations(path):
        lhs, rhs = eq.split("=", 1)
        s = set()
        for side in (lhs, rhs):
            t = safe_term(side.strip())
            if t is not None:
                subtrees(alpha(t, {}, fresh_vars()), s)
        if s:
            sets.append(s)
    return sets


# ---------------------------------------------------------------- extraction

def donor_terms(out_path: Path):
    """Intermediate terms of the proof's rewrite chains, Twitch-style.

    In twee's proof section each chain line is either a term or a
    `= { by ... }` justification; the terms are the states the proof passes
    through, which is exactly what Twitch harvests as hints.
    """
    text = out_path.read_text(errors="replace")
    proof = text.split("The conjecture is true", 1)[-1]
    counts = collections.Counter()
    for block in re.findall(r"Proof:(.*?)(?=(?:Lemma\s+\d+|RESULT|Goal|\Z))",
                            proof, re.DOTALL):
        for line in block.strip().splitlines():
            line = line.strip().replace("(peak)", "").strip()
            if not line or "=" in line or "by" in line.split()[:2]:
                continue
            counts[line] += 1
    return counts


def adapt(t, target_syms, subst):
    """Fit a donor term to the target signature.

    Donor constants absent from the target (twee's flattening constants f2...,
    goal constants) become fresh variables -- FINDINGS: hints with absent
    symbols are inert, and variabilisation is the fix. Terms using absent
    *non-nullary* functions cannot be fixed this way; return None to drop.
    """
    if isinstance(t, str):
        if VAR.match(t) or (t, 0) in target_syms:
            return t
        if t not in subst:
            subst[t] = f"W{len(subst) + 1}"
        return subst[t]
    if (t[0], len(t) - 1) not in target_syms:
        return None
    args = [adapt(a, target_syms, subst) for a in t[1:]]
    if any(a is None for a in args):
        return None
    return (t[0], *args)


def build_hints(counts, target_syms):
    """Filter, adapt and rank donor terms into a hint list <= MAX_HINTS."""
    kept, dropped, seen = [], 0, set()
    for raw, n in counts.most_common():
        t = safe_term(raw)
        if t is None:
            dropped += 1
            continue
        if isinstance(t, str):        # bare variable or constant: no content
            dropped += 1
            continue
        adapted = adapt(t, target_syms, {})
        if adapted is None:
            dropped += 1
            continue
        key = alpha(adapted, {}, fresh_vars())
        if key in seen:
            continue
        seen.add(key)
        kept.append((unparse(adapted), n, raw))
        if len(kept) >= MAX_HINTS:
            break
    return kept, dropped


# ------------------------------------------------------------------ pipeline

def screen_baseline(problem):
    out = {}
    for f in (ROOT / "logs" / "screen" / "results.jsonl",
              ROOT / "logs" / "screen4000" / "results.jsonl"):
        if not f.exists():
            continue
        for line in f.read_text().splitlines():
            r = json.loads(line)
            if r["problem"] == problem:
                out[f"{r['budget']}s {r['direction']}"] = r["result"]
    return out


def find_donor(problem, domain, exclude, shortlist=5):
    """Best solved same-domain sibling that has a saved proof.

    Two stages: a cheap whole-problem Jaccard shortlists candidates, then
    Twitch's per-axiom similarity ranks the shortlist. The exact version is
    quadratic in axioms x subtrees and unusably slow on LCL-10 encodings.
    """
    target_sets = axiom_sets(twee.problem_path(problem))
    target_merged = merged(target_sets)
    coarse = []
    seen = set()
    for out in sorted(PROOFS.glob(f"{domain}*.out")):
        donor = out.stem.removesuffix("_no-flatten-goal").removesuffix("_flatten-goal")
        if donor == problem or donor in exclude or donor in seen:
            continue
        seen.add(donor)
        dsets = axiom_sets(twee.problem_path(donor))
        dm = merged(dsets)
        j = len(target_merged & dm) / len(target_merged | dm) if dm else 0.0
        coarse.append((j, donor, out, dsets))
    coarse.sort(key=lambda x: -x[0])
    best = (0.0, None, None)
    for _, donor, out, dsets in coarse[:shortlist]:
        sim = similarity(target_sets, dsets)
        if sim > best[0]:
            best = (sim, donor, out)
    return best


def make_example(problem, exclude):
    domain = re.match(r"[A-Z]+", problem).group(0)
    sim, donor, proof_file = find_donor(problem, domain, exclude)
    if donor is None:
        print(f"  {problem}: no donor with a saved proof in {domain}")
        return None
    target_syms = problem_symbols(twee.problem_path(problem))
    counts = donor_terms(proof_file)
    hints, dropped = build_hints(counts, target_syms)
    if len(hints) < 3:
        print(f"  {problem}: only {len(hints)} usable hints from {donor}, skipping")
        return None

    d = EXAMPLES / problem
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{problem}.p").write_text(twee.problem_path(problem).read_text())
    (d / "hints.tptp").write_text(
        "".join(twee.as_cnf_hint(h, i) for i, (h, _, _) in enumerate(hints, 1)))
    twee.build_input(problem, [h for h, _, _ in hints],
                     d / f"{problem}_hinted.p")

    lines = [
        f"# Sketch: {problem}",
        "",
        f"Target `{problem}` resisted the baseline screen in both goal",
        "directions. The sketch is the proof of its most axiom-similar solved",
        "sibling; hints are the intermediate terms of that proof's rewrite",
        "chains (Twitch's extraction), adapted to the target signature.",
        "",
        f"- donor: `{donor}` (axiom similarity **{sim:.3f}**)",
        f"- donor proof: `{proof_file.relative_to(ROOT)}`",
        f"- extracted {sum(counts.values())} term occurrences"
        f" ({len(counts)} distinct)",
        f"- dropped {dropped} (absent non-nullary symbols, unparseable,"
        " or contentless)",
        f"- kept {len(hints)} (cap {MAX_HINTS}; donor-only constants"
        " variabilised to Wn)",
        f"- baseline: {json.dumps(screen_baseline(problem))}",
        "",
        "| # | hint (adapted) | donor occurrences | donor term |",
        "|---|---|---|---|",
    ]
    for i, (h, n, raw) in enumerate(hints, 1):
        note = "" if h == raw else f"`{raw}`"
        lines.append(f"| {i} | `{h}` | {n} | {note} |")
    (d / "sketch.md").write_text("\n".join(lines) + "\n")
    print(f"  {problem}: donor {donor} sim {sim:.3f}, "
          f"{len(hints)} hints ({dropped} dropped)")
    return {"problem": problem, "donor": donor, "similarity": round(sim, 3),
            "n_hints": len(hints)}


def run_example(problem, budget):
    d = EXAMPLES / problem
    hinted = d / f"{problem}_hinted.p"
    results = {"problem": problem, "budget": budget,
               "baseline": screen_baseline(problem), "hinted": {}}
    for direction in ("--flatten-goal", "--no-flatten-goal"):
        r = twee.run(hinted, twee.BASE_FLAGS + HINT_FLAGS + [direction], budget)
        results["hinted"][direction] = {
            "result": r["result"], "proved": r["proved"],
            "cpu": round(r["cpu"], 1)}
        tag = direction.replace("--", "")
        (d / f"{problem}_hinted.{tag}.out").write_text(r["output"])
        print(f"  {problem} {direction}: {r['result']} {r['cpu']:.1f}s",
              flush=True)
        if r["proved"]:
            break                     # one proof is enough; save the budget
    (d / "result.json").write_text(json.dumps(results, indent=2) + "\n")
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("problems", nargs="*", help="target problem names")
    ap.add_argument("--exclude", type=Path,
                    help="file of problems never to use as donors or targets")
    ap.add_argument("--run", action="store_true", help="run the hinted jobs")
    ap.add_argument("--budget", type=int, default=1000)
    a = ap.parse_args()

    exclude = set()
    if a.exclude and a.exclude.exists():
        exclude = {l.strip() for l in a.exclude.read_text().splitlines()
                   if l.strip()}

    made = []
    for p in a.problems:
        info = make_example(p, exclude)
        if info:
            made.append(info)
    if a.run:
        for info in made:
            run_example(info["problem"], a.budget)


if __name__ == "__main__":
    main()
