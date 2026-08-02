#!/usr/bin/env python3
"""Re-run a recorded Twitch success and compare against its recorded time.

`twitch/data/experiments/hard_successes/*.json` stores the winning config, the
exact hint set and the wall time for each hard problem the paper solved. That is
enough to reproduce a run without re-running Stitch, which makes it a direct
check that our twee build, hint encoding and flag set match the authors'.

It records no baselines and no failures (see FINDINGS.md), so --baseline runs the
paired no-hint job that the recorded data is missing.

Two flags are appended by Twitch to every twee invocation and are not in the
stored config -- `--kbo-weight0-unary` and `--print-score` (src/utils.py:22).
Leaving them out changes the search, so they are applied here too.
"""
import argparse
import json
import sys
from pathlib import Path

from overtone import config, runner

ROOT = config.ROOT
SUCCESSES = ROOT / "twitch" / "data" / "experiments" / "hard_successes"


def load_records(problem: str):
    """Every recorded success for `problem`, fastest first."""
    out = []
    for source in ("both", "domain", "partial"):
        path = SUCCESSES / f"{source}.json"
        if not path.exists():
            continue
        for entry in json.load(open(path)).get(f"{problem}.p", []):
            out.append({"source": source, **entry})
    return sorted(out, key=lambda e: e["time"])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("problem", help="e.g. ROB034-1")
    ap.add_argument("--rank", type=int, default=0,
                    help="which recorded success, 0 = fastest (default)")
    ap.add_argument("--list", action="store_true", help="list records and exit")
    ap.add_argument("--baseline", action="store_true",
                    help="also run with no hints, same flags and timeout")
    ap.add_argument("--timeout", type=int, help="override the recorded timeout")
    ap.add_argument("--outdir", type=Path, default=ROOT / "logs" / "replicate")
    a = ap.parse_args()

    records = load_records(a.problem)
    if not records:
        sys.exit(f"no recorded success for {a.problem} in {SUCCESSES}")
    if a.list:
        for i, r in enumerate(records):
            flags = " ".join(r["config"]["twee"]["flags"])
            print(f"  [{i}] {r['time']:8.1f}s  {r['source']:<8} "
                  f"{len(r['hints']):3d} hints  {flags}")
        return

    rec = records[a.rank]
    flags = rec["config"]["twee"]["flags"]
    timeout = a.timeout or rec["config"]["twee"].get("timeout", 1000)
    print(f"{a.problem}  [rank {a.rank}/{len(records)-1}]  source={rec['source']}")
    print(f"  recorded  {rec['time']:.1f}s with {len(rec['hints'])} hints")
    print(f"  flags     {' '.join(flags)}")
    print(f"  timeout   {timeout}s")

    a.outdir.mkdir(parents=True, exist_ok=True)
    jobs = [("hinted", rec["hints"])]
    if a.baseline:
        jobs.append(("baseline", []))

    results = {}
    for label, hints in jobs:
        path = runner.write_problem(a.problem,
                                    a.outdir / f"{a.problem}_{label}.p",
                                    hints=hints)
        print(f"\n  running {label} ({len(hints)} hints) ...", flush=True)
        # use_max_time stays False: the recorded Twitch times were produced with
        # an external timeout and no --max-time, so adding one would change the
        # search and make the comparison meaningless.
        r = runner.run(path, flags, timeout, problem=a.problem,
                       n_hints=len(hints), use_max_time=False)
        (a.outdir / f"{a.problem}_{label}.out").write_text(r.output)
        results[label] = r
        verdict = "PROVED" if r.proved else f"NO PROOF ({r.status})"
        print(f"    {verdict}  {r.cpu:.1f}s cpu  {r.wall:.1f}s wall")

    h = results["hinted"]
    print(f"\n  replication: recorded {rec['time']:.1f}s -> ours {h.cpu:.1f}s cpu", end="")
    if h.proved:
        print(f"  ({h.cpu / rec['time']:.2f}x recorded)")
    else:
        print("  -- DID NOT REPRODUCE")
    if a.baseline:
        b = results["baseline"]
        if b.proved and h.proved:
            print(f"  hint effect: {b.cpu / h.cpu:.2f}x speedup "
                  f"(baseline {b.cpu:.1f}s)")
        elif h.proved:
            print(f"  hint effect: baseline did not prove ({b.status}) "
                  f"within {timeout}s")

    json.dump({"problem": a.problem, "rank": a.rank, "recorded": rec["time"],
               "flags": flags, "timeout": timeout, "n_hints": len(rec["hints"]),
               "results": {k: {"result": v.status, "proved": v.proved,
                               "cpu": v.cpu, "wall": v.wall}
                           for k, v in results.items()}},
              open(a.outdir / f"{a.problem}_replication.json", "w"), indent=2)


if __name__ == "__main__":
    main()
