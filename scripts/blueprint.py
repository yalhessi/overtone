#!/usr/bin/env python3
"""Draw a sketch's dependency graph with its current proof status.

    ./scripts/blueprint.py --out docs/img/rng_dag.svg
    ./scripts/blueprint.py --results logs/rng_dag/rng_dag.json --watch

Reads the sketch from a module that defines either a `SKETCH` (an
`agent.dag.Sketch`) or a `DAG` dict of `name -> (lhs, rhs, parents)`, and the
statuses from whatever verification results exist so far. Safe to run against a
live run -- unfinished nodes simply show as pending, so the picture fills in.
"""
import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from overtone import config
from overtone.agent import blueprint
from overtone.agent.dag import Sketch


def load_sketch(path: Path) -> Sketch:
    spec = importlib.util.spec_from_file_location("_sketch", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if hasattr(mod, "SKETCH"):
        return mod.SKETCH
    if hasattr(mod, "DAG"):
        return Sketch(mod.DAG)
    sys.exit(f"{path} defines neither SKETCH nor DAG")


def load_results(path: Path):
    """Verification results, from the run's JSON or from its run directory.

    The JSON only lands when a run finishes, so fall back to the artifacts a run
    leaves as it goes: a `<node>.<direction>.p` per attempt and a matching
    `.out` per success. That is enough for status, which is what a blueprint
    shows, and it means the picture fills in live.
    """
    if path and path.exists():
        data = json.loads(path.read_text())
        return data.get("results", data) if isinstance(data, dict) else data
    outdir = path.parent if path else None
    if not outdir or not outdir.is_dir():
        return []
    results = []
    for attempt in sorted(outdir.glob("*.p")):
        node, _, direction = attempt.stem.rpartition(".")
        if not node:
            continue
        proof = attempt.with_suffix(".out")
        results.append({"node": node, "direction": f"--{direction}",
                        "proved": proof.exists(), "cpu": None,
                        "n_support": 0, "result": "?"})
    return results


def load_details(sketch, outdir: Path, results):
    """Per-node statement, goal clause as twee saw it, and the proof it found.

    `proofs.proof_section` is what makes this tractable: assoc_add_1's run file
    is 655 KB of search trace and 15 KB of proof, and only the proof is worth
    putting on a page.
    """
    from overtone import proofs
    details = {}
    for name in sketch.nodes:
        runs = sorted((r for r in results if r["node"] == name),
                      key=lambda r: r["direction"])
        proof, goal = "", ""
        best = min((r for r in runs if r["proved"]),
                   key=lambda r: r["cpu"] if r["cpu"] is not None else 0,
                   default=None)
        if best:
            out = outdir / f"{name}.{best['direction'][2:]}.out"
            if out.exists():
                text = out.read_text(errors="replace")
                proof = proofs.proof_section(text)
                for line in text.splitlines():
                    if line.strip().startswith("Goal 1"):
                        goal = line.strip()
                        break
        details[name] = {"runs": runs, "proof": proof, "goal": goal}
    return details


ANNOT = Path(__file__).resolve().parents[1] / "data" / "lists" / "tptp_nodes.json"


def load_annot(path: Path):
    """Which nodes are TPTP problems in their own right, with ratings.

    A node carrying a problem name is a benchmark someone else has to solve, not
    an internal step -- worth seeing on the graph, because it is what makes a
    sketch checkable against the outside world.
    """
    return json.loads(path.read_text()) if path.exists() else {}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sketch", type=Path,
                    default=config.ROOT / "scripts" / "rng_dag.py")
    # `agent.dag.verify` writes dag.json. The old hand-rolled walk wrote
    # rng_dag.json, and pointing here at that stale name silently rendered a
    # blueprint from the previous run's results.
    ap.add_argument("--results", type=Path,
                    default=config.LOGS / "rng_dag" / "dag.json")
    ap.add_argument("--out", type=Path,
                    default=config.ROOT / "docs" / "img" / "rng_dag.svg")
    ap.add_argument("--title", default="Alternative-ring sketch")
    ap.add_argument("--engine", choices=("auto", "dot", "builtin"), default="auto")
    ap.add_argument("--annot", type=Path, default=ANNOT,
                    help="JSON of {node: {tptp: [...], note: str}}")
    ap.add_argument("--html", type=Path, nargs="?",
                    const=config.ROOT / "docs" / "img" / "rng_dag.html",
                    help="also write an interactive page: hover traces "
                         "dependencies, click opens the statement and proof")
    ap.add_argument("--watch", type=int, metavar="SECONDS", nargs="?", const=60,
                    help="redraw every SECONDS while a run is in flight")
    a = ap.parse_args()

    sketch = load_sketch(a.sketch)
    while True:
        results = load_results(a.results)
        st = blueprint.statuses(sketch, results)
        done = sum(1 for v in st.values() if v["status"].startswith("proved"))
        sub = (f"{done}/{len(sketch.nodes)} proved · "
               + " · ".join(f"{k} {sum(1 for v in st.values() if v['status'] == k)}"
                            for k in blueprint.STATUS_ORDER
                            if any(v["status"] == k for v in st.values())))
        annot = load_annot(a.annot)
        out = blueprint.render(sketch, a.out, results, title=a.title,
                               subtitle=sub, engine=a.engine, annot=annot)
        print(f"{out}  ({sub})", flush=True)
        if a.html:
            details = load_details(sketch, a.results.parent, results)
            a.html.parent.mkdir(parents=True, exist_ok=True)
            a.html.write_text(blueprint.to_html(sketch, results, details,
                                                title=a.title, subtitle=sub,
                                                annot=annot))
            print(f"{a.html}", flush=True)
        if not a.watch or done == len(sketch.nodes):
            return
        time.sleep(a.watch)


if __name__ == "__main__":
    main()
