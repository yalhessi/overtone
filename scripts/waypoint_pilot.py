#!/usr/bin/env python3
"""Look for a waypoint by enumeration and measurement, not by derivation.

    ./scripts/waypoint_pilot.py RNG029-5 --bank logs/loop/RNG029-5-derive-03
    ./scripts/waypoint_pilot.py RNG029-5 --dry-run     # no prover; sizes only

FINDINGS settles that the mechanical route cannot *generate* one. The goal is not
a linear consequence of the scaffold, so `freering.certificate` cannot reach it;
and a waypoint cannot be mined out of the searches that failed to derive it --
`right_moufang` appears in 0 of 20 evidence banks, which is definitional rather
than unlucky, since a bank holds what searches derived cheaply. Enumeration plus
the prover is what is left.

Three stages, each bounded:

**Candidates.** `freering.balanced_candidates` enumerates word-preserving
rebracketings at the conjecture's own degree and variable-multiplicity partition:
59 statements for RNG029-5, containing the right-Moufang identity under alpha and
orientation normalisation without ever naming it.

**Recomposition screen.** For each mined equation `E` and each candidate `W`,
assume `E` plus the derived scaffold and give `W` two seconds. This is the
operation the loop never performed: `derive-03` selected an associator identity
at iteration 2 and never asked which product-form identity that equation makes
easy. Assumptions here are search state -- nothing proved, nothing entering a
sketch.

**Bidirectional witness.** A candidate counts only when both arms land: the
scaffold proves `W`, and `W` proves the conjecture. `dag.race_support` runs the
support variants in parallel and stops at the first proof, which matters because
the winning set is narrow -- its own docstring records `right_moufang` proving
from exactly three lemmas and timing out if any one is removed or a fourth true
one is added.

**Gold-free by construction.** Nothing here reads `scripts/rng_dag.py`, the
manual sketch, a donor proof, or any Moufang artifact. The hypothesis class is
still chosen knowing where Moufang lives, so a result on RNG029-5 says much less
than it appears to -- the held-out RNG027/028 family is where the evidence is.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from overtone import config, freering as F, problems
from overtone.agent.dag import race_support, verify
from overtone.agent.derive import derive_sketch
from overtone.agent.evidence import Bank, relevance
from overtone.terms import eq_key


def translation_core(sketch, proved):
    """`[(name, (lhs, rhs))]` -- the scaffold lemmas that actually proved.

    Whatever the seed derived and verified: additivity, the linearised axiom
    instances, the polarizations, the permutations those certify. The pilot does
    not decide which of them a waypoint needs -- the upstream race measures that,
    because nothing about a lemma predicts whether it helps.
    """
    return [(n, sketch.nodes[n][:2]) for n in sorted(sketch.claims())
            if n in proved and not n.endswith("goal")]


def support_variants(core, extra=(), loo=False):
    """`[(label, names, eqs)]` -- the full set, bare, and optionally leave-one-out.

    Staged rather than all at once. A twelve-lemma core makes fourteen sets, and
    at two directions and 300s an arm that is 8,400 prover-seconds for ONE
    candidate -- twice the whole pilot budget, spent before the second candidate
    is reached. So the full set and the bare one go first, and leave-one-out only
    if the budget is there.

    Worth stating what leave-one-out cannot do: `race_support`'s own docstring
    records `right_moufang` proving from exactly three lemmas and timing out if
    any one is removed OR a fourth true one is added. Dropping one lemma from
    twelve explores eleven-element sets, and the winning set may be a small
    subset that no leave-one-out reaches. That is a known limit of this stage,
    not something the budget fixes.
    """
    ex = list(extra)
    names, eqs = [n for n, _ in core], [e for _, e in core]
    en, ee = [x[0] for x in ex], [x[1] for x in ex]
    out = [("core", names + en, eqs + ee), ("bare", en, ee)]
    if loo:
        for i, n in enumerate(names):
            out.append((f"core-{n}",
                        [m for j, m in enumerate(names) if j != i] + en,
                        [e for j, e in enumerate(eqs) if j != i] + ee))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("problem")
    ap.add_argument("--bank", type=Path,
                    help="a run directory holding evidence.jsonl")
    ap.add_argument("--budget", type=float, default=4000.0,
                    help="total prover CPU seconds; the pilot stops at it")
    ap.add_argument("--screen", type=int, default=2, help="seconds per screen arm")
    ap.add_argument("--witness", type=int, default=300, help="seconds per arm")
    ap.add_argument("--node-budget", type=int, default=60)
    ap.add_argument("--evidence", type=int, default=8,
                    help="how many mined equations to screen against")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--outdir", type=Path)
    ap.add_argument("--binary")
    ap.add_argument("--dry-run", action="store_true",
                    help="report the spaces and spend no prover time")
    a = ap.parse_args()

    out = a.outdir or (config.LOGS / "pilot" / a.problem)
    out.mkdir(parents=True, exist_ok=True)
    binary = a.binary or config.twee_path(deterministic=True)
    ledger = None
    spent = {"cpu": 0.0}

    def charge(rows):
        spent["cpu"] += sum(r.get("cpu") or 0.0 for r in rows)
        return spent["cpu"] < a.budget

    conj = problems.conjecture(problems.problem_path(a.problem))
    sketch, _ = derive_sketch(a.problem)
    goal = next(n for n in sketch.nodes if n.endswith("goal"))

    pool = F.balanced_candidates(*conj)
    print(f"{a.problem}: {conj[0]} = {conj[1]}")
    print(f"candidates: {len(pool)} word-preserving rebracketings at degree "
          f"{F.degree(F.expand(F.parse(conj[0]), F.parse(conj[1])))}")

    ev = []
    if a.bank:
        bank = Bank(Path(a.bank) / "evidence.jsonl")
        # `corpus="run"` only: one bank held 15 of 51 artifacts from a /tmp
        # scratchpad smoke test, and a pilot whose inputs are not reproducible
        # is not an experiment.
        # NOT by source count. Ranked that way the top four on RNG029-5 are
        # `(XX)Y = X(XY)`, `(XY)Y = X(YY)` and both in associator form -- the
        # problem's own axioms, which twee already has from the problem file, so
        # assuming them changes nothing and the screen found 0 hits in 59
        # candidates. It is the bank's structural bias showing up at selection:
        # what every search re-derives is what every search already had.
        #
        # So drop anything the axioms or the proved scaffold already state, and
        # order by `evidence.relevance`, which puts definition bridges first --
        # the facet that was invisible, and what the 18x node was an instance of.
        known = {eq_key(l, r) for l, r in
                 problems.named_axioms(problems.problem_path(a.problem)).values()}
        known |= {eq_key(*sketch.nodes[n][:2]) for n in sketch.claims()}
        items = [e for e in bank.all(corpus="run")
                 if not e.universal and eq_key(e.lhs, e.rhs) not in known]
        items.sort(key=relevance)
        ev = [(e.id, (e.lhs, e.rhs)) for e in items[:a.evidence]]
        print(f"evidence: {len(bank)} in the bank, "
              f"{len(bank.all(corpus='run'))} run-sourced, "
              f"{len(items)} after dropping axioms and scaffold, "
              f"{len(ev)} screened against")
        for eid, (l, r) in ev:
            print(f"   {eid}  {l[:52]} = {r[:38]}")

    if a.dry_run:
        print(f"\ndry run: {len(pool)} candidates x {max(1, len(ev))} evidence "
              f"= {len(pool) * max(1, len(ev)) * a.screen * 2}s of screening at "
              f"worst, before cancellation")
        return 0

    v = verify(a.problem, sketch, outdir=out / "scaffold", budget=a.node_budget,
               workers=a.workers, binary=binary, ledger=ledger)
    charge(v["results"])
    core = translation_core(sketch, set(v["proved"]))
    print(f"scaffold: {len(core)} lemma(s) proved, {spent['cpu']:.1f}s charged")
    if not core:
        print("no scaffold proved; nothing to screen against")
        return 2

    hits, trials, trivial = [], [], 0
    print(f"\n--- recomposition screen ({a.screen}s an arm) ---")
    for i, (lhs, rhs) in enumerate(pool):
        if spent["cpu"] >= a.budget:
            print(f"budget reached at candidate {i}; stopping")
            break
        base = support_variants(core)[0]
        # First: does the SCAFFOLD ALONE already prove it? Then it is a
        # consequence of what is proved -- bookkeeping, the accelerant class --
        # and cannot be a waypoint however cheaply it lands. The first version of
        # this screen raced the core alongside the evidence sets, so `core` won
        # 12 times and every one of the six "hits" was scaffold-trivial. Asking
        # the two questions separately is the whole difference.
        #
        # It also does at one second what the linear-algebra version of the same
        # question could not do in 600: whether a statement is a consequence of
        # the proved set.
        triv, rows = race_support(a.problem, lhs, rhs, [base],
                                  outdir=out / f"triv{i:03d}", budget=a.screen,
                                  workers=a.workers, binary=binary, ledger=ledger)
        charge(rows)
        trials += [{"stage": "trivial", "candidate": i, **r} for r in rows]
        if triv:
            trivial += 1
            continue
        if not ev or spent["cpu"] >= a.budget:
            continue
        sets = [(f"+{eid}", base[1] + [eid], base[2] + [eq]) for eid, eq in ev]
        winner, rows = race_support(a.problem, lhs, rhs, sets,
                                    outdir=out / f"screen{i:03d}",
                                    budget=a.screen, workers=a.workers,
                                    binary=binary, ledger=ledger)
        charge(rows)
        trials += [{"stage": "screen", "candidate": i, **r} for r in rows]
        if winner:
            hits.append((i, lhs, rhs, winner))
            print(f"  [{i}] HIT via {winner}: {lhs[:56]}")
    print(f"screen: {len(hits)} hit(s) of {len(pool)} ({trivial} were already "
          f"consequences of the scaffold), {spent['cpu']:.1f}s charged")

    print(f"\n--- bidirectional witness ({a.witness}s an arm) ---")
    witnessed = []
    for i, lhs, rhs, via in hits:
        if spent["cpu"] >= a.budget:
            print("budget reached; stopping")
            break
        up, up_rows = race_support(a.problem, lhs, rhs, support_variants(core),
                                   outdir=out / f"up{i:03d}", budget=a.witness,
                                   workers=a.workers, binary=binary, ledger=ledger)
        charge(up_rows)
        trials += [{"stage": "upstream", "candidate": i, **r} for r in up_rows]
        bridge_eq = None
        if not up and via.startswith("+"):
            # The screen said an assumption `E` makes `W` fall out. That is not
            # a witness -- `E` is mined, not proved -- but it becomes one the
            # moment the scaffold proves `E` itself, and then the grounded
            # support for `W` is the core plus `E`. This is the recursion the
            # loop never performed: it selected such an equation and never asked
            # what it made easy, let alone whether it was itself reachable.
            eid = via[1:]
            eq = dict(ev).get(eid)
            if eq and spent["cpu"] < a.budget:
                ok, e_rows = race_support(a.problem, eq[0], eq[1],
                                          support_variants(core),
                                          outdir=out / f"ev{i:03d}",
                                          budget=a.witness, workers=a.workers,
                                          binary=binary, ledger=ledger)
                charge(e_rows)
                trials += [{"stage": "evidence", "candidate": i, **r}
                           for r in e_rows]
                if ok:
                    bridge_eq = (eid, eq)
                    up = f"{ok}+{eid}"
                    print(f"  [{i}] upstream via a proved {eid} ({ok})")
        if not up:
            print(f"  [{i}] upstream: no arm proved it from the scaffold")
            continue
        extra = [(f"W{i}", (lhs, rhs))]
        if bridge_eq:
            extra.append(bridge_eq)
        down, down_rows = race_support(
            a.problem, conj[0], conj[1],
            support_variants(core, extra=extra),
            outdir=out / f"down{i:03d}", budget=a.witness, workers=a.workers,
            binary=binary, ledger=ledger)
        charge(down_rows)
        trials += [{"stage": "downstream", "candidate": i, **r} for r in down_rows]
        if down:
            witnessed.append({"candidate": i, "lhs": lhs, "rhs": rhs,
                              "screened_via": via, "upstream": up,
                              "downstream": down})
            print(f"  [{i}] WITNESSED: upstream {up}, downstream {down}")
        else:
            print(f"  [{i}] upstream {up}, but it does not prove the conjecture")

    (out / "pilot.json").write_text(json.dumps(
        {"problem": a.problem, "candidates": len(pool), "hits": len(hits),
         "scaffold_trivial": trivial,
         "witnessed": witnessed, "cpu": round(spent["cpu"], 1),
         "budget": a.budget, "trials": trials}, indent=1) + "\n")
    print(f"\n{len(witnessed)} witnessed waypoint(s), {spent['cpu']:.1f}s of "
          f"{a.budget:.0f}s -> {out}/pilot.json")
    if not witnessed:
        print("no complete chain: waypoint generation remains unresolved, and "
              "the honest reading is that this class or this budget does not "
              "contain one -- not that the loop needs more iterations.")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
