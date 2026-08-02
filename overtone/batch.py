"""Resumable parallel sweeps and the results.jsonl format.

Owns one serialisation format on both sides: `sweep` appends records, `load_done`
and `screen_baseline` read them back. Deliberately not a job framework -- there is
no Job type, no registry, no retry policy. `run_one` is opaque and the only key
this module requires of a record is `id`.

Presentation stays with the caller: `scripts/screen.py` keeps its own markdown
tracker, because that is one experiment's reporting and the thing most likely to
be hand-tweaked.
"""
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from overtone import config

# Frozen strings, not conventions to tidy. `agent/donors.py` discovers donor
# proofs by parsing PROOF_STEM; unify these two and donor discovery does not
# crash -- it silently finds nothing and reports "no donor with a saved proof",
# which reads like a data problem rather than a bug.
INPUT_STEM = "{problem}.{tag}.p"          # logs/<run>/inputs/
PROOF_STEM = "{problem}_{tag}.out"        # logs/<run>/proofs/


def load_done(results_path: Path) -> dict:
    """Records already written, keyed by id, for resume."""
    done = {}
    if Path(results_path).exists():
        for line in Path(results_path).read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                done[rec["id"]] = rec
    return done


def append_record(fh, rec: dict) -> None:
    """Append one record. `fh` should be opened line-buffered so a killed sweep
    still leaves every completed job on disk."""
    fh.write(json.dumps(rec) + "\n")


def sweep(jobs, run_one, results_path: Path, workers: int = 12,
          on_result=None) -> dict:
    """Run `run_one` over `jobs` in a process pool, appending as results land.

    `run_one` must be a module-level function: it is pickled to reach the pool,
    so a closure or bound method fails only once the pool starts, with an opaque
    error. Returns {id: record} including anything already present.

    Exceptions from a worker are reported and skipped rather than killing the
    sweep -- note that this catches Exception, so library code called here must
    raise rather than call sys.exit (SystemExit would escape).
    """
    results_path = Path(results_path)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    done = load_done(results_path)
    with open(results_path, "a", buffering=1) as sink, \
            ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_one, j): j for j in jobs}
        for i, fut in enumerate(as_completed(futures), start=1):
            try:
                rec = fut.result()
            except Exception as e:                                # noqa: BLE001
                print(f"  ERROR {futures[fut]}: {e}", flush=True)
                continue
            append_record(sink, rec)
            done[rec["id"]] = rec
            if on_result:
                on_result(i, rec, done)
    return done


def screen_baseline(problem: str, roots=None) -> dict:
    """Recorded no-hint outcomes for `problem`, as {"<budget>s <direction>": status}.

    Every hinted or learned run needs its paired baseline; this is where they are.
    """
    out = {}
    roots = roots or [config.LOGS / "screen", config.LOGS / "screen4000"]
    for root in roots:
        f = Path(root) / "results.jsonl"
        if not f.exists():
            continue
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r["problem"] == problem:
                out[f"{r['budget']}s {r['direction']}"] = r["result"]
    return out
