# Findings

Empirical results and gotchas established by experiment, with the evidence. Read
this before designing a run — several of these cost a day each to discover, and
two of them invalidate experiments that look reasonable.

## Toolchain

**twee must be built against jukebox < 0.5.12.** twee 2.6.1 declares
`jukebox >= 0.5.9` with no upper bound; jukebox 0.5.12 added a field to the
`Inference` constructor, so an unconstrained `cabal install twee` fails to
compile `executable/SequentialMain.hs`. Use
`cabal install twee --constraint='jukebox < 0.5.12'`.

**Released twee 2.6.1 supports hints.** No fork needed. The flags are hidden
behind `--expert-help`: `--hint-skel-factor`, `--hint-skel-cost`, `--resonance`.

## Measurement

**twee exits 0 whether or not it found a proof.** The outcome is on the final
`RESULT: <status>` line. Only `Unsatisfiable` and `Theorem` mean a proof;
`Satisfiable`/`CounterSatisfiable` mean it saturated, `GaveUp`/`Timeout` mean it
stopped. Checking the exit code alone silently counts saturations as successes —
which matters most on UNK/OPN problems, where saturation is exactly what might
happen. Use `twee_found_proof()`.

**Screen at a realistic budget or not at all.** A `--max-time 30` screen called
ROB026-1 and ROB033-1 unsolved; they need **419s** and **782s**. Three separate
experiment designs were built on that bad screen before it was caught.

**Goal direction can decide everything.** ROB026-1: solved in 419s with
`--no-flatten-goal`, `GaveUp` with `--flatten-goal`. Same for ROB033-1 (782s vs
GaveUp). Single-direction screening produces confident false negatives.

**Always run the baseline in the same batch.** Several results here were
uninterpretable until a paired no-hint run existed. A hinted run that fails at
300s says nothing if the baseline needs 419s.

## Hints

**`--hint-skel-factor 0` is actively harmful.** Measured four independent times:

| experiment | effect |
|---|---|
| 56 large hints, factor 0 | **zero rules derived** in 300s |
| 227 donor hints, factor 0 | 2.1x slower than no hints (897s vs 419s) |
| 45 oracle hints, factor 0, ROB005-1 | 2.8x and 6.7x slower |
| same 45 hints, factor 0.5 | **3.3x and 1.8x faster** |

Hint cost is `(len - nvars) * skel_factor + skel_cost + dup_penalty`
(`Twee.hs:618`). At factor 0 a hint costs nothing, so any critical pair matching
a large hint scores ~0 and monopolises the queue. **Use factor 0.5.** Note the
repo's `hints_17-11` grid and several `hard_*` configs use factor 0.

**Hint set size matters as much as content.** 43 hints neutral, 227 hints 2.1x
slower. Twitch's own wins used 9-33 hints. Stay in that range.

**Hints whose symbols are absent from the problem are inert, not harmful.**
Measured: 821ms vs 844ms baseline (no effect); a useful hint gives 252ms. So an
untranslated transfer produces a *fake negative* — the intervention simply does
not exist. Variabilise donor-specific symbols (goal-flattening Skolems `g`, `h`)
before transferring.

**`V1`/`V2`-style names are valid TPTP variables** and behave identically to
`A`/`B` (239ms vs 244ms), so variabilisation can mint fresh names freely.
`normalize_fof_term` only recognises single-letter variables, so it will not
alpha-normalise them — harmless, but it weakens deduplication.

## Search behaviour

**91–98% of derived rules never appear in the proof.**

| corpus | derived | used | waste |
|---|---|---|---|
| A0 hinted ROB (4) | 10,990 | 160 | 98.5% |
| GRP (369) | 121,175 | 10,592 | 91.3% |
| LAT (52) | 39,022 | 1,748 | 95.5% |
| COL (79) | 11,234 | 273 | 97.6% |

Used rules sit at median derivation position **0.01–0.08** of the run; unused at
**0.51–0.54**. Score separates the two only weakly and theory-dependently: an
oracle cap at the highest used score prunes 80% of work on hinted ROB runs but
~0% on LAT.

Caveat: "used" means referenced in the final post-processed proof, so rules that
contributed by simplification are miscounted as waste. Also measured only on
successful runs.

**twee has resource limits and they default to unlimited** — `--max-term-size`,
`--max-cps`, `--max-cp-depth`, `--max-rules`. Every EQP run in McCune's Robbins
work sets `max_weight` (21, 30, 34, 50, 60, 70, 100). None of the 4538 configs
in the twitch repo set any limit.

## Corpora

**TPTP UEQ**: 1455 problems (1140 UNS, 260 SAT, 48 UNK, 7 OPN); 156 rated >= 0.9.
The nine theories the paper uses total exactly 1041, excluding ETP.

**ETP**: 22,033,636 implication pairs, but 99.97% of the proven ones solve in
under a second (median 0.023s; only 2407 exceed 1s, 4 exceed 60s). The value is
the ~2400 non-trivial ones plus 1062 Vampire could not resolve — the latter being
a frontier eval set ~19x larger than TPTP's UNK+OPN.

**TSTP** has no proof of ROB001-1, ROB031-1 or ROB007-1 from any system (only
Infinox, which proves the domain infinite). It runs at competition limits; EQP
needed 678,232s on Robbins. Dense on easy/medium problems, empty at the frontier.
E-family derivations are structured TPTP and harvest directly; Waldmeister and
Vampire entries are raw system output.

**Robbins ladder** (each rung derives the next condition, not Boolean-ness):

| McCune | statement | TPTP | base twee |
|---|---|---|---|
| Lemma 2 | Robbins + `n(C+D)=n(C)` |- exists A,B. A+B=A | — | — |
| Lemma 1 | Robbins + exists C,D. C+D=C |- exists x. x+x=x | — | — |
| Lemma 0 | Robbins + exists C. C+C=C |- Huntington | ROB005-1 | 10.5s |
| — | Robbins + (c+d=c) |- Huntington | ROB026-1 | 419s |
| — | Robbins |- Huntington | ROB001-1 | unsolved |

ROB007-1 (UNK) is Lemma 2 composed with 1 and 0 — the full chain, which is why
no prover has done it.

## Corrected ROB frontier (~950s CPU, both goal directions)

Resist: ROB001-1, ROB006-1, ROB031-1, ROB032-1, ROB007-1, ROB020-1, ROB024-1,
ROB027-1. Solvable: ROB026-1 (419s), ROB033-1 (782s), both `--no-flatten-goal`.

## Data hygiene

11 of the 1027 `ETP_UEQ_UNSAT` files in the twitch repo are implications Vampire
*refuted* (at 430-540s) — satisfiable, in a directory labelled UNSAT, unprovable
by construction.

`hard_successes/*.json` records winning configs but no baselines and no failures,
so it is not usable as a training source without regeneration.

## Open

Whether McCune's Lemma 2 hints can drive twee through Lemma 2 is **unresolved**.
The first sweep used factor 0/0.2/0.5 but had no baseline and predates the
finding that factor 0 is pathological; the `0.5` arms were killed without
flushing. Rerun with factor 0.5 and a paired 1000s baseline before concluding
anything. The AC-association question is also open: EQP hints are AC-flattened
(`x+y+z`) and the translator picks one association, so some hints may never match.
