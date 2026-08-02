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

**Every cabal build needs libgmp.so, not just libgmp.so.10.** GHC links Integer
against GMP. Shared clusters routinely ship the runtime without the development
symlink from `gmp-devel`, and then *every* package fails at link time with
`/usr/bin/ld: cannot find -lgmp` -- starting with `alex`, so the error appears
long before twee and looks like a twee problem. Without root:
`conda install -c conda-forge gmp`, then pass
`--extra-lib-dirs=$CONDA_PREFIX/lib` to cabal.

**Pin GHC to 9.6.7.** It is the version these results were built on. Newer GHC
(9.10.x) pulls a newer `base` that twee's older transitive dependencies
(`symbol`, `uglymemo`) were never updated for.

**Released twee 2.6.1 supports hints.** No fork needed. The flags are hidden
behind `--expert-help`: `--hint-skel-factor`, `--hint-skel-cost`, `--resonance`.

## Reproducibility

### The mechanism, isolated

**Interreduction is scheduled by elapsed CPU time, so it fires at a different
point in the derivation on every run, and the search diverges from exactly that
point.** Demonstrated on REL029-1 (1.9s, 6 runs, byte-identical input):

| run | rules derived | interreduce fired after rule |
|---|---|---|
| r0 | 1690 | 1151 |
| r1 | 1690 | 1153 |
| r2 | 1684 | 1146 |
| r3 | 1697 | 1143 |
| r4 | 1697 | 1139 |
| r5 | 1680 | 1145 |

Across all **15 pairs of runs**, the first differing derived rule is *exactly*
one after the earlier run's interreduce point — 15/15, no exceptions. The runs
are bit-identical before it and divergent immediately after.

The causal chain is therefore complete:

1. `newTask 1 0.05 $ ... interreduce ...` fires when `getCPUTime` says enough
   time has passed (`Twee/Task.hs:taskDue`).
2. Machine load and cache state decide which derivation step that lands on.
3. `interreduce` rewrites rules with respect to one another, changing the rule
   set and hence which critical pairs exist and how they score.
4. Every subsequent choice differs.

**Confirmed by removing it.** `--no-simplify` disables interreduction, and the
run becomes perfectly deterministic:

| flags | rules derived over 4 runs | cpu |
|---|---|---|
| default | 1691, 1690, 1689, 1690 | 1.86–1.88s |
| `--no-simplify` | **1222, 1222, 1222, 1222** | 1.15–1.16s |
| `--always-simplify` | 2481, 2481, 2484, 2481 | 92.9–93.1s |

`--always-simplify` (interreduce after every step) is *nearly* deterministic but
not quite, so the other CPU-time-scheduled tasks — `simplifyQueue`,
`recomputeGoals`, `checkCompleteness` — contribute a smaller share of the same
effect. Interreduction is the dominant term.

**`--no-simplify` is not a usable fix.** It buys determinism by disabling
interreduction entirely, which is cheap on REL029-1 (1.6x *faster*, 1222 rules
vs ~1690) and ruinous where interreduction is load-bearing: on MVA006-1 it ran
past **1200s per attempt against a stock range of 94–245s**, i.e. at least 5x
slower and probably non-terminating at any budget we would use. Abandoned.

**Scheduling by step count instead of CPU time does work.**
`build/twee-deterministic` patches `Twee/Task.hs` to fire tasks off a per-task
count of `checkTask` calls — the same two conditions (minimum gap, fraction of
iterations spent) in step units rather than picoseconds, with a
`TWEE_STEPS_PER_SECOND` constant converting the existing frequencies. On
REL029-1, 5 runs each:

| steps/sec | rules | cpu | |
|---|---|---|---|
| 1,000 | 2083 | 4.16s | deterministic |
| 3,000 | 2344 | 3.95s | deterministic |
| **10,000** | **1559** | **1.54s** | **deterministic, 1.24x faster than stock** |
| 30,000 | 1222 | 1.12s | deterministic (interreduce never fires) |
| stock | 1680–1697 | 1.90s | varies |

Every setting is bit-reproducible. Two caveats before treating this as the
default: a step schedule interreduces at different *moments* than a time
schedule, so it is a different prover configuration and every timing in this
file would need re-baselining against it; and REL029-1 is a 1.9s problem, so
whether determinism survives where interreduction is load-bearing is a separate
question.

This also explains why the effect looks so violent on some problems and not
others. It is not that timing noise accumulates: a single scheduling difference
forks the search once, and from there the two runs explore different spaces.
Whether that costs 1% or 3x depends on whether the fork happens to land near the
proof.

### The original observation

**twee's search is not reproducible run to run, because its maintenance work is
scheduled by CPU time.** `Twee.hs:824-848` registers tasks with `newTask`, and
`Twee/Task.hs` fires them off `getCPUTime`:

```haskell
newTask 10 (renormalise_percent/100) $ ... simplifyQueue ...
newTask 1  0.02 $ ... checkCompleteness ...
newTask 1  0.05 $ ... interreduce ...        -- rewrites the rule set
newTask 1  0.02 $ ... recomputeGoals ...
```

`interreduce` and `simplifyQueue` change the rule set and the critical-pair
queue, so *when* they fire changes what the search does next. The inference
rules are deterministic; the schedule is not. `cfg_random_mode` is off by
default and is a red herring — this is a separate mechanism.

Measured with byte-identical inputs (same md5), same binary, same flags,
sequential runs, 5 repeats:

| problem | cpu mean | cpu cv | cpu spread | distinct rule counts (of 5) |
|---|---|---|---|---|
| REL029-1 | 1.88s | 0.55% | 1.44% | 3 |
| LAT190-10 | 23.49s | 0.51% | 1.24% | 5 |
| **MVA006-1** | 191.73s | **67.68%** | 160.62% | 5 (8782 … 15862) |
| **GRP666-5** | 186.06s | **26.37%** | 63.47% | 5 (20785 … 24979) |

**Variance is strongly problem-dependent, and large where it matters.** The two
fast problems are stable to ~0.5%; the two slow ones are not, and MVA006-1
ranges over a factor of 2.6 in runtime and 1.8 in rules derived. The plausible
mechanism is positive feedback: a slightly different `interreduce` moment
changes the rule set, which changes the timing, which shifts the next
maintenance window.

Four consequences:

- **On fast problems, single-run timings are reliable** to a couple of percent.
  On slow ones they are close to meaningless — report mean+-sd over n>=5 via
  `overtone.runner.summarise`.
- **Outcomes near a budget boundary can flip.** A problem finishing at 118s
  against a 120s cap may time out on a rerun. Donor lemma 270 in the MVA005-1
  ladder did exactly this (118.2s proved, 120.2s failed); it was attributed to
  directory contamination and is at least partly this instead.
- **Derived-rule sets are a nondeterministic sample**, so the derived-vs-used
  labels behind `scripts/rule_usefulness.py` come from one arbitrary run. The
  91-98% waste figures are approximate, not exact.
- **Screen timings and near-serial timings are not comparable.** GRP666-5 was
  recorded at 396.0s in the 16-worker screen but averages 186.1s run solo -- a
  2.1x gap. Contention does not just add clock time, it changes which searches
  happen.

Comparisons across different machine loads are also suspect: the screens ran at
16-24 concurrent workers while the ablation and ladder experiments ran nearly
serial, so their task schedules differ systematically, not just their clocks.

`overtone/runner.py` exists to make this auditable: every run allocates its own
directory with an atomic `mkdir` and stores its input, output, parsed result and
exact command together, so no two runs can share a path and every number is
traceable to the bytes that produced it.

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

## Replication

**Our setup reproduces Twitch's best recorded result on ROB034-1.** Rated
UNS@1.00. Recorded 30.1s with 33 hints at `--hint-skel-factor 0.2 --flatten-goal`;
we get **24.7s CPU** with the same hints and flags — 0.82x, i.e. slightly faster
hardware, no configuration gap. Reproduce with
`./scripts/replicate_twitch.py ROB034-1 --rank 0 --baseline`.

Two things this pinned down that the stored configs do not state:

Twitch appends `--kbo-weight0-unary --print-score` to *every* twee invocation
(`twitch/src/utils.py:22`) and neither appears in any stored config. Any run
meant to be comparable to the paper's numbers must include them.

**The paired baseline, which `hard_successes` never recorded, is a timeout.**
ROB034-1 does not prove without hints in 1000s at `--flatten-goal`. So the hint
effect here is not a ratio — it is unsolvable to 24.7s. Note this is one goal
direction only; `--no-flatten-goal` baseline is untested and the screen will
settle it.

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

**TPTP UEQ**: 1455 problems (1140 UNS, 260 SAT, 48 UNK, 7 OPN); 156 of the UNS
rated >= 0.9. Reproduced offline by `make_ueq_list.py` from the `% SPC :` headers
of v9.2.1, which agrees with these counts exactly. The nine theories the paper
uses total 1040 UNS, not 1041 — see the GRP740-1 note under Data hygiene.

**ETP**: 22,033,636 implication pairs, but 99.97% of the proven ones solve in
under a second (median 0.023s; only 2407 exceed 1s, 4 exceed 60s). The value is
the ~2400 non-trivial ones plus 1062 Vampire could not resolve — the latter being
a frontier eval set ~19x larger than TPTP's UNK+OPN.

**Veroff's archive is the only source of human oracle hints at the frontier.**
Fetched 2026-07-31 from `cs.unm.edu/~veroff`: 446MB, 175 `.in` files (168
carrying `list(hints)`/`formulas(hints)`, ~2.38M hints total) and 196 `.pf`
proofs, across AIM loops, BA, CD, LT, GMV, HBCK, MEDIAN_ALGEBRA, LOOPS and
ROBBINS. AIM_REDONE dominates: single inputs reach 1.3MB of hints and one proof
is 143MB.

Two consequences for use. These hint sets are 3-5 orders of magnitude larger
than the 9-33 range where Twitch's wins live, so they are a pool to select from,
not a set to pass through. And they are Otter/Prover9 syntax, so they need
`overtone/otter.py` and inherit its open AC-association question.

`ROBBINS/r2h.in` is a demodulation-free Otter check of the Robbins-to-Huntington
derivation at `max_weight 5` — a second, independent hint list for the same
frontier the McCune files target.

**TSTP** has no proof of ROB001-1, ROB031-1 or ROB007-1 from any system (only
Infinox, which proves the domain infinite). It runs at competition limits; EQP
needed 678,232s on Robbins. E-family derivations are structured TPTP and harvest
directly; Waldmeister and Vampire entries are raw system output.

**Measured TSTP coverage: it collapses exactly where we need it.** Harvested
2026-07-31 over all 1140 UEQ UNS problems x 5 E-family systems: 3990 derivations,
29MB, 930 problems (81.6%) with at least one. By difficulty:

| rating | UNS problems | with a TSTP donor | coverage |
|---|---|---|---|
| < 0.3 | 665 | 665 | 100% |
| 0.3–0.7 | 179 | 174 | 97.2% |
| 0.7–0.9 | 140 | 82 | 58.6% |
| **>= 0.9** | **156** | **9** | **5.8%** |

The nine are CSR040-10, CSR065-10, GRP721-1, GRP771-1, LAT400-1, LAT400-2,
LCL060-10, LCL390-10, ROB033-1.

This is a structural constraint on the whole hint-mining line, not a gap to fill
by crawling harder — TSTP runs at competition time limits, so the frontier is
absent by construction. Consequences:

- There are no same-problem donors at the frontier. Every frontier hint must come
  from *transfer* off easier problems, which is exactly what Twitch's
  `veroff_hints` method does at axiom similarity >= 0.9.
- Donor material and evaluation targets are therefore drawn from different
  difficulty distributions. Any hint-mining model trained on TSTP is trained
  almost entirely on the easy band and evaluated on a band where its input
  channel is 94% empty. Treat that shift as a first-class design problem, not a
  detail of the split.
- It raises the value of `data/external/veroff/`, which is the only corpus we
  have that *is* at the frontier.

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

## High-budget baseline screen (2026-08-01)

296 UNS problems rated >= 0.7, both goal directions, 1000s each, no hints. 592
jobs in 6.21h wall. Raw results in `logs/screen/results.jsonl`, tables in
`docs/RUNS.md`.

**175 solved, 121 resisted.** By rating band:

| rating | n | solved | rate |
|---|---|---|---|
| 0.7–0.79 | 82 | 65 | 79.3% |
| 0.8–0.89 | 58 | 50 | 86.2% |
| 0.9–0.99 | 71 | 42 | 59.2% |
| **1.00** | **85** | **18** | **21.2%** |

**18 of the 85 problems rated 1.00 fall to a plain baseline run.** No hints, no
learning — correct goal direction and 1000s. Ten of the eleven 1.00-rated MVA
problems solved (all but MVA005-1), plus GRP724-1, LAT074-1, LAT077-1, LAT161-1,
LAT229-10, LCL927-10, REL039-1 and ROB033-1. A TPTP rating of 1.00 means no
state-of-the-art system solves it under the *rating's* time limit; at 1000s with
the right direction, twee does, for a fifth of them.

**Goal direction decides 67 of the 175 solved problems** — 33 solve only with
`--flatten-goal`, 34 only with `--no-flatten-goal`. A single-direction screen
would have produced up to 34 false negatives. This is the largest single effect
measured anywhere in this file, and it is a configuration effect, not a
guidance one.

**The 1000s cap is still truncating.** 22 problems solved between 300s and 846s
and 9 above 600s, with ROB033-1 the slowest at 845.7s. The solved-time
distribution has not flattened at the cap, so a 2000–4000s screen would very
likely convert more of the 121 resisted. Settle that before attributing anything
to guidance.

### Screen analysis

**Solve rate varies enormously by theory, and TPTP rating does not explain it.**

| domain | n | solved | rate |
|---|---|---|---|
| REL | 39 | 39 | **100%** |
| MVA | 15 | 14 | 93.3% |
| LAT | 55 | 51 | 92.7% |
| GRP | 57 | 32 | 56.1% |
| LCL | 39 | 19 | 48.7% |
| ROB | 13 | 5 | 38.5% |
| **RNG** | **17** | **1** | **5.9%** |
| PLA/SYN/ANA/MSC/PUZ | 17 | 0 | 0% |

REL's 39 problems are rated 0.70–1.00 and twee's median solve time on them is
**1.1s**. RNG's 17 span the same rating range and twee solves one. The rating is
computed across all systems; twee's difficulty profile is a different function.

**TPTP rating is a weak per-problem predictor of twee's runtime**: Pearson r =
0.18 over the 175 solved. Band medians do order correctly — 4.9s, 23.3s, 47.7s,
123.5s for 0.7–0.8, 0.8–0.9, 0.9–1.0, 1.00 — so rating is usable for coarse
stratification and useless for per-problem prediction. Stratify eval by twee's
own measured times, not by rating.

**Goal direction matters less than the headline suggests, and a trivial rule
captures most of it.** 108 of 175 solved problems (62%) solve in both
directions, so direction decides only 67:

| policy | solved | cpu |
|---|---|---|
| run both directions | 175 (100%) | 2x |
| best single fixed direction | 142 (81%) | 1x |
| **best per-theory rule** | **160 (91%)** | **1x** |
| perfect per-problem oracle | 175 (100%) | 1x |

So the value of direction selection is a ~2x CPU saving, not more problems
solved, and a per-theory lookup table already banks most of it. The headroom for
a *learned* per-problem chooser is 15 problems, 9%. This qualifies the
"configuration prediction should be line of work #1" argument in
`EXPECTATIONS.md`: the effect is real and large, but the cheap version captures
91% of it.

**The 121 resisted problems concentrate where we have the least donor material.**
GRP 25, LCL 20, RNG 16, ALG 8, ROB 8, PLA 7, CSR 6, COL 5, KLE 5, LAT 4, SYN 4,
rest <= 2. Only 16 of 119 (13.4%) have any TSTP donor. RNG is the worst served:
16 resisted, 1 donor, and no Veroff material in that theory at all.

### Verifying the screen's proofs

Every proved result in the screen is `Unsatisfiable`, with no `Theorem` and no
other status. That is correct by construction and was checked rather than
assumed:

- The screen list is 296 problems filtered on `$3=="UNS"`, so it contains only
  problems TPTP records as unsatisfiable. They are CNF (`CNF_UNS_RFO_PEQ_UEQ`),
  and twee reports `Unsatisfiable` for CNF refutations and `Theorem` only for FOF
  conjectures — so `Theorem` cannot appear here.
- **Ground truth cross-check: all 296 carry both `% Status : Unsatisfiable` and
  `SPC : CNF_UNS_*`, zero disagreements.** Not a vacuous check — GRP740-1 (see
  Data hygiene) shows these two fields *can* contradict each other.
- Saved proofs are real derivations — rewrite chains with named axiom citations
  (`= { by axiom 2 (permute2) R->L }`), not stubs.
- **Negative control**: twee run on the 260 SAT UEQ problems, same flags, both
  directions. It must saturate and must never claim a proof. Partial result at 57
  of 520 jobs: 27 `Satisfiable`, 30 `Timeout`, **0 false proofs**.

The all-Unsat pattern is therefore a property of the problem selection, not
evidence of a systematic error. Worth restating because the concurrency bug below
shows how convincingly a broken pipeline can fabricate plausible statuses.

### Score-bound headroom, measured over 283 screen proofs

For each solved problem: take the highest `--print-score` value of any rule that
appears in the final proof, and ask what fraction of derived rules scored above
it. That is an oracle bound on any score-bounded search.

Median **58.6%** of derived rules prunable, mean 49.0%. 115 of 283 problems above
80%. But the aggregate hides the important structure:

| theory | n | median prunable | screen solve rate |
|---|---|---|---|
| CSR | 4 | 98.5% | 25.0% |
| LCL | 25 | 95.4% | 48.7% |
| ROB | 6 | 92.4% | 38.5% |
| MVA | 26 | 88.2% | 93.3% |
| COL | 5 | 76.0% | 44.4% |
| REL | 69 | 29.0% | 100% |
| LAT | 85 | 18.0% | 92.7% |
| GRP | 52 | 18.0% | 56.1% |

**The inversion matters: score bounds have the most headroom exactly where twee
is currently worst.** LCL, ROB and CSR are three of the four lowest solve rates
in the screen and three of the four highest pruning potentials. REL and LAT,
where twee already solves ~everything, are where a bound buys least. This is the
opposite of the usual pattern where a technique helps most where you are already
strong.

Absolute scores: the highest *used* rule has median score **55** (p90 83); the
highest *explored* rule has median 90 (p90 150). Twee overshoots the useful
score range by only 1.65x in the median — but because rule count grows steeply
with score, that 1.65x is 58% of the rules.

**This brackets McCune's hand-tuned Robbins ladder.** Every EQP run in his
Robbins work set `max_weight` — 21, 30, 34, 50, 60, 70, 100 — and our measured
median used-cap of 55 sits in the middle of it. None of the 4538 configs in the
twitch repo set any limit.

Two caveats, both load-bearing. This is an **oracle**: it assumes you know the
cap. And it is measured **only on solved problems**, which is a selection effect
— the 121 resisted may have entirely different structure, and they are the
population we actually care about. Iterative deepening sidesteps the first
(saturate under a bound, raise it, repeat) but not the second.

### Twitch's 19 hard problems all resist our baseline

The paper is Axelrod, Johansson & Smallbone, *Twitch: Learning Abstractions for
Equational Theorem Proving*, IJCAR 2026 ([arXiv:2603.06849](https://arxiv.org/abs/2603.06849)).
Note Smallbone is twee's own author, which is worth remembering whenever this
repo characterises twee's maturity or its abstraction mechanism.

`hard_successes` records 19 distinct problems. Checked against our screen:
**0 of 19 are solved by the no-hint baseline at 1000s in either goal direction.**
All 19 are in our resisted set.

This supplies the paired baseline their stored data never recorded (see Data
hygiene) and independently validates the result: those problems are genuinely
beyond baseline twee at the same budget with both directions tried. It also means
our 18 baseline-solved rating-1.00 problems are a *disjoint* set from theirs —
the two results add up rather than competing.

### 4000s screen: 14 more flips, and what they cost us

The 121 problems that resisted at 1000s, rerun at 4000s in both directions
(11.11h, 242 jobs). **14 flip (11.6%)**, all by budget alone:

| problem | rating | cpu | direction | note |
|---|---|---|---|---|
| MVA005-1 | 1.00 | 312.6 | --no-flatten-goal | sketch target |
| BOO014-10 | 0.78 | 1302.2 | --no-flatten-goal | |
| LCL231-10 | 0.83 | 1406.4 | --flatten-goal | sketch target |
| GRP693-1 | 0.83 | 1557.2 | --no-flatten-goal | |
| LAT075-1 | 1.00 | 2028.7 | --no-flatten-goal | **Twitch-19** |
| GRP694-1 | 0.78 | 2031.5 | --no-flatten-goal | |
| GRP689-1 | 0.70 | 2467.8 | --flatten-goal | |
| RNG027-10 | 1.00 | 3271.1 | --no-flatten-goal | |
| COL002-10 | 0.70 | 3448.6 | --no-flatten-goal | |
| RNG027-5 | 0.96 | 3555.6 | --no-flatten-goal | |
| LCL348-10 | 0.96 | 3690.2 | --flatten-goal | **Twitch-19** |
| LCL054-10 | 0.83 | 3728.0 | --flatten-goal | sketch target |
| LAT138-1 | 0.70 | 3817.7 | --flatten-goal | sketch target |
| RNG028-5 | 0.96 | 3825.8 | --no-flatten-goal | |

Three consequences, all of which cost us claims made earlier in this file.

**MVA005-1 falls to a plain baseline in 312.6s, faster than any hinted run.**
The sketch-transfer flip is therefore not a flip at all: at 1000s the problem
looked hint-only because the 1000s baseline used `--no-flatten-goal` and timed
out, but with 4000s the same direction solves it in 312.6s. The hinted runs
(546.8s flat, 173.6s ladder-as-hints) were solving an already-solvable problem.
The ladder-as-hints result is still a real 1.8x speedup over plain baseline, but
**"sketch transfer flipped a 1.00-rated problem" is withdrawn.**

**Three of our four sketch-transfer "nulls" were budget, not bad hints.**
LCL054-10, LCL231-10 and LAT138-1 all prove at 4000s unhinted. The hint-firing
instrumentation showed 18 firings in 600s on LCL054-10, which is still true and
still means the hints were inert — but the problem was never a hint problem.

**Two of Twitch's 19 hard problems fall to an unhinted baseline at 4000s**:
LAT075-1 (2028.7s) and LCL348-10 (3690.2s). Their paper's budget was 1000s, so
this is not a contradiction of their result, but it does mean 2 of the 19 are
budget-limited rather than requiring abstractions. The remaining 17 still resist
at 4000s in both directions.

**Three RNG problems flip** (RNG027-10, RNG027-5, RNG028-5), the domain with a
5.9% solve rate at 1000s and no donor material of any kind. Budget reaches where
we had no other lever.

The screen list should be regenerated: the resisted set is now **107**, not 121.

### Sketch transfer v0: 1 flip in 8

Donor-proof hints for resisted problems, no LLM: the sketch is the proof of the
most axiom-similar *solved* sibling, hints are that proof's intermediate
rewrite-chain terms adapted to the target signature
(`scripts/sketch_transfer.py`, design in `docs/SKETCH_LOOP.md`). Eight targets,
all disjoint from the 19 Twitch already solved, all Timeout in both directions
in the 1000s baseline screen.

**MVA005-1 (rated 1.00) proved in 547s with 25 hints from MVA001-1**
(similarity 1.000), `--no-flatten-goal`. It was the one 1.00-rated MVA problem
the baseline screen could not take, having solved the other ten. The paired
baseline was recorded before the hinted run, so budget-and-direction — the
hypothesis behind the other 21 flips in this file — is excluded.

The other seven produced no proof: GRP673-10, GRP674-11, KLE096-10 (all 1.00),
LCL054-10, LCL231-10 (0.83), COL003-1 (0.74), LAT138-1 (0.70).

Two caveats. The null results do not distinguish **bad hint content** from
**hints that never fired** — LCL054-10 and LCL231-10 had similarity-1.000 donors
and still failed, which is the signature expected from the demodulation leak
Twitch's §7 describes. Hint-firing instrumentation is a prerequisite for
interpreting any further null. And MVA005-1 has not yet been reached by the
4000s screen; if plain baseline takes it at 4000s, the claim weakens from "hints
flipped it" to "hints flipped it ~7x cheaper".

### Hint firing, measured directly

Hints are matched inside `CP.score`, which runs on every critical pair scored --
including ones never kept -- so firing is invisible in twee's normal output.
twee's author wrote a `trace` at that exact site and commented it out
(`Twee/CP.hs:261`). `scripts/build_instrumented_twee.sh` restores it as a
counter, in a **separate binary**: 300M+ counter updates is not free, and stock
twee must stay authoritative for timings.

Run it with `--max-time N`, never an external timeout — the stats print on the
normal exit path, so a SIGKILLed run reports nothing.

First measurements, on the v0 sketch-transfer examples:

| problem | outcome | rules derived | hints fired | distinct hints firing |
|---|---|---|---|---|
| MVA005-1 | proved (stock, 547s) | 13,825 | **316,610,998** | 25 of 25 |
| LCL054-10 @600s | GaveUp | 25,692 | **18** | 9 of 25 |
| LCL231-10 @120s | GaveUp | 14,191 | 19 | 9 of 25 |

**LCL054-10 fired 18 times at 120s and still exactly 18 at 600s** — zero
additional firings across ~19,500 further derived rules. The hints engaged at
the very start and never again.

**The cause is hint generality, not the demodulation leak.** Hint term sizes:
MVA005-1 median 5 symbols with 12 of 25 at <= 3 (`op(X, Y)`, `join(X, unit)`);
LCL054-10 median 15, max 32, **none** below 4. Tiny two-variable hints match
almost every subterm; deeply-nested `ifeq(...)` hints from LCL-10 encodings match
almost nothing. This is a cleaner explanation than brittleness-by-rewriting, and
this data does not demonstrate the demodulation leak either way.

MVA005-1's firing profile is dominated by generic hints — `join(X, Y)` 82M,
`meet(X, Y)` 77M, `ld(X, Y)` 62M — while the specific transferred structure
fired rarely (36 times for `meet(rd(ld(X, Y), Z), ld(X, rd(Y, Z)))`, once for
the largest). That raised the worry that the flip was a blanket size discount
close to the `--hint-skel-factor 0` pathology rather than real transfer.

**Ablation says otherwise.** Same problem, direction and budget, hints split at
<= 3 symbols:

| arm | hints | result | cpu |
|---|---|---|---|
| no hints (screen baseline) | 0 | Timeout, both directions | > 1000s |
| generic only (<= 3 symbols) | 12 | **Timeout** | 1001.6s |
| specific only (> 3 symbols) | 13 | **Unsatisfiable** | 852.9s |
| full set | 25 | **Unsatisfiable** | 546.8s |

The generic hints alone cannot solve it; the specific ones alone can. **The
transferred structure is doing the work**, and the flip stands as real transfer.
The generic hints are not useless either — adding them takes 852.9s down to
546.8s, a further 1.6x — but they are accelerant, not mechanism. Note also that
firing count is a terrible proxy for value: the 62M-firing hints are the
dispensable ones.

**The extraction bug is real but subtler than it looked.** `overtone/agent/hints.py:build_hints` ranks
by occurrence count in the donor proof, which favours generic terms. Here the
cap of 25 happened to admit 13 specific hints alongside 12 generic ones, so the
structural content survived by luck. **A tighter cap would have kept only
generic hints and lost the problem.** Rank for specificity so structural hints
survive the cap, then add generic ones as accelerant if budget allows.

### twee's hint cost is inversely related to informativeness

Cost is `(len - #var_occs) * skel_factor + skel_cost + (#var_occs - #distinct)`
(`Twee.hs:618`), i.e. it grows with the number of function symbols. So the
*cheapest* hint — the one whose match buys the biggest discount — is the most
generic one. MVA005-1's 25 hints at factor 0.5:

| cost | hint | fired |
|---|---|---|
| 0.5 | `join(X, Y)` | 82,012,749 |
| 0.5 | `meet(X, Y)` | 76,543,950 |
| 0.5 | `ld(X, Y)` | 62,139,237 |
| ... | ... | ... |
| 5.0 | `op(X, op(ld(X, unit), ld(ld(Y, unit), unit)))` | 1 |
| 5.5 | `meet(rd(ld(X, Y), Z), ld(X, rd(Y, Z)))` | 36 |

**The ablation showed the cost-5.5 cohort is what makes the problem solvable and
the cost-0.5 cohort cannot solve it at all.** The formula assigns the largest
discount to the dispensable hints and the smallest to the load-bearing ones.

A single `--hint-skel-factor` governs both, so there is no setting that is right
for both roles: lower it and generic hints monopolise the queue (the factor-0
pathology), raise it and the specific waypoints get discounted least of all.
Treating "hints" as one channel is the underlying design error.

`--resonance` (restrict hint substitutions to variable-to-variable) is the
obvious control for over-general hints and is untested here.

### MVA005-1 as a ladder

Waypoints as sequential *goals* rather than simultaneous hints
(`scripts/ladder.py`). 22 separate twee runs: rungs 1..21 each have one donor
lemma as their goal, with the theory axioms plus previously proven rungs as
axioms; the final run has the original conjecture with every proven rung
available.

**This is a lemma library, not a proof sketch.** The rungs are intermediate
lemmas from the *donor's* proof (MVA001-1, goal `at(x, x) = x`), so they are
lateral facts about the theory, not progressive approximations of the target
goal (`at(join(x,y), join(z,u)) = join(at(x,z), at(y,u))`). Veroff's method
weakens *the same* conjecture and eliminates assumptions one at a time, so its
rungs converge on the target. That version is still unimplemented, and it is the
one `docs/SKETCH_LOOP.md` actually argues for.

| arm | result | cpu |
|---|---|---|
| no hints (screen baseline) | Timeout, both directions | > 1000s |
| accelerants only (12) | Timeout | 1001.6s |
| waypoints as hints (13) | proved | 852.9s |
| full hints (25) | proved | **546.8s** |
| ladder final, 20 lemmas as **axioms** | **Timeout** | 1001.7s |
| ladder final, same 20 lemmas as **hints** | proved | **173.6s** |

**Same content, opposite outcome, decided purely by the delivery mechanism.**
As axioms the final goal times out; as hints it proves in 173.6s — 3.1x faster
than the best flat hint set (546.8s) and the fastest result on this problem by a
wide margin.

An added axiom enlarges the rewrite system: it forms critical pairs with every
existing rule, so 20 of them blow up the search space. A hint only reweights
scoring and adds no inference obligations. **"Sound and strictly stronger" is
true logically and false operationally.** Never promote proven lemmas as axioms.

**Verified lemma equations also beat rewrite-chain terms as hint content**
(173.6s vs 546.8s), which is what the ladder is really for: it converts
unverified donor terms into checked equations.

End-to-end accounting, rungs 365.6s + final 173.6s = **539.2s**, against 546.8s
for the flat set whose hints came free — near parity. But two things favour the
ladder: 120.3s of the rung cost is the single failing rung, which a refiner
would subdivide rather than burn full budget on (418.9s without it), and **the
20 verified lemmas are theory-level assets reusable across every MVA problem**,
whereas flat hints are re-extracted per target. Amortised over a theory, the
ladder's 3.1x on the final run is what counts.

What the ladder does buy is **localisation**: exactly one rung fails,
`meet(rd(ld(X, Y), Z), ld(X, rd(Y, Z))) = ld(X, rd(Y, Z))` (donor lemma 227), so
a refiner knows precisely which step to subdivide. No flat run yields that.
The open question is whether that signal can be obtained without paying the
axiom-blowup cost — i.e. by promoting proven rungs as *hints* rather than
axioms.

**Rung cost profile: 13 of 21 rungs cost 2.2s combined**, the rest concentrated
in 8 hard lemmas. So there is no fixed per-rung re-entry tax — cold-start
rediscovery of base theory is not where ladder time goes. Any rediscovery is of
the unnamed intermediate rules twee builds toward each hard rung, which passing
proven lemmas forward does not share; that is measurable by saving rung outputs
and diffing derived-rule sets, and has not been done.

**The rung count is now 20, not 21.** Rung selection matched waypoints against
donor lemmas using a normaliser that replaced every variable with `*`, so
`f(X,Y)` compared equal to `f(X,X)` and one lemma matched spuriously. Fixed in
the refactor (`terms.alpha_key`). The numbers above were measured with the
21-rung ladder and have not been re-run; the extra rung was one of the cheap
ones, so the totals move by little, but they are not exactly reproducible from
the current code.

**An earlier revision of this section reported the ladder proving in 378.2s.
That number came from two ladder runs writing the same output directory and is
withdrawn.** The rung budget also matters more than expected: donor lemma 270
proved at 118.2s against a 120s cap in the clean run and failed at 120.2s in the
contaminated one.

**Rung goals must be Skolemised.** A CNF `negated_conjecture` with free
variables means "for all X, lhs != rhs", so refuting it needs only *some*
instantiation — proving an instance, not the universal law — and promoting the
variable-form equation back as an axiom is then unsound. Before the fix all 21
rungs "proved" in 0.0s; with fresh constants, real times appear (34.1s, 36.6s)
and two rungs fail outright. The 0.0s row was the fast-result bug signature
again.

### A concurrency bug that produced fake results

`screen.py` originally wrote both goal directions of a problem to the same input
path. The two directions run in separate workers and usually start together;
`Path.write_text` truncates before writing, so one worker's twee could open a
half-written file. It then parses a shorter problem and reports **`Satisfiable`
in ~0.0s**, or exits with no `RESULT` line at all — both of which land in the
results table looking like real outcomes.

Caught because COL002-10 timed out in both directions at 1000s and then returned
`Satisfiable` in 0.01s on a rerun. Three jobs corrupted (COL002-10, CSR040-10,
CSR065-10); the latter two were counted among the resisted when they had never
actually run. Fixed by giving each job its own input path and making
`build_input` write atomically via rename (`overtone/runner.py`).

The general lesson for this repo: a fast non-timeout result on a problem expected
to be hard is a bug signature, not a discovery. Prefer atomic writes anywhere
twee inputs are generated concurrently.

## Corrected ROB frontier (~950s CPU, both goal directions)

Resist: ROB001-1, ROB006-1, ROB031-1, ROB032-1, ROB007-1, ROB020-1, ROB024-1,
ROB027-1. Solvable: ROB026-1 (419s), ROB033-1 (782s), both `--no-flatten-goal`.

## Data hygiene

11 of the 1027 `ETP_UEQ_UNSAT` files in the twitch repo are implications Vampire
*refuted* (at 430-540s) — satisfiable, in a directory labelled UNSAT, unprovable
by construction.

`hard_successes/*.json` records winning configs but no baselines and no failures,
so it is not usable as a training source without regeneration.

**GRP740-1 contradicts itself in TPTP v9.2.1**: its header says
`% Status : Unsatisfiable` but `% SPC : CNF_SAT_RFO_PEQ_UEQ`. It is the sole
difference between the 1041-problem nine-theory list in
`twitch/data/TPTP/UEQ_Unsat.txt` (built with `tptp2T` against an older TPTP) and
the 1040 that v9.2.1's SPC headers give. It is currently sitting in
`twitch/data/TPTP/GRP_UEQ_UNSAT/`. Which field is stale is unresolved, so the
problem should be excluded from both training and evaluation rather than
assigned a label — the same treatment as the 11 refuted ETP_UEQ_UNSAT files.

**Twitch's `veroff_hints` path is not runnable in this repo.**
`meta_abstarctions.py:297` mines hints from twee's own base-run proof outputs of
sibling problems (axiom similarity >= 0.9), and needs both
`data/experiments/axiom_abs_11-11/base_times.json` (not in the submodule) and
populated `LOG_DIR` proof outputs. Note it is a *method*, unrelated to the
Veroff corpus above, and 18 of its 54 configs use the pathological
`--hint-skel-factor 0`. Its similarity threshold is also the main leakage risk
for a train/eval split: split by axiom-signature cluster, not by problem.

## Open

Whether McCune's Lemma 2 hints can drive twee through Lemma 2 is **unresolved**.
The first sweep used factor 0/0.2/0.5 but had no baseline and predates the
finding that factor 0 is pathological; the `0.5` arms were killed without
flushing. Rerun with factor 0.5 and a paired 1000s baseline before concluding
anything. The AC-association question is also open: EQP hints are AC-flattened
(`x+y+z`) and the translator picks one association, so some hints may never match.
