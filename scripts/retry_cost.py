#!/usr/bin/env python3
"""What the automatic standalone retry cost, from the runs that actually ran.

    ./scripts/retry_cost.py                    # archived dag.json under logs/
    ./scripts/retry_cost.py --ledger           # also the weaker ledger estimate

`dag.verify` used to re-attempt every failed node with all of its parents
removed, at the same budget that had just failed, racing both directions. This
script is the measurement that retired it, and it is kept because the evidence
lives only in artifacts: the `scope_retry` key it reads no longer exists in the
code, so the number cannot be re-derived from a fresh run.

**Read `dag.json`, not the ledger.** A retry row is only real prover time when
`reused` is false -- the ledger answers a repeat from the record, and counting
those charges the same search many times over. Of 308 `scope_retry` rows across
84 archived files, 81 were fresh.

The ledger can only approximate this. It has no `scope_retry` key, so the best it
can do is `n_support == 0`, which cannot tell an automatic retry from a
deliberate `--scope none` control arm or from a naturally parentless donor rung.
It is reported under `--ledger` as a separate, weaker number and should not be
quoted as the cost of the retry.

Grouping is by run key -- the hash of the input bytes and the invocation -- and
never by node name. Node names repeat across problems and across iterations of
one loop, so a name is not an identity; `final` alone appears in every run.
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from overtone import config


def retry_rows(root: Path):
    """Every `scope_retry` row in every archived dag.json, tagged with its file."""
    for f in sorted(root.glob("**/dag.json")):
        try:
            d = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        for r in d.get("results", ()):
            if r.get("scope_retry"):
                yield f, r


def summarise(rows):
    """Totals over fresh retry rows, plus what each distinct search cost."""
    fresh = [(f, r) for f, r in rows if not r.get("reused")]
    won = [(f, r) for f, r in fresh if r.get("proved")]
    lost = [(f, r) for f, r in fresh if not r.get("proved")]

    def cpu(rs):
        return sum(r.get("cpu") or 0.0 for _, r in rs)

    # By run key where there is one: two rows with the same key are the same
    # search and must not be counted twice. Rows predating the key fall back to
    # their own identity so nothing is silently merged.
    by_key = defaultdict(list)
    for i, (f, r) in enumerate(fresh):
        by_key[r.get("key") or f"{f}#{i}"].append(r)
    return {"rows": len(rows), "fresh": len(fresh), "cpu": cpu(fresh),
            "won": len(won), "cpu_won": cpu(won),
            "lost": len(lost), "cpu_lost": cpu(lost),
            "searches": len(by_key), "wins": won}


def ledger_estimate(path: Path):
    """Empty-support CPU as a share of all of it. An upper bound, not the cost."""
    rows = []
    with open(path) as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue          # a torn line from a killed writer
            if "/pytest-of-" not in (rec.get("input") or ""):
                rows.append(rec)
    tot = sum(r.get("cpu") or 0.0 for r in rows)
    zero = sum(r.get("cpu") or 0.0 for r in rows
               if not (r.get("n_support") or 0))
    return {"rows": len(rows), "cpu": tot, "cpu_empty": zero}


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--logs", type=Path, default=None,
                    help="root to scan for dag.json (default: the logs dir)")
    ap.add_argument("--ledger", action="store_true",
                    help="also print the weaker ledger-side estimate")
    a = ap.parse_args()

    root = a.logs or config.LOGS
    rows = list(retry_rows(root))
    if not rows:
        print(f"no scope_retry rows under {root} -- nothing to measure")
        return 1
    s = summarise(rows)

    print(f"archived standalone retries under {root}")
    print(f"  rows                {s['rows']:>6}"
          f"   ({s['fresh']} fresh, {s['rows'] - s['fresh']} served from the "
          f"ledger)")
    print(f"  distinct searches   {s['searches']:>6}")
    print(f"  fresh prover time   {s['cpu']:>9.1f}s")
    share = 100 * s["cpu_lost"] / s["cpu"] if s["cpu"] else 0.0
    print(f"    proved nothing    {s['cpu_lost']:>9.1f}s over {s['lost']} row(s)"
          f"  -- {share:.1f}%")
    print(f"    proved something  {s['cpu_won']:>9.1f}s over {s['won']} row(s)")

    if s["wins"]:
        print("\n  the retries that paid off (node, direction, cpu):")
        seen = set()
        for f, r in sorted(s["wins"], key=lambda x: x[1].get("cpu") or 0.0):
            tag = (r["node"], r.get("direction"))
            if tag in seen:
                continue
            seen.add(tag)
            print(f"    {r['node']:<28} {r.get('direction'):<20} "
                  f"{r.get('cpu') or 0.0:>7.1f}s")
        print("    -- every one under --flatten-goal, the SECOND of "
              "dag.DIRECTIONS, which is why a one-direction probe would have "
              "found none of them")

    if a.ledger:
        p = config.LOGS / "ledger.jsonl"
        if not p.exists():
            print(f"\nno ledger at {p}")
        else:
            e = ledger_estimate(p)
            pct = 100 * e["cpu_empty"] / e["cpu"] if e["cpu"] else 0.0
            print(f"\nledger-side UPPER BOUND (weaker -- see the module "
                  f"docstring)")
            print(f"  non-test rows       {e['rows']:>6}")
            print(f"  all prover time     {e['cpu']:>9.1f}s")
            print(f"  empty-support       {e['cpu_empty']:>9.1f}s  -- {pct:.1f}%"
                  f"  (retries AND deliberate --scope none arms)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
