"""Can a hint's effect be predicted before running the proof attempt?

`scripts/hint_effect.py` measures what each single hint does. This asks whether
anything computable beforehand agrees with that.

The mechanism is exact, so the candidates are not guesses. `size'` (CP.hs) walks
a term charging `cfg_funweight` per function symbol and `cfg_varweight` per
variable; when a subterm matches a hint it charges `hint_cost` INSTEAD of that
subterm's structure and recurses into the substitution's bindings. And
`hint_cost` is `(len h - |vars h|) * factor` (Twee.hs:618) -- the hint's OWN
function-symbol count, times 0.5. So:

    discount per match ~= 0.5 * (function symbols in the hint)

fixed by the hint, independent of how large the matched subterm is. A one-symbol
hint like `associator(X,Y,Z) = associator(Y,Z,X)` can only ever shave 0.5; a
four-symbol definition shaves 2.0 every time it fires.

That gives magnitude but not sign. For sign the question is WHICH critical pairs
get cheaper, and the testable form is an **enrichment ratio**: of the terms twee
actually derived, a hint that preferentially matches the ones on the successful
proof path should steer toward it, and one that preferentially matches
everything else should steer away.

    on_path_enrichment = P(hint matches | term is on the proof path)
                       / P(hint matches | term was merely derived)

Both populations come from the baseline run's own output, so this is computable
from one prior proof and no new prover time.

    python scripts/hint_predict.py
"""
import argparse
import json
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from overtone import terms                                        # noqa: E402
from scripts.hint_multiplicity import match                       # noqa: E402

_RULE = re.compile(r"^\((?:[\d.]+)\)\s+\d+\.\s+(.*?)\s+->\s+(.*)$")
_LEMMA = re.compile(r"^Lemma \d+: (.*?) = (.*?)\.$")
_STEP = re.compile(r"^[=\s]*([a-z_][\w]*\(.*?\))(?:\s+\(peak\))?\s*$")


def funs(t):
    return 0 if isinstance(t, str) else 1 + sum(funs(a) for a in t[1:])


def _subterms(text, out):
    t = terms.safe_term(text.strip().rstrip("."))
    if t is not None and not isinstance(t, str):
        out |= {x for x in terms.subtrees(t) if not isinstance(x, str)}


def populations(path, cap=3000):
    """(everything derived, everything on the proof path) as subterm sets."""
    lines = Path(path).read_text().splitlines()
    try:
        cut = next(i for i, l in enumerate(lines) if l.startswith("Proof:"))
    except StopIteration:
        cut = len(lines)
    derived, on_path = set(), set()
    for line in lines[:cut][:cap]:
        m = _RULE.match(line)
        if m:
            _subterms(m.group(1), derived)
            _subterms(m.group(2), derived)
    # The proof section: every lemma statement and every rewriting step in it.
    for line in lines[cut:]:
        m = _LEMMA.match(line.strip())
        if m:
            _subterms(m.group(1), on_path)
            _subterms(m.group(2), on_path)
            continue
        m = _STEP.match(line.strip())
        if m:
            _subterms(m.group(1), on_path)
    return derived, on_path


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--effects", default="logs/hint_effect/effects.json")
    a = ap.parse_args()

    rows = json.loads(Path(a.effects).read_text())
    base = rows[0]
    derived, on_path = populations(base["output"])
    print(f"baseline proof: {len(on_path)} subterms on the path, "
          f"{len(derived)} derived overall\n")

    from scripts.hint_dose import pool
    eqs, _ = pool()

    out = []
    for r in rows[1:]:
        sides = [terms.safe_term(s) for s in eqs[r["hint"]]]
        hs = [h for h in sides if h is not None and not isinstance(h, str)]
        disc = 0.5 * max((funs(h) for h in hs), default=0)
        hit_d = sum(1 for s in derived if any(match(h, s) is not None for h in hs))
        hit_p = sum(1 for s in on_path if any(match(h, s) is not None for h in hs))
        pd = hit_d / len(derived) if derived else 0
        pp = hit_p / len(on_path) if on_path else 0
        enrich = (pp / pd) if pd else float("nan")
        out.append({**r, "discount": disc, "p_derived": pd, "p_path": pp,
                    "enrichment": enrich, "pressure": disc * pd})

    print(f"{'hint':<26}{'measured':>12}{'disc':>6}{'p_path':>8}"
          f"{'p_deriv':>8}{'enrich':>8}")
    for r in sorted(out, key=lambda r: (not r["proved"], r["cpu"])):
        eff = "LOST" if not r["proved"] else f"{r['ratio']:.2f}x"
        e = r["enrichment"]
        print(f"  {r['hint']:<24}{eff:>12}{r['discount']:>6.1f}"
              f"{r['p_path']:>8.2f}{r['p_derived']:>8.2f}"
              f"{e:>8.2f}" if e == e else
              f"  {r['hint']:<24}{eff:>12}{r['discount']:>6.1f}"
              f"{r['p_path']:>8.2f}{r['p_derived']:>8.2f}{'n/a':>8}")

    def spearman(xs, ys):
        def rank(v):
            order = sorted(range(len(v)), key=lambda i: v[i])
            rk = [0.0] * len(v)
            for pos, i in enumerate(order):
                rk[i] = pos
            return rk
        rx, ry = rank(xs), rank(ys)
        n = len(xs)
        if n < 3:
            return float("nan")
        mx, my = statistics.mean(rx), statistics.mean(ry)
        num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
        den = (sum((a - mx) ** 2 for a in rx) *
               sum((b - my) ** 2 for b in ry)) ** 0.5
        return num / den if den else float("nan")

    # Rank every arm by cost, counting a lost proof as worse than any timing.
    cost = [(r["cpu"] if r["proved"] else 1e9) for r in out]
    print("\n--- Spearman against measured cost (negative = predicts benefit) ---")
    for key in ("discount", "p_path", "p_derived", "enrichment", "pressure"):
        vals = [r[key] for r in out]
        if any(v != v for v in vals):
            print(f"  {key:<12} n/a (undefined for some hint)")
            continue
        print(f"  {key:<12} rho = {spearman(vals, cost):+.2f}")


if __name__ == "__main__":
    main()
