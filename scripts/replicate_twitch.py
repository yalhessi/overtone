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
import os
import re
import resource
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUCCESSES = ROOT / "twitch" / "data" / "experiments" / "hard_successes"
ALWAYS = ["--kbo-weight0-unary", "--print-score"]


def env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        dotenv = ROOT / ".env"
        if dotenv.exists():
            for line in dotenv.read_text().splitlines():
                if line.startswith(f"{name}="):
                    val = line.split("=", 1)[1].strip()
                    break
    if not val:
        sys.exit(f"{name} is not set; run ./bootstrap.sh")
    return val


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


def as_cnf_hint(term: str, i: int) -> str:
    """Byte-identical to Twitch's src/utils.py:160."""
    return f"cnf(hint_{i}, axiom,\n\t $hint( {term} )).\n"


def build_input(problem: str, hints, dest: Path) -> Path:
    src = next((Path(env("TPTP_ROOT")) / "Problems").rglob(f"{problem}.p"), None)
    if src is None:
        sys.exit(f"{problem}.p not found under TPTP_ROOT/Problems")
    body = src.read_text()
    if hints:
        body += "\n\n" + "\n".join(as_cnf_hint(h, i)
                                   for i, h in enumerate(hints, start=1))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(body)
    return dest


def run(path: Path, flags, timeout: int):
    cmd = ([env("TWEE_PATH"), str(path), "--root", env("TPTP_ROOT")]
           + [f for flag in flags for f in flag.split()] + ALWAYS)
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.monotonic()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True)
    try:
        out, _ = proc.communicate(timeout=timeout)
        status = "ran"
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
        status = "timeout"
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)
    # twee exits 0 whether or not it proved anything; the RESULT line is the
    # only reliable outcome. See FINDINGS.md.
    m = re.search(r"^RESULT:\s*(\w+)", out, re.MULTILINE)
    result = m.group(1) if m else ("Timeout" if status == "timeout" else "None")
    return {"result": result, "proved": result in ("Unsatisfiable", "Theorem"),
            "cpu": cpu, "wall": time.monotonic() - started, "output": out,
            "cmd": cmd}


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
        path = build_input(a.problem, hints,
                           a.outdir / f"{a.problem}_{label}.p")
        print(f"\n  running {label} ({len(hints)} hints) ...", flush=True)
        r = run(path, flags, timeout)
        (a.outdir / f"{a.problem}_{label}.out").write_text(r["output"])
        results[label] = r
        verdict = "PROVED" if r["proved"] else f"NO PROOF ({r['result']})"
        print(f"    {verdict}  {r['cpu']:.1f}s cpu  {r['wall']:.1f}s wall")

    h = results["hinted"]
    print(f"\n  replication: recorded {rec['time']:.1f}s -> ours {h['cpu']:.1f}s cpu", end="")
    if h["proved"]:
        print(f"  ({h['cpu'] / rec['time']:.2f}x recorded)")
    else:
        print("  -- DID NOT REPRODUCE")
    if a.baseline:
        b = results["baseline"]
        if b["proved"] and h["proved"]:
            print(f"  hint effect: {b['cpu'] / h['cpu']:.2f}x speedup "
                  f"(baseline {b['cpu']:.1f}s)")
        elif h["proved"]:
            print(f"  hint effect: baseline did not prove ({b['result']}) "
                  f"within {timeout}s")

    json.dump({"problem": a.problem, "rank": a.rank, "recorded": rec["time"],
               "flags": flags, "timeout": timeout, "n_hints": len(rec["hints"]),
               "results": {k: {x: v[x] for x in ("result", "proved", "cpu", "wall")}
                           for k, v in results.items()}},
              open(a.outdir / f"{a.problem}_replication.json", "w"), indent=2)


if __name__ == "__main__":
    main()
