"""Sketch transfer v0: donor-proof hints for a problem the baseline cannot solve.

One iteration of docs/SKETCH_LOOP.md with no LLM in it. The sketch is the proof
of the most axiom-similar *solved* sibling; the hints are that proof's
rewrite-chain terms, adapted to the target signature.

Writes an example bundle per problem:

    examples/sketch_loop/<PROBLEM>/
      <PROBLEM>.p          the original, copied from TPTP
      sketch.md            donor, similarity, extraction and filtering record
      hints.tptp           the surviving hint clauses
      <PROBLEM>_hinted.p   original + hints, what twee actually runs
      result.json          baseline vs hinted outcome (after `run_example`)
"""
import json
import re
from pathlib import Path

from overtone import config, proofs, runner
from overtone.agent import donors, hints as hintlib
from overtone.problems import problem_path, problem_symbols
from overtone.runner import BASE_FLAGS, as_cnf_hint

EXAMPLES = config.ROOT / "examples" / "sketch_loop"
DIRECTIONS = ("--flatten-goal", "--no-flatten-goal")


def make_example(problem, exclude=(), outdir=None, cap=hintlib.MAX_HINTS,
                 rank_by="frequency"):
    """Build the bundle for `problem`. Returns a summary dict, or None."""
    outdir = Path(outdir or EXAMPLES)
    domain = re.match(r"[A-Z]+", problem).group(0)
    sim, donor, proof_file = donors.find_donor(problem, domain, exclude)
    if donor is None:
        print(f"  {problem}: no donor with a saved proof in {domain}")
        return None
    target_syms = problem_symbols(problem_path(problem))
    counts = proofs.chain_terms(proof_file.read_text(errors="replace"))
    kept, dropped = hintlib.build_hints(counts, target_syms, cap=cap,
                                        rank_by=rank_by)
    if len(kept) < 3:
        print(f"  {problem}: only {len(kept)} usable hints from {donor}, skipping")
        return None

    d = outdir / problem
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{problem}.p").write_text(problem_path(problem).read_text())
    (d / "hints.tptp").write_text(
        "".join(as_cnf_hint(h, i) for i, (h, _, _) in enumerate(kept, 1)))
    runner.write_problem(problem, d / f"{problem}_hinted.p",
                         hints=[h for h, _, _ in kept])

    lines = [
        f"# Sketch: {problem}",
        "",
        f"Target `{problem}` resisted the baseline screen in both goal",
        "directions. The sketch is the proof of its most axiom-similar solved",
        "sibling; hints are the intermediate terms of that proof's rewrite",
        "chains (Twitch's extraction), adapted to the target signature.",
        "",
        f"- donor: `{donor}` (axiom similarity **{sim:.3f}**)",
        f"- donor proof: `{proof_file.relative_to(config.ROOT)}`",
        f"- extracted {sum(counts.values())} term occurrences"
        f" ({len(counts)} distinct)",
        f"- dropped {dropped} (absent non-nullary symbols, unparseable,"
        " or contentless)",
        f"- kept {len(kept)} (cap {cap}; donor-only constants"
        " variabilised to Wn)",
        f"- baseline: {json.dumps(donors.baseline(problem))}",
        "",
        "| # | hint (adapted) | donor occurrences | donor term |",
        "|---|---|---|---|",
    ]
    for i, (h, n, raw) in enumerate(kept, 1):
        lines.append(f"| {i} | `{h}` | {n} | {'' if h == raw else f'`{raw}`'} |")
    (d / "sketch.md").write_text("\n".join(lines) + "\n")
    print(f"  {problem}: donor {donor} sim {sim:.3f}, "
          f"{len(kept)} hints ({dropped} dropped)")
    return {"problem": problem, "donor": donor, "similarity": round(sim, 3),
            "n_hints": len(kept)}


def run_example(problem, budget=1000, outdir=None):
    """Run the hinted problem in both directions, stopping at the first proof."""
    d = Path(outdir or EXAMPLES) / problem
    hinted = d / f"{problem}_hinted.p"
    results = {"problem": problem, "budget": budget,
               "baseline": donors.baseline(problem), "hinted": {}}
    for direction in DIRECTIONS:
        r = runner.run(hinted, [*BASE_FLAGS, *hintlib.HINT_FLAGS, direction],
                       budget, problem=problem)
        results["hinted"][direction] = {"result": r.status, "proved": r.proved,
                                        "cpu": round(r.cpu, 1)}
        tag = direction.replace("--", "")
        (d / f"{problem}_hinted.{tag}.out").write_text(r.output)
        print(f"  {problem} {direction}: {r.status} {r.cpu:.1f}s", flush=True)
        if r.proved:
            break                     # one proof is enough; save the budget
    (d / "result.json").write_text(json.dumps(results, indent=2) + "\n")
    return results


def ablate(problem, budget=1000, outdir=None, threshold=3, direction=None):
    """Split the hint set by specificity and run each arm against the whole.

    Regenerates the comparison in docs/FINDINGS.md: on MVA005-1 the generic
    hints alone could not prove the conjecture, the specific ones alone did in
    852.9s, and the full set in 546.8s -- so the transferred structure is the
    mechanism and the generic hints only accelerate.
    """
    d = Path(outdir or EXAMPLES) / problem
    terms = re.findall(r"\$hint\(\s*(.*?)\s*\)\)\.",
                       (d / "hints.tptp").read_text(), re.S)
    specific, generic = hintlib.split_by_specificity(terms, threshold)
    print(f"  {problem}: {len(terms)} hints -> {len(specific)} specific, "
          f"{len(generic)} generic (threshold {threshold} symbols)")

    abl = d / "ablation"
    abl.mkdir(parents=True, exist_ok=True)
    out = {"problem": problem, "budget": budget, "threshold": threshold,
           "baseline": donors.baseline(problem), "arms": {}}
    dirs = [direction] if direction else list(DIRECTIONS)
    for name, hs in (("specific", specific), ("generic", generic), ("full", terms)):
        if not hs:
            continue
        path = runner.write_problem(problem, abl / f"{problem}_{name}.p", hints=hs)
        (abl / f"hints_{name}.tptp").write_text(
            "".join(as_cnf_hint(h, i) for i, h in enumerate(hs, 1)))
        for direc in dirs:
            r = runner.run(path, [*BASE_FLAGS, *hintlib.HINT_FLAGS, direc],
                           budget, problem=problem)
            out["arms"].setdefault(name, {})[direc] = {
                "result": r.status, "proved": r.proved, "cpu": round(r.cpu, 1),
                "n_hints": len(hs)}
            (abl / f"{name}.{direc.replace('--', '')}.out").write_text(r.output)
            print(f"    {name:<9} {direc:<18} {r.status:<16} {r.cpu:7.1f}s",
                  flush=True)
            if r.proved:
                break
    (abl / "ablation.json").write_text(json.dumps(out, indent=2) + "\n")
    return out
