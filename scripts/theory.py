#!/usr/bin/env python3
"""Pipeline B -- derive a lemma library once, then attack a family with it.

    ./scripts/theory.py --sketch scripts/rng_dag.py --host RNG029-5 \
        --targets data/lists/rng_moufang.txt
    ./scripts/theory.py --sketch scripts/rng_dag.py --check-only

Reports two numbers and never adds them: what the library cost to derive, and
what each target cost given it. Blending those is what made the RNG result
unattributable.

Containment is asserted per target first. A lemma proved from the host's axioms
is a theorem of a target's theory only if that theory is at least as strong;
RNG027-10 and RNG029-10 drop three and four of RNG029-5's axioms, and skipping
this check is how they were briefly claimed and then withdrawn. `--check-only`
runs that audit alone, with no proving.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# also this directory: these CLIs import a sibling script, which only
# resolves implicitly when run directly, not when imported.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from overtone import config, problems
from overtone.agent.pipeline import Budget, run_theory
from prove import load_sketch


def load_budgets(path: Path):
    """Per-node budgets a sketch declares, if it is a module that declares any.

    `right_moufang` needs 192.6s against a 60s default. Dropping this silently
    truncated the library to 24/29 and made a reproduction run look like a
    negative result.
    """
    if path.suffix == ".json":
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location("_sketch_budgets", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, "TIER_BUDGET", None) or None


def read_targets(spec, sketch_path):
    """Targets from a file, a comma list, or the sketch module's TARGETS."""
    if spec and Path(spec).exists():
        return [l.strip() for l in Path(spec).read_text().split() if l.strip()]
    if spec:
        return [t.strip() for t in spec.split(",") if t.strip()]
    import importlib.util
    spec_ = importlib.util.spec_from_file_location("_sketch", sketch_path)
    mod = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(mod)
    if hasattr(mod, "TARGETS"):
        return list(mod.TARGETS)
    sys.exit("no --targets given and the sketch defines no TARGETS")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sketch", type=Path, required=True)
    ap.add_argument("--host", default="RNG029-5",
                    help="problem whose axioms the library is proved from")
    ap.add_argument("--targets", help="file, comma list, or the sketch's TARGETS")
    ap.add_argument("--node-budget", type=int, default=60,
                    help="default per-node budget; a sketch's own "
                         "TIER_BUDGET overrides it per node")
    ap.add_argument("--final-budget", type=int, default=300)
    ap.add_argument("--slow", type=int, default=30)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--outdir", type=Path)
    ap.add_argument("--rerun", action="store_true",
                    help="ignore the ledger and re-run every "
                         "invocation, even ones already recorded")
    ap.add_argument("--binary")
    ap.add_argument("--check-only", action="store_true",
                    help="audit axiom containment per target and stop")
    a = ap.parse_args()

    try:
        sketch = load_sketch(a.sketch)
    except (ValueError, FileNotFoundError) as e:
        sys.exit(str(e))
    targets = read_targets(a.targets, a.sketch)

    if a.check_only:
        print(f"axiom containment against {a.host}:")
        bad = 0
        for t in targets:
            ok, missing = problems.contains_axioms(t, a.host)
            bad += not ok
            print(f"  {t:<12} {'ok' if ok else f'MISSING {len(missing)} axioms'}")
        print(f"\n  {len(targets) - bad}/{len(targets)} may use this library")
        return

    outdir = a.outdir or (config.LOGS / "theory" / a.sketch.stem)
    budget = Budget(node=a.node_budget, slow=a.slow, final=a.final_budget,
                    workers=a.workers)
    try:
        binary = a.binary or config.twee_path(deterministic=True)
    except RuntimeError as e:
        sys.exit(str(e))

    print(f"library: {len(sketch.nodes)} nodes on {a.host}; "
          f"{len(targets)} targets\n", flush=True)
    out = run_theory(sketch, targets, host=a.host, outdir=outdir, budget=budget,
                     budgets=load_budgets(a.sketch), binary=binary,
                     reuse=not a.rerun)

    lib = out["library"]
    print(f"\n  library      {lib['n_proved']}/{lib['n_nodes']} nodes, "
          f"{lib['cost']['cpu']:.1f}s CPU over {lib['cost']['n_runs']} runs")
    marg = [r["marginal"]["cpu"] for r in out["targets"].values() if r["marginal"]]
    if marg:
        print(f"  marginal     {min(marg):.1f}-{max(marg):.1f}s CPU per target")
    print(f"  proved       {out['n_proved']}/{out['n_targets']}")
    skipped = [t for t, r in out["targets"].items() if not r["contained"]]
    if skipped:
        print(f"  skipped      {skipped} (axiom containment)")
    print(f"  -> {outdir}/theory.json")


if __name__ == "__main__":
    main()
