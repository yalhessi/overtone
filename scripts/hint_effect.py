"""Which single hints help, which destroy, and can either be predicted?

The dose curve (FINDINGS) is nested -- 4 hints to 8 adds four lemmas at once --
so nothing in it is attributable to one hint. This runs the design that is:
the sufficient four as axioms, plus EXACTLY ONE hint, one arm per pool member,
against the 69.2s no-hint baseline. Deterministic build, so one run per arm is
the arm's whole behaviour and the digest proves it.

That gives a per-hint effect. The point is to test predictors against it, since
a predictor is only worth having if it works BEFORE the run:

  coverage      how many scorable subterms the hint matches at all
  discount      how much apparent size it removes, summed over what it matches
                -- `size'` charges `hint_cost` in place of the subterm's own
                structure and then recurses into the substitution, so the saving
                is size(t) - hint_cost - size(bindings), which is computable
                offline and is the entire mechanism by which a hint acts
  on_path       whether what it discounts appears in the BASELINE PROOF. A hint
                that cheapens terms the successful derivation actually visits
                should steer toward it; one that cheapens terms leading
                elsewhere should steer away. This is the predictor with a
                mechanism behind it rather than a shape.

`on_path` needs the baseline proof, which is why the baseline arm is run first
and its output kept.

    python scripts/hint_effect.py --budget 300
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from overtone import config                                       # noqa: E402
from scripts.hint_dose import (REFERENCE_CPU, WINNERS,            # noqa: E402
                               pool, run)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--budget", type=int, default=300)
    ap.add_argument("--direction", default="--flatten-goal")
    ap.add_argument("--binary", default=None)
    ap.add_argument("--loo", type=int, default=0, metavar="K",
                    help="instead of singletons, take the first K of the "
                         "seeded shuffle -- the set the dose curve measured -- "
                         "and drop one member at a time. Singletons showed 0 of "
                         "15 hints helping while the 8-set runs 1.71x faster "
                         "than none, so the benefit is not carried by any "
                         "member and only leave-one-out can locate it.")
    ap.add_argument("--out", default="logs/hint_effect")
    a = ap.parse_args()

    eqs, goal = pool()
    win = [eqs[n] for n in WINNERS]
    rest = [n for n in eqs if n not in WINNERS]
    binary = a.binary or config.twee_path(deterministic=True)
    outdir = Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)

    if a.loo:
        import random
        random.Random(0).shuffle(rest)
        rest = rest[:a.loo]
    base_hints = [eqs[n] for n in rest] if a.loo else []
    base = run("baseline", win, base_hints, goal, outdir, a.budget, a.direction,
               (), binary)
    what = f"4 axioms, {len(base_hints)} hints" if a.loo else "4 axioms, 0 hints"
    print(f"  baseline ({what}): {base.get('result')} "
          f"{base['cpu']:.1f}s   [no-hint reference {REFERENCE_CPU}s]")
    if not base["proved"]:
        sys.exit("ABORT: the baseline did not prove; nothing below can be read "
                 "as a hint effect.")
    print(f"  baseline proof kept at {base.get('output')}\n")
    print(f"  {len(rest)} {'leave-one-out' if a.loo else 'single-hint'} arms, "
          f"budget {a.budget}s\n")

    rows = [{"hint": "(none)", "cpu": base["cpu"], "proved": True,
             "output": base.get("output"), "digest": base.get("digest")}]
    for name in rest:
        # LOO: everything BUT this one. Singleton: only this one.
        supply = ([eqs[n] for n in rest if n != name] if a.loo
                  else [eqs[name]])
        r = run(f"{'loo' if a.loo else 'one'}.{name}", win, supply, goal,
                outdir, a.budget, a.direction, (), binary)
        ratio = r["cpu"] / base["cpu"] if base["cpu"] else 0
        verdict = ("LOSES THE PROOF" if not r["proved"]
                   else f"{ratio:.2f}x {'slower' if ratio > 1 else 'FASTER'}")
        tag = f"without {name}" if a.loo else name
        print(f"  {tag:<26} {r['cpu']:7.1f}s  {verdict}")
        rows.append({"hint": name, "cpu": r["cpu"], "proved": r["proved"],
                     "ratio": ratio, "output": r.get("output"),
                     "digest": r.get("digest")})
        (outdir / "effects.json").write_text(json.dumps(rows, indent=2))

    good = [r for r in rows[1:] if r["proved"] and r["cpu"] < base["cpu"]]
    bad = [r for r in rows[1:] if not r["proved"]]
    print(f"\n  {len(good)} helped, {len(bad)} lost the proof, "
          f"{len(rows) - 1 - len(good) - len(bad)} slowed it")
    print(f"  wrote {outdir / 'effects.json'}")


if __name__ == "__main__":
    main()
