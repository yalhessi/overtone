"""Does the hint channel help, and past what dose does it hurt?

FINDINGS once said hints "cannot poison" because they form no critical pairs.
That does not follow, and the archive contradicts it: 43 hints neutral but 227
**2.1x slower than no hints**, a flat hint set 1.29x slower at cv <= 0.2%, and
all 234 mined lemmas as hints proving none of four targets that eight axioms
proved three of. The mechanism is `size'` (CP.hs:258): a hint match takes the
FIRST entry `Index.matches` returns, not the best, and short-circuits the
structural walk -- the subterm's own size is never computed, only `hint_cost`.
Each added hint converts more subterms from "measured" to "flat", so the score
function loses resolution and the queue orders on noise. Harm is monotone in
dose.

The 56.3s combined-channel figure that prompted a pipeline change is a SINGLE
run, made under parallel core load, at 15 hints -- inside the 9-33 band the
archive already calls safe. It is not evidence about large pools, and it was
never checked against the two controls that decide the question:

    standalone, no hints at all      <- never run; the baseline everything needs
    the pool as hints, no axioms     <- reported as timeout and explained away
                                        as "standalone wearing a costume",
                                        which is exactly what this compares

Everything here runs ONE twee at a time and repeats, because the numbers in
FINDINGS that held up were repeated to cv <= 0.2% and the ones that did not were
single runs under contention.

    python scripts/hint_dose.py --repeats 3 --budget 300
"""
import argparse
import hashlib
import json
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from overtone import config                                       # noqa: E402
from overtone.agent import dag                                    # noqa: E402
from overtone.agent.derive import derive_sketch                   # noqa: E402

PROBLEM = "RNG029-5"
# ((XY)Z)Y = X(Y(ZY)), the waypoint the manual route proves in 197.8s.
RIGHT_MOUFANG = ("multiply(multiply(multiply(X,Y),Z),Y)",
                 "multiply(X,multiply(Y,multiply(Z,Y)))")
# "the exact four: cyclic, both def variants, right-Moufang" (FINDINGS).
WINNERS = ["associator_perm_120", "associator_def_yzx",
           "associator_def_yxz_neg", "right_moufang"]
# What WINNERS proves in, under --flatten-goal, from the ledger (probe.exact4).
# The calibration arm must reproduce this or the run is void.
REFERENCE_CPU = 67.9


def pool():
    """The 19 derived lemmas, plus the waypoint. Given axioms are not lemmas."""
    sk = derive_sketch(PROBLEM)[0]
    goal = next((n for n in sk.nodes if n.endswith("_goal")), None)
    eqs = {n: (l, r) for n, (l, r, _) in sk.nodes.items()
           if n not in sk.given and n != goal}
    eqs["right_moufang"] = RIGHT_MOUFANG
    return eqs, sk.nodes[goal][:2]


def run(label, axioms, hints, goal, outdir, budget, direction, extra=(),
        binary=None):
    """One twee, alone on the machine. `reuse=False` -- old rows were contended.

    `binary` must be the DETERMINISTIC build. Stock twee schedules interreduce
    off `getCPUTime` (`Twee/Task.hs`, upstream), so it fires at a different
    derivation step on every run, rewrites the rule set at a different moment,
    and the search forks from there. Measured on this experiment's own output:
    two runs of byte-identical input agreed through rule 1855, then one
    interreduced and the other took three more rules first, and every later
    interreduce point drifted. A dose curve measured that way is a lottery.
    """
    t0 = time.monotonic()
    row = dag._job({"problem": PROBLEM, "node": f"dose.{label}",
                    "lhs": goal[0], "rhs": goal[1],
                    "eqs": list(axioms), "hint_eqs": list(hints),
                    "channel": "axioms", "direction": direction,
                    "extra_flags": tuple(extra),
                    "budget": budget, "outdir": str(outdir),
                    "binary": binary,
                    "reuse": False, "ledger": None})
    out = Path(row["output"]) if row.get("output") else None
    row["digest"] = (hashlib.sha256(out.read_bytes()).hexdigest()[:12]
                     if out and out.exists() else None)
    row["wall_measured"] = round(time.monotonic() - t0, 1)
    return row


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--budget", type=int, default=300)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--seed", type=int, default=0)
    # MEASURED: the 67.9s reference proof is `--flatten-goal` (ledger,
    # probe.exact4). A first version of this script defaulted to the other
    # direction, and all eight arms timed out -- a clean, plausible-looking
    # dose curve of pure harness fault. Hence `--calibrate` below.
    ap.add_argument("--direction", default="--flatten-goal")
    ap.add_argument("--no-calibrate", action="store_true",
                    help="skip the reference check. Only for a deliberate "
                         "experiment where the reference is expected to fail.")
    ap.add_argument("--resonance", action="store_true",
                    help="add --resonance, which makes a hint count only when "
                         "its substitution maps variables to variables. It is "
                         "the gate aimed at over-general hints -- unlike "
                         "picking a 'better' matching hint, which cannot help: "
                         "`hint_cost` is a function of the HINT alone "
                         "(Twee.hs:618), so choosing among matches changes "
                         "which number is charged, never how many subterms get "
                         "flattened. Off by default in twee; never tried here.")
    ap.add_argument("--binary", default=None,
                    help="default is the DETERMINISTIC build; stock twee "
                         "schedules interreduce by CPU time and forks the "
                         "search on every run")
    ap.add_argument("--out", default="logs/hint_dose")
    a = ap.parse_args()

    eqs, goal = pool()
    missing = [n for n in WINNERS if n not in eqs]
    if missing:
        sys.exit(f"the recorded winning set is not in the pool: {missing}")
    win = [eqs[n] for n in WINNERS]
    rest_names = [n for n in eqs if n not in WINNERS]
    random.Random(a.seed).shuffle(rest_names)
    rest = [eqs[n] for n in rest_names]

    # Two controls, a replication, and a dose curve over the SAME shuffled rest,
    # so k and k+1 differ by exactly one hint rather than by a different set.
    # MEASURED: C0 times out at 300s, so every no-axiom arm below is a timeout
    # and the C0/C1 pair cannot decide the harm question -- two timeouts are not
    # a comparison. The arms that CAN decide it are the D curve, which varies
    # hint count on top of an axiom set that does prove. Kept anyway because
    # "standalone does not prove at this budget" is itself the fact that
    # retired the "hints alone are just standalone" story.
    arms = [
        ("C0_standalone_no_hints", [], []),
        ("C1_pool_as_hints_only", [], list(eqs.values())),
        ("R_win4_axioms_only", win, []),
        ("R_win4_plus_all_hints", win, rest),
    ]
    for k in (2, 4, 8, 12):
        if k <= len(rest):
            arms.append((f"D_win4_plus_{k}_hints", win, rest[:k]))
    # ...and the same doses without the axioms, to separate "hints help" from
    # "hints help *because* the axioms are already sufficient".
    for k in (4, 12):
        if k <= len(rest):
            arms.append((f"N_noaxioms_{k}_hints", [], rest[:k]))

    binary = a.binary or config.twee_path(deterministic=True)
    extra = ("--resonance",) if a.resonance else ()
    outdir = Path(a.out + ("-resonance" if a.resonance else ""))
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"pool {len(eqs)} lemmas | winners {len(win)} | rest {len(rest)}")
    print(f"{len(arms)} arms, {a.repeats} repeats, serial, budget {a.budget}s\n")

    # CALIBRATE FIRST. The reference arm has a known answer, so run it before
    # anything else and stop if it does not come back. Every arm here shares a
    # direction, a goal statement and a pool; if any of those is wrong, every
    # arm times out and the output looks exactly like a real negative -- which
    # is the failure mode FINDINGS calls the worst this harness can have. A
    # measurement whose control did not reproduce is not a measurement.
    if not a.no_calibrate:
        ref = run("calibrate", win, [], goal, outdir, a.budget, a.direction,
                  extra, binary)
        print(f"  calibrate: win4 axioms alone -> {ref.get('result')} "
              f"{ref['cpu']:.1f}s (reference {REFERENCE_CPU}s)")
        if not ref["proved"]:
            sys.exit(
                f"\nABORT: the reference set did not prove in {a.budget}s.\n"
                f"  Expected {REFERENCE_CPU}s under {a.direction}.\n"
                f"  Something shared by every arm is wrong -- direction, goal\n"
                f"  statement, or pool -- so no arm below would mean anything.")
        if ref["cpu"] > REFERENCE_CPU * 3:
            print(f"  WARNING: {ref['cpu']:.1f}s is far above the reference; "
                  f"the machine is loaded or the build changed.")
    print()

    results = []
    for label, ax, hi in arms:
        cpus, digests, proved = [], [], 0
        # A timeout costs the full budget every repeat and says the same thing
        # each time; only repeat what actually returns a number to compare.
        reps = a.repeats
        for i in range(reps):
            r = run(f"{label}.{i}", ax, hi, goal, outdir, a.budget,
                    a.direction, extra, binary)
            cpus.append(r["cpu"])
            digests.append(r.get("digest"))
            proved += bool(r["proved"])
            if not r["proved"]:
                print(f"  {label:<28} {r.get('result','?'):<12} "
                      f"{r['cpu']:7.1f}s  (not repeated)")
                break
        else:
            mean = statistics.mean(cpus)
            cv = (statistics.stdev(cpus) / mean * 100) if len(cpus) > 1 else 0.0
            # On the deterministic build, identical input must give identical
            # OUTPUT; only CPU jitters. A differing digest means the binary is
            # not deterministic after all, and no number in this table can be
            # attributed to the hint set rather than to the interreduce lottery.
            same = len(set(d for d in digests if d)) <= 1
            print(f"  {label:<28} {'proved':<12} {mean:7.1f}s  "
                  f"cv {cv:4.1f}%  n={len(cpus)}"
                  f"{'' if same else '   ** DERIVATION DIVERGED **'}")
        results.append({"arm": label, "n_axioms": len(ax), "n_hints": len(hi),
                        "proved": proved, "runs": len(cpus), "cpus": cpus,
                        "digests": digests,
                        "deterministic": len(set(d for d in digests if d)) <= 1,
                        "mean_cpu": statistics.mean(cpus) if cpus else None})
        (outdir / "results.json").write_text(json.dumps(results, indent=2))

    by = {r["arm"]: r for r in results}
    base, only = by.get("C0_standalone_no_hints"), by.get("C1_pool_as_hints_only")
    print("\n--- the control that decides it ---")
    if base and only:
        if not base["proved"] and not only["proved"]:
            print("  both timed out: this budget cannot separate them. Raise it.")
        else:
            verdict = ("HINTS HURT" if (base["proved"] and not only["proved"])
                       or (base["proved"] and only["proved"]
                           and only["mean_cpu"] > base["mean_cpu"] * 1.1)
                       else "hints do not hurt at this dose")
            print(f"  standalone {base['mean_cpu']:.1f}s vs pool-as-hints "
                  f"{only['mean_cpu']:.1f}s -> {verdict}")
    print(f"\nwrote {outdir / 'results.json'}")


if __name__ == "__main__":
    main()
