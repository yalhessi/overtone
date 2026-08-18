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

Every setting is bit-reproducible.

**It holds on the high-variance problem too, and is faster there.** MVA006-1,
3 runs per configuration:

| config | cpu | rules | |
|---|---|---|---|
| stock | 94.0, 245.3, 94.0, 157.5 | 9540–15856 | cv 47.9% |
| **step, 10,000/s** | **80.6, 80.8, 81.3** | 9147 | deterministic, **1.76x faster than stock's mean** |
| step, 1,000/s | 198.0, 199.1, 198.2 | 8373 | deterministic, 1.39x *slower* than stock |

Faster than stock's *fastest* run (80.9s vs 94.0s) at the good scale, and
deriving fewer rules than stock's minimum. The speedup is larger on the
high-variance problem than on REL029-1 (1.76x vs 1.24x), which fits the
mechanism: stock was forking into worse trajectories about half the time.

**The scale is a real tuning parameter, not a free win.** At 1,000 steps/sec the
run is still deterministic but derives *fewer* rules while taking longer — the
time goes into interreduce rather than the search — and lands 1.39x worse than
stock. 10,000 has been good on both problems tested; that is two problems.

**Confirmed over 21 related problems at once.** The MVA005-1 ladder is 20 rungs
of graded difficulty over one theory plus a final run, so one ladder execution is
a 21-problem test. Run twice per build:

| | rung cpu | final | total | failing rung |
|---|---|---|---|---|
| det rep1 | 324.9s | 139.0s | **463.9s** | lemma 227 |
| det rep2 | 325.2s | 138.6s | **463.8s** | lemma 227 |
| stock rep1 | 365.7s | 230.9s | 596.6s | lemma 269 |
| stock rep2 | 336.0s | 134.5s | 470.5s | lemma 269 |

The two deterministic runs agree on **every rung outcome and every rung time to
within 0.1s**. The two stock runs agree on outcomes but their finals differ by
1.7x (230.9s vs 134.5s) on identical input with identical rung results — that
final is the number this project has been quoting as its headline hint result.

**Determinism makes the ladder's answer stable without making it correct.** The
builds disagree on exactly the rungs whose cost lands near the 120s rung cap:

| rung | lemma | det (both) | stock (both) |
|---|---|---|---|
| 16 | 227 | **FAIL 120.1s** | ok 106.1 / 102.7s |
| 18 | 243 | 30.2 / 30.3s | 72.9 / 49.7s |
| 20 | 269 | ok 116.8s | **FAIL 120.1s** |

Every other rung agrees within noise. Lemma 243 differs 2.4x between builds while
passing under both, so the underlying cost genuinely differs — this is not only
a threshold coin flip. The deterministic build reproducibly reports lemma 227 as
the failure, but stock proves it in ~104s.

So **pass/fail at a fixed rung budget is the wrong instrument for the refiner**.
A rung costing 106s against a 120s cap is not "the step that is too hard". Rank
rungs by *cost* instead: both builds and all four runs agree that 227, 269, 223
and 243 are the expensive ones, and that ordering is stable where the binary
verdict is not. Across the four stock ladder runs recorded so far the failing
rung has been 227, 243, 269, 269 — three different answers.

Remaining caveat: a step schedule interreduces at different *moments* than a
time schedule, so this is a different prover configuration and every timing in
this file would need re-baselining against it before adopting it as default.

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
(`scripts/ladder.py`, removed at 8712094; superseded by `agent/dag.py`, whose `scope="none"` is standalone rung verification and whose `attempt` is the final phase). 22 separate twee runs: rungs 1..21 each have one donor
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

### Why the ladder was slower: chaining, not decomposition

The ladder's premise is that each rung starts from more knowledge. That premise
is what made it slow, and two mechanisms compound.

**Completion amortises; the ladder discards it.** The donor MVA001-1 derives
**all 263 lemmas in 21.7s** -- one completion, one shared rewrite system. The
chained ladder spends **324.9s** re-deriving 20 of them individually: a 15x
blowup from throwing the sharing away.

**Carrying lemmas forward actively hurts, and the penalty compounds with depth.**
Each expensive rung proved three ways, deterministic build:

| rung | lemma | prior | standalone | as axioms | as hints |
|---|---|---|---|---|---|
| 13 | 188 | 12 | 8.6s | 16.3s | 15.1s |
| 15 | 223 | 14 | 8.0s | 22.4s | 17.6s |
| 16 | 227 | 15 | **22.4s** | **143.4s** | 92.1s |
| 18 | 243 | 16 | 7.9s | 30.3s | 27.7s |
| 20 | 269 | 18 | **11.5s** | **117.3s** | 68.0s |

1.9x at 12 prior lemmas, 10.2x at 18 -- every added equation enlarges the rewrite
system, giving more rules to interreduce and more critical pairs to score. This
is the axioms-vs-hints effect already recorded for the final run, but applying at
*every* rung and growing with position. Hints are less bad than axioms and still
worse than nothing.

**The localisation signal was an artifact of this.** Lemma 227 -- the rung the
ladder reports as too hard, failing at 120.1s -- proves **standalone in 22.4s**.
The ladder was reporting its own accumulation penalty as intrinsic difficulty.

**Standalone verification over all 20 rungs: 94.3s proving 20/20**, against
324.9s chained proving 19/20. 3.4x cheaper *and* complete. Three rungs (105, 187,
242) are genuinely faster chained -- their predecessors are real shortcuts -- but
they save ~22s against ~250s lost, so standalone is the right default. Standalone
rungs are also independent and parallelise; a chain cannot.

### MVA005-1, every arm on the deterministic build

| arm | final | verify | end-to-end |
|---|---|---|---|
| no hints | 317.2 / 316.6 / 318.0s | — | **317.2s** |
| flat hints (25) | 408.2 / 408.9 / 407.8s | — | 408.3s |
| ladder, chained -> hints | 139.0 / 138.6s | 324.9s | 463.9s |
| **skeleton, standalone -> hints** | 164.2s | 94.3s | **258.5s** |

All cv <= 0.2%, so these are finally comparable. Three readings:

- **Flat hints are worse than no hints** (408.3s vs 317.2s, a 1.29x slowdown).
  The v0 hint set actively harms this problem; earlier readings of that
  comparison were lost in 69-100% variance.
- **Standalone skeleton verification is the only arm that beats plain twee**,
  1.23x end-to-end, and its 94.3s is 20 independent jobs -- bounded by the
  slowest rung (22.4s) given cores, so ~187s wall.
- The chained ladder has the *fastest final* (139.0s) because it carries 19
  lemmas rather than 20. Hint-set size again; end-to-end is the number to quote.

Caveat: 1.23x on one problem, whose donor has identical axioms (similarity
1.000) -- close to a best case. This is not yet evidence that skeleton transfer
helps generally. It is the first configuration here that beats plain twee on a
clean measurement, and an explanation for why the earlier attempts did not.

### Draft/sketch/prove without a donor: no flip (RNG029-5)

The first test of the loop where the sketch is *drafted* rather than retrieved.
RNG029-5 is the middle Moufang identity `(xy)(zx) = x((yz)x)` in an alternative
ring: 15 axioms, rating 0.96, resisted at 4000s in both directions, and its
domain has essentially no donor material (1 saved RNG proof for 13 resisted RNG
problems, no Veroff coverage).

Drafted 11 lemmas along the classical route -- associator alternating in each
argument pair, hence the flexible law, hence Moufang -- plus the sign lemmas.
Verified standalone against the problem's own axioms, deterministic build, 120s
each. **7 of 11 verified in 483s:**

| verified | cpu | failed |
|---|---|---|
| `neg_mult_r`, `neg_mult_l`, `neg_add` | 0.0s | `assoc_alt_12` (alternating in args 1,2) |
| `associator(X,X,Y) = 0`, `associator(X,Y,Y) = 0` | 0.0s | `assoc_alt_23` (alternating in args 2,3) |
| `associator(X,Y,X) = 0` | 1.3s | `left_moufang` |
| **flexible: `(xy)x = x(yx)`** | **1.3s** | `right_moufang` |

**Attempt with the 7 verified lemmas as 10 hints: Timeout at 1200s in both
directions.** No flip.

**The failure is predicted by the ablation, not mysterious.** Everything that
verified is small and generic — `associator(X,X,Y)`, `multiply(multiply(X,Y),X)`,
the sign lemmas. Those are the *accelerant* category, which the MVA005-1 ablation
showed cannot solve a problem alone and only speed up a search that already
works. Every lemma with real structural content — both alternating laws, both
Moufang identities — failed verification. The verified subset is all accelerant
and no waypoint.

**The failed steps are too big, not unreachable.** `assoc_alt_12` is the
linearisation of `associator(X,X,Y) = 0`, which twee proves in 0.0s: substituting
`x+y` for `x` and expanding gives
`associator(x,y,z) + associator(y,x,z) = 0` directly. So the refiner has a
concrete subdivision available — state it additively to avoid `additive_inverse`
on the right, and/or supply the linearised instance
`associator(add(X,Y),add(X,Y),Z) = additive_identity` as an intermediate.

Standing conclusion: the loop's *verification* half works cheaply and in
parallel, and its *drafting* half has not yet produced a waypoint on a no-donor
problem. One iteration of a design intended to take several.

### The drafted library flips one problem, and the control is clean

Iteration 3 of the alternative-ring library (19 drafted lemmas, verified in
**both** goal directions -- 13/19, up from 10 single-direction) was attempted on
10 RNG problems sharing `RNG003-0.ax`, 4000s, both directions, deterministic
build. **RNG025-5 proved at 2484s** (`--no-flatten-goal`; 3357s the other way);
the other nine timed out at ~4004s.

That attempt changed two things against the screen baseline -- it added hints
*and* moved from the stock to the deterministic build -- so the missing arm was
run:

| RNG025-5, deterministic build, 4000s | `--no-flatten-goal` | `--flatten-goal` |
|---|---|---|
| 19 drafted hints | **Unsatisfiable 2484s** | Unsatisfiable 3357s |
| no hints | Timeout 4003.4s | Timeout 4003.9s |

RNG029-5 also timed out in both directions without hints. So the flip is
attributable to the hint library, not to the build. It is the first flip here
from a *drafted* (non-donor) sketch.

Two things keep it modest. RNG025-5 is **rated 0.74**, so roughly a quarter of
state-of-the-art systems solve it -- this is a flip over our own baseline, not an
ATP first. And its conjecture is one of the library's own unverified lemmas
(`alt23_additive`), so the library mainly proved its own missing rung.

### TPTP shipped an axioms-vs-hints experiment: RNG025-4 vs RNG025-5

The two problems have the **same conjecture and the same axiom include**.
RNG025-5 adds seven inline axioms, which are exactly the sign lemmas our library
drafted (`(-x)y = -(xy)`, `x(-y) = -(xy)`, `(-x)(-y) = xy`, and four
distributivity-with-inverse variants). Same screen, build, budget and direction:

| problem | 1000s `--flatten-goal` |
|---|---|
| RNG025-4 (without the seven) | **Unsatisfiable 371.9s** |
| RNG025-5 (with them as axioms) | Timeout -- and still Timeout at 4000s |

Seven true, relevant lemmas added as axioms turned a 372s proof into a >4000s
failure. The same lemmas as *hints* proved RNG025-5 in 2484s. We did not
construct this pair.

Note the field disagrees about direction: RNG025-4 is rated 0.83 and RNG025-5
is 0.74, so for most systems the extra axioms help. The penalty looks specific to
completion-based provers, or to this configuration.

### Context scope decides the drafted rungs, and it inverts the promotion rule

`alt12_additive` follows in four rewrite steps from lemmas that all verified
(`lin_left_inst`, `assoc_add_1`, `assoc_add_2`, `assoc_xxy`, `assoc_xyy`), yet
timed out at 300s. Standalone verification supplied none of them. Three scopes x
two channels x two directions, 600s, deterministic build:

| lemma | scope | as axioms | as hints |
|---|---|---|---|
| `alt12_additive` | none | 592.5s / Timeout | — |
| | **direct parents (5)** | **0.2s / 0.0s** | Timeout / Timeout |
| | all 13 verified | 0.1s / 0.0s | Timeout / Timeout |
| `alt23_additive` | none | 415.4s / Timeout | — |
| | **direct parents (5)** | **0.1s / 0.0s** | 483.1s / Timeout |
| | all 13 verified | 0.1s / 0.1s | 194.5s / Timeout |

(cells are `--flatten-goal` / `--no-flatten-goal`)

Four readings:

- **Supplying the direct parents as axioms is worth ~3000-4000x** (592.5s ->
  0.2s), and converts a `--no-flatten-goal` timeout into 0.0s.
- **The minimal parent set is sufficient.** 5 lemmas and 13 lemmas both land at
  0.0-0.2s, so scope should follow *direct parents*, not the ancestor closure.
- **Axioms beat hints decisively -- the opposite of MVA005-1**, where 20 lemmas
  as axioms timed out and the same as hints proved in 173.6s. Here `alt12` never
  proved from any hint configuration, and parents-as-hints (>600.7s) was *worse*
  than supplying nothing (592.5s). The distinguishing variable is set size and
  precision: **5 exact logical parents -> axioms; 20 loosely related lemmas
  (19 supplied against a 179-lemma closure) -> hints.**
  `agent/ladder.py`'s unconditional `promote="hints"` default was set from the
  MVA005-1 measurement alone and was wrong for the small-precise case; the rule
  now lives in `agent/dag.channel_for`, which reads the sketch's structure
  instead of applying one global default.
- **Two separable causes.** `alt23` standalone needs 415.4s and `alt12` 592.5s,
  both above the 300s verification budget used overnight. So the "6 of 19 failed"
  result was partly under-budgeting and partly scope; the `none` control arms are
  what separate them, and without those arms the whole effect would have been
  misattributed to scope.

Direction also stops mattering once parents are supplied: every unaided success
was `--flatten-goal` only, while parents-as-axioms proves both ways at 0.0s.

### Three resisted Moufang targets, decomposed (RNG029-5, RNG028-7, RNG027-8)

The primary target of the sketch line. RNG029-5 is the middle Moufang identity
in an alternative ring, rated 0.96, and it resisted 4000s in both goal
directions, resisted the 19-lemma drafted library, and has no donor of its own.

Verified as a 29-node DAG against RNG029-5's own axioms, 1122s wall end to end:

| node | parents | cpu |
|---|---|---|
| 26-node base sketch (sign, alternating, trilinearity, absorption) | | <= 2.7s each |
| `assoc_cyclic` `(x,y,z) = (y,z,x)` | alt12, alt23 | 0.0s |
| `assoc_def_246`, `assoc_def_247` | cyclic + core | 0.2s each |
| **`right_moufang`** `((xy)z)y = x(y(zy))` | the three above | **193.6s** |
| **`right_moufang_a`** = RNG027-8, rating 0.91 | + right_moufang | **0.5s** |
| **`left_moufang`** = RNG028-7, rating 0.96 | + right_moufang | **35.0s** |
| **`middle_moufang`** = RNG029-5, rating 0.96 | + right_moufang | **107.6s** |

Summed CPU along the successful path is ~344s, against >8000s of failed baseline
per target. Only `left_moufang_a` remains unproved, at 300s, including on the
standalone retry.

**No donor lemma appears anywhere in this.** A donor was used once, and only to
*locate* the intermediates: RNG027-5's proof has 234 lemmas, its goal cites four,
and the same four serve all three targets. Three of those four then turned out to
be reachable from the drafted sketch in under a second. The donor's role was
selection, not supply.

**The chain length was an artifact of the starting point.** Reconstructing the
donor's proof as a DAG -- 234 nodes, 35 layers, 548 edges, citations as edges --
verifies 234/234 with *every node at 0.0s*, where the same proof cost 3555.6s
from bare axioms. But 234 was never the decomposition: four lemmas were. Reading
twee's own search order as the structure of the proof is what made the problem
look intractable.

**Scale, and where hints stop working.** Supplying all 234 mined lemmas as hints
proves *none* of the four targets at 300s, while eight as axioms proves three of
them. That is the sharpest form of the axioms-vs-hints result here: the hint
channel cannot substitute for a decomposition at any quantity.

Open: `right_moufang` at 193.6s is well above the point where a node is suspect,
so a missing node sits under it. Candidate intermediates ranked from its own
failed search are in `logs/decompose/candidates.json`.

### Ten flips in the RNG Moufang family, and where the method stops

Six lemmas -- cyclicity, two associator-definition variants, the flexible law,
right Moufang, left Moufang, all proved from RNG029-5's own axioms -- appended to
the real TPTP problem files, 300-600s, both directions:

| flip (baseline: timeout at 4000s, both directions) | rating | cpu |
|---|---|---|
| RNG027-7, RNG028-7 | 0.96 | 0.0s |
| RNG028-9 | 0.91 | 0.1s |
| RNG025-5 | 0.74 | 0.2s |
| RNG027-8 | 0.91 | 0.6s |
| RNG027-9 | 0.91 | 1.2s |
| RNG028-8 | 0.96 | 1.4s |
| RNG029-7 | 0.96 | 24.3s |
| RNG029-6 | 0.96 | 183.9s |
| RNG029-5 | 0.96 | 197.3s |

Plus RNG027-5 at 3555.6s -> 0.0s and RNG028-5 at 3825.8s -> 0.0s. On RNG025-5
the drafted 19-lemma library had needed 2484s; six mined lemmas take 0.2s.

The RNG028 cluster initially resisted, and the cause was syntactic: it states
left Moufang as `(x(yx))z = x(y(xz))` where our node had `((xy)x)z`, which differ
by exactly the flexible law. Adding it flipped all five remaining problems.

**Two results withdrawn.** RNG027-10 and RNG029-10 (both rating 1.00) proved in
0.0s and 1.3s, but they are [Sma18] re-encodings whose axiom sets are *missing*
3 and 4 of RNG029-5's axioms. Lemmas proved from the stronger theory are not
theorems of the weaker one, so appending them adds assumptions rather than
lemmas and the proofs establish nothing about those problems. `transfer_dag.py`
verifies donor lemmas against the target before using them and would have caught
this; the fixed-library script did not check containment. Any transfer must
assert `donor_axioms <= target_axioms` or re-verify.

### RNG029-5 through the per-problem pipeline: 2146.4s, everything counted

The first honest per-problem number. `scripts/prove.py`, nothing shared with any
other problem, every lemma verified against RNG029-5's own axioms in this run,
and the cost is everything spent -- failures, both goal directions, the runs that
lost:

| | |
|---|---|
| nodes proved | 29/29 |
| result | **proved** |
| total | **2146.4s CPU over 60 runs, 8 failed** |
| baseline | Timeout at 1000s and 4000s, both directions |

Against a baseline that spent ~8000s not solving it. This is what reachability
costs when it is not amortised across a family, and it is the number an
evaluation should quote for a single problem.

Three nodes still trip the diagnostic threshold -- `right_moufang` 192.1s,
`middle_moufang` 112.5s, `left_moufang` 33.3s -- so by the rule that held
everywhere else, nodes are still missing beneath them and this figure should come
down.

### Goal-ranked donor selection does not rescue cross-theory transfer

`find_donor` ranking by axiom similarity was the obvious suspect for the GRP/LAT/
COL failures: it cannot see whether a donor's *goal* is a fact the target needs,
which is what decided RNG. Ranking by goal relatedness instead picks a different
donor for LAT138-1 -- LAT141-1, whose conjecture is LAT138-1's **verbatim**,
goal score 1.000, against the axiom-ranked pick of LAT139-1, a different theorem.

That is the best case the new ranking can produce, and it still fails:

| | |
|---|---|
| donor | LAT141-1, same conjecture, different axiomatization |
| lemmas holding in the target's theory | 13/16 |
| final attempt | Timeout, both directions, 300s |

So the hypothesis is falsified: cross-theory transfer was not failing because
donor selection optimised the wrong quantity. The likely reason goal relatedness
carries so little signal here is that **a different axiomatization usually means a
different proof route** -- LAT138-1 lacks one of LAT141-1's axioms, and a theory
that has to reach the same statement by another path has different machinery to
lend. Sharing a goal is not sharing a proof.

Both rankings are kept, because they answer different questions and each is right
somewhere, and because goal ranking is still the honest answer for GRP: nothing
scores above zero, so it declines rather than naming a donor at 0.817 that
carries nothing. But note it must not be used alone -- for RNG029-5 it ranks
RNG027-10 first, a withdrawn problem whose axiom set is weaker. Containment
gates the transfer regardless.

### Cross-theory transfer fails, in three distinguishable ways

`scripts/transfer_dag.py` runs the whole method as one command: pick the most
axiom-similar solved sibling, read its proof as a citation DAG, verify that DAG
against the *target's* axioms, supply the deepest survivors as axioms.

| target | donor | sim | held | donor proof | result |
|---|---|---|---|---|---|
| GRP673-10 | GRP664-10 | 0.817 | 177/260 | 278 lemmas, depth 23 | Timeout 300s |
| LAT138-1 | LAT139-1 | 0.930 | 18/20 | 20 lemmas, depth 7 | Timeout 300s |
| COL003-1 | COL066-1 | 0.897 | 2/13 | 13 lemmas, depth 4 | Timeout 300s |

Three different faults, none of them the verification machinery:

- **GRP: the donor's goal is irrelevant.** Lots transfers, but the survivors stop
  at depth 11-13 of a depth-23 proof -- everything near the donor's goal fails,
  so ranking by depth selects precisely the useless material.
- **LAT: the donor is too easy.** 18 of 20 lemmas transfer and none of them help;
  a proof 20 lemmas long contains nothing a resisted problem needs.
- **COL: the similarity metric overstates.** 2 of 13 lemmas are theorems of the
  target's theory at a claimed 0.897.

RNG succeeded because it had all three properties at once: identical axiom sets,
a deep donor proof (234 lemmas, depth 34), and a donor whose **goal was itself a
lemma every target needed** -- RNG027-5 proves right Moufang, which is exactly
what the other twelve require. That is a narrow condition, and axiom similarity
does not detect it. The measured conclusion is that `find_donor` optimises the
wrong quantity: relatedness of *goals* is what matters, not of axioms.

### A wrong edge costs more than a missing one (teichmuller)

The Teichmuller identity holds in **any** ring -- it is pure expansion of the
associator definition, needing only distributivity and additive associativity --
and is TPTP RNG026 at rating 0.30-0.39. Drafted into the DAG it was given five
parents: the three trilinearity lemmas and the two sign lemmas. It timed out at
900s in both directions, and because verification is topological that blocked
six downstream nodes: both associator-form Moufang identities, both product
forms, and middle Moufang.

The statement was correct (checked against RNG026). The edges were not.
Trilinearity is adjacent in the theory and absent from the derivation.

| scope | supplied | derived rules | `--flatten-goal` | `--no-flatten-goal` |
|---|---|---|---|---|
| **none** | 0 | **2,290** | **3.3s** | Timeout 901.1s |
| sign lemmas | 2 | 15,821 | 358.6s | Timeout 901.4s |
| as drafted | 5 | — | Timeout 900s | Timeout 900s |

**Two true, relevant lemmas cost 109x; five cost the problem.** Same mechanism as
everywhere else -- an axiom joins the rewrite system and forms critical pairs
with every rule -- but this is the cleanest measurement of it we have, because
scope is the only variable and the standalone control is in the same table.

This qualifies the R1 result rather than contradicting it. Correct parents were
worth ~3000x on `alt12_additive`; incorrect parents are worth -infinity here. The
quantity that matters is whether the supplied lemmas lie on the derivation path,
and *nothing in the pipeline checks that*: the prover's soundness catches a wrong
statement, and no mechanism catches a wrong edge.

Hence `agent/dag.py` retried any failed node standalone before recording failure
(`retry_standalone=True`). One extra run per failure was the entire cost, and it
would have saved this branch.

**That retry was removed later; see "The standalone retry cost 8620.8s and
answered the wrong question" below.** The finding above stands -- nothing checks
a wrong edge -- but the check it motivated was priced wrong and shaped wrong, and
the proof certificate answers the same question for free.

Note also what the DAG format buys and costs. A flat lemma list cannot record a
wrong edge -- but it cannot record a right one either, and the right ones are
worth 3000x. The format is load-bearing, and the drafter is now the component
most able to break it.

### Three rating-1.00 / 0.96 problems fell to the plain 4000s screen

No hints, no sketch, stock build, `--no-flatten-goal`:

| problem | rating | cpu |
|---|---|---|
| **RNG027-10** | **1.00** | 3271.1s |
| RNG027-5 | 0.96 | 3555.6s |
| RNG028-5 | 0.96 | 3825.8s |

Rating is the fraction of state-of-the-art systems that fail at TPTP's evaluation
limit, so 1.00 means no current system solves it under competition conditions.
All three land in the last 20% of a 4000s budget, so the honest description is
**budget, not capability**. It remains the strongest RNG result here -- stronger
than the hinted RNG025-5 flip -- and it sharpens the alternative hypothesis that
any sketch result has to beat.

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

## Counting term shapes under `--flatten-goal` measures nothing (2026-08-04)

`--flatten-goal` introduces a constant for every subterm of the goal and rewrites
any matching term to it immediately:

    Axiom 18 (flattening): multiply3 = multiply(sk_dag_2, associator(sk_dag_3, sk_dag_4, sk_dag_1)).
    17. multiply(sk_dag_2, associator2) -> multiply3
    30. add(multiply4, multiply3) -> add3

So a goal subterm **cannot appear literally** in the derived rules, and grepping
for its shape counts the residue of the naming convention rather than the search.

This cost a full iteration. RNG033-8's iteration 2 was drafted on the reading
"the search never builds the goal's RHS", from ~10 literal matches out of 24k
rules. Counted properly -- by resolving the flattening definitions and matching
the constants -- the RHS is the *dominant* side, 11,565 rules against 3,033 for
the LHS. The premise was backwards, and the four nodes added to fix it cut the
rules mentioning both sides, the only ones that can close the goal, from **162 to
102**. A `--precedence` experiment built on the same measurement moved it to 103.

    run                  rules   LHS side  RHS side  BOTH sides
    iter00  6-parent     24107       3033     11565         162
    iter01 10-parent     24727       2927     11596         102
    iter01 +precedence   25894       3058     12270         103

Iteration 3 reverted those four nodes and cut the goal to three parents, adding
the standalone (0-parent) run to the comparison:

    parents   rules    lhs     rhs   both    both%
          0   19163   3297    9322    371    1.94%
          3   26358   2708   12839    171    0.65%
          6   24107   3033   11565    162    0.67%
         10   24727   2927   11596    102    0.41%
         10   25894   3058   12270    103    0.40%   + --precedence

Parent *count* is not the lever between 3 and 6 -- 171 against 162, and lower by
rate. Ten parents is genuinely worse. **And the highest contact belongs to
supplying nothing**, which did not prove the goal at 300s, so `both` is a veto
rather than
an objective: a fall is evidence an edit hurt, a rise is evidence of nothing, and
maximising it drives a sketch toward the configuration already known to fail.
None of 0, 3, 6 or 10 parents proves RNG033-8 at 300s.

Three rules follow. Resolve `Axiom N (flattening):` lines and match twee's own
constants, never source-level shapes; judge a decomposition by rules touching
**both** sides of the goal rather than either one; and treat that count as a
veto on edits, never as a quantity to maximise.

## The loop's instruments were not connected (2026-08-13)

Two agent runs failed, and the obvious reading -- that verified lemma count is a
useless objective -- is true but secondary. Audited against their own artifacts,
the primary cause is that the measurements the loop is built on were never taken,
and its prover budget went to the one configuration this file already condemns.

**`State.contact` was `None` at every iteration of the RNG029-5 run.** `_contact`
globbed `{node}.flatten-goal.*.fail.out` for the *goal node*, which was blocked
and so never ran. The final attempt in the same iteration left a 2.2 MB failed
search on the real problem, and `proofs.goal_contact` reads it without
complaint -- `{lhs: 1727, rhs: 2153, both: 22, rules: 14562}`. The veto signal was
on disk and shown to nobody. Now computed from the attempt's own result row.

**The target attempt was the budget.** It ran every iteration with every proved
node as axioms, channel hardcoded, while `verify` chose per node via
`channel_for`:

| run | attempts | total | share |
|---|---|---|---|
| RNG033-8 | **6,003.7s** | 10,423.9s | 57.6% |
| RNG029-5 | **1,201.4s** | 1,441.9s | 83.3% |

That is the loose-bag-as-axioms configuration measured as a timeout on MVA005-1
and as worse-than-nothing on `teichmuller`. The support is now the goal node's
*declared parents* filtered to what proved, and the attempt is skipped entirely
when that set is unchanged -- an identical input the ledger would answer for free
and `cost` would charge 600s for again.

**`cpu_spent` charged ledger reuse at full price.** Of RNG033-8's 4,420.2s of
node verification, **2,857.0s was reused**; iteration 7 reported 601.7s of which
100% was reuse, and RNG029-5's total rose 600.7s across an iteration whose two
attempts were both served from the ledger. `cost` now returns `cpu` (cold cost,
the honest per-problem figure) and `cpu_new` (what the machine spent) separately.

**Artifact lookup by directory glob is contaminated in both directions.**
`logs/loop/RNG033-8-agent/iter00/` holds `final.*.p` from **five** separate loop
invocations, because repeated runs share an `iterNN` directory. Same class as the
`screen.py` concurrency bug. Everything is now addressed through `row["output"]`.

**A statement that is not a term reached the prover.** RNG029-5's iteration-0
edit proposed a node whose sides were `associator(X,Y,Z) = additive_identity` and
`multiply(multiply(X,Y),Z) = multiply(X,multiply(Y,Z))` -- an implication written
as an equation between two equations. `=` is not a token of the term grammar, so
`safe_term` returned `None`, `alpha_key` fell back to a stripped string, and every
`eq_key`-based reviewer compared that string and found no match. twee rejected it
in 0.003s x 4 and the loop recorded `failed`, which is what a hard lemma reports;
the agent subdivided it, then removed it, and the *cycle detector* ended the run.
Arity is the subtler half -- `associator(X,Y)` parses fine, is not a term of the
signature, and used to crash `freering.reviewer`, which caught parse errors but
not a known head applied to the wrong number of arguments.

**The cycle detector hashed node names.** RNG033-8's two failing nodes were
renamed `..._zeroed` and back across iterations 5-9, so nine passes round the same
loop read as nine fresh sketches. The digest is now over `eq_key`s: a rename is
not a new sketch, and neither is a re-orientation or a variable renaming.

Two consequences for how a run is judged. Progress is now the probe an agent
*declared before the run*, not a node newly proved -- proving a lemma nothing
asked for is `inconclusive` and does not clear a stall. And a fall in target
contact `regresses` the iteration, which reverts the sketch and closes that
branch rather than ending the run, which is what RNG029-5 needed and did not have.

### The rebuilt loop, replaying RNG029-5 end to end

Scripted agent, deterministic build, 60s a node and 300s a final, fresh outdir.
**Proved at iteration 3**, `stop_reason: proved`:

| iter | nodes | charged | new | outcome | target |
|---|---|---|---|---|---|
| 0 | 20/25 | 3155.9s | 600.5s | baseline | Timeout, 1 lemma, `both` 21 |
| 1 | 20/25 | 5591.2s | 600.5s | inconclusive | **skipped**, support unchanged |
| 2 | 21/26 | 8001.0s | 600.5s | inconclusive | **skipped**, support unchanged |
| 3 | 28/29 | 9994.4s | 1986.3s | **solved** | **Unsatisfiable 424.0s**, 4 lemmas as axioms |

Two of the four attempts were skipped on unchanged support, and the one that
proved was given the goal's four declared parents -- `assoc_cyclic`,
`assoc_def_246`, `assoc_def_247`, `right_moufang` -- as axioms, not the 28 nodes
that had proved by then. Charged 9994.4s against 1986.3s actually spent, so the
two figures differ by 5x on a single run and the old single number was neither.

**The target node had to be found by its statement.** This sketch has no node
named `*goal` at all: the conjecture is `middle_moufang`, which *is* RNG029-5.
Taking the support from "the goal node" under the old `name.endswith("goal")`
rule would have supplied nothing and proved nothing. `_target_node` matches the
problem's conjecture by `eq_key` first, falls back to the naming convention, then
to the DAG's unique sink, and reports rather than guessing when all three fail.

### A drafted run that failed, and the three separable reasons

gpt-5.4 drafting RNG029-5 from scratch: 3 iterations, 2,769.5s charged / 2,045.3s
new, no proof, `stop_reason: the agent proposed no further edits`. Worth
recording because the causes are independent and only one is mathematical.

**The sketch contained a false lemma, and it was load-bearing.** `shuffle_inner`
states `y(zx) = (yz)x` -- full associativity, which is false in an alternative
ring by construction, the theory being defined by not having it. `target_bridge`
rested on it, the goal rested on `target_bridge`, so the goal's declared support
was **empty at every iteration** and the target was attempted with nothing.

**The free-ring check cannot see this, and says so.** It returns "2 monomials
remain" for `shuffle_inner` and *the same verdict* for `flexible_law`, which is
true and proved in 1.3s. Non-universality does not separate "needs alternativity
and holds" from "is associativity and does not". That limit is in the module
docstring and this is what it looks like in a real run.

**The runtime signal was there and the prompt inverted it.** All three failing
nodes were `failed_standalone` -- they failed with nothing supplied, which
exonerates their parents. Rule 2 told the model "if a node fails WITH parents but
its standalone retry also fails, suspect the parents before the statement",
which is backwards and contradicts `state_of`'s own comment. The model followed
it and re-parented the same three nodes for three iterations. The rule then
spelled out both statuses: `failed_with_parents` means fix the edges,
`failed_standalone` means suspect the statement.

*Superseded.* Both statuses are gone with the retry that produced them. What the
model needed here was the distinction between "the search closed and your
statement does not follow" and "the budget ran out", and `failed_standalone`
was only ever a proxy for it -- an expensive one, and a lossy one. `NodeState.failure`
now carries `saturated` / `timeout` / `error` directly off the result line. See
below.

**An empty-support attempt is the bare baseline and is now skipped.** It cost
600.5s of 2,045.3s new CPU (29%) to re-derive a timeout already recorded at
4000s in both directions. Worse, its contact is not comparable to any later
reading: supplying nothing scores the highest contact ever measured here (371
against 162 for six parents), so using it as the reference makes the first real
lemma look like a large regression -- and this loop reverts regressions, which
would undo every genuine step. `target_of` now withholds the delta when either
side of the comparison supplied nothing.

### The second attempt: cheaper, and it retreats instead of redrafting

Same model and problem with those fixes in, fresh outdir: 4 iterations,
3,011.4s charged but **841.0s new**, still no proof. Two things worked and one
new fault appeared.

Iterations 0-2 re-verified the identical drafted sketch and cost **0.0s of new
prover time** -- entirely ledger-served -- while the empty-support skip removed
three 600.5s baseline attempts. Real cost fell from 2,045.3s to 841.0s. And the
agent **redrafted at `stalled = 2`**, which the previous run never did.

Then the redraft went backwards. It proposed `nodes: []`: keep the five nodes
that had already proved, delete the rest, point the goal at `flexible_law`. The
five are `associator(X,X,Y) = 0`, `associator(X,Y,Y) = 0`, `commutator(X,X) = 0`,
the flexible law and `associator(X,Y,X) = 0` -- every one an **accelerant**, the
category the first RNG029-5 write-up in this file already found "all accelerant
and no waypoint". 5 of 6 nodes proved, and the target timed out.

The loop scored that as a route change because deleting four nodes is a
non-empty diff, so it reset the stall counter and bought four fresh iterations on
a sketch strictly smaller than the one that had just failed. **A redraft
proposing no new lemmas is now withheld**, with the reason stating that keeping
what already proved is a retreat to a subset already known to be insufficient.

That withholding exposed an older bug worth naming separately: the loop tested
`if not actions` on the batch AFTER review, so a wholly withheld batch ended the
run as "the agent proposed no further edits" -- untrue, and the same class of
false ending as the cycle detector firing on a revert. A withheld batch now
returns the findings and another turn.

### One rejected node destroyed a whole draft

The third run's severest fault, and the cheapest to fix. The draft proposed five
nodes; `sandwich_shift` was correctly rejected for restating the conjecture; the
other four survived review -- and `goal_parents` still named the rejected one, so
`apply` raised `unknown parents` and **the entire redraft was discarded**.
`_draft` caught the exception and only printed it, so the model was never told.
The run began with a bare one-node sketch and spent four of its first five
iterations testing nothing.

`repair` had always dropped unresolvable names from a node's `parents`. It never
touched a redraft's `goal_parents` or `keep`, which are node references by the
same rule. Replaying that exact draft through the fixed review now yields all
four nodes and an applicable action, and a draft that still cannot apply reaches
the model as a finding saying so.

**A rollback handed the agent the sketch it had just thrown away.** After
restoring `prev_sketch` the loop called the agent with the *old* `state` while
review ran against the restored sketch. The model proposed `goal_left_factor`
because its state said the node was absent, and review rejected it as a
duplicate because it had just been restored. The state is now rebuilt from the
restored sketch's own results.

Four smaller things the same audit turned up, all of which mislead the model
directly: a node with **no parents** that failed was labelled
`failed_with_parents`, pointing the agent at edges that do not exist (both
statuses are since gone -- see the standalone-retry entry below); the
problem's own **axioms rendered as `pending`**, 15 of 20 rows in one prompt,
reading as work outstanding rather than assumptions; the draft prose said a
parent **may** name an axiom while the JSON schema said **never**; and the draft
cap asked for 5-15 lemmas when the only decomposition ever driven to a proof on
a problem of this difficulty has **29 claims**, now 8-30.

**The target attempt's own search is now mined.** It is the longest run of the
iteration -- 600s against the real conjecture -- and its derived rules were read
only for a contact count, then discarded. Candidates from any run are also
filtered now: rules naming run-local constants (`sk_dag_2 -> multiply2`) cannot
become reusable lemmas because the names die with the run, and rules the sketch
already states or the problem already assumes are not candidates at all.

### Fourth run: the drafts finally survive, and the goal comes loose instead

With the draft repaired, the same model on the same problem went from 1-2 proved
nodes to **20-24**, over four named approaches -- Bruck-Kleinfeld and Teichmüller
waypoints, which is the actual literature route. 8 iterations, 6,453.1s charged /
3,501.2s new, no proof. The decomposition is now real; two things stop it being
tested.

**The target was attempted once in eight iterations.** Not because it was
skipped as a baseline by design, but because the goal node had **no parents at
all** from iteration 3 to 6 while 24 lemmas sat proved and unused. The cause is
the previous fix's blind spot: repair drops goal parents that name rejected
nodes, and when it drops them *all* the goal is connected to nothing. The model
had supplied goal parents both times; every name it chose had just been rejected
as a duplicate. A redraft that would orphan the goal is now withheld, on the same
rule as a carrier whose every node was rejected -- a goal with no parents is not
a decomposition of anything.

**Seven nodes were lost to one recurring malformation.** The model wrote the
whole equation into `lhs` and omitted `rhs`:
`"lhs": "associator(X,Y,multiply(Z,X)) = additive_identity"`. `well_formed`
rejected it correctly, but reported the case it was written for -- an implication
between two equations -- so the reason described something the model had not
done, and it repeated the mistake across two iterations. One `=` with `rhs`
missing is unambiguous and is now **split and kept**, with a warning; two `=`
signs remain a rejection, because which relation was meant is not recoverable.

The lesson generalising across all four runs: every remaining loss has been a
*repair* that was too weak or a *message* that described the wrong error. The
prover has not yet been the bottleneck.

### Fifth run: the fix for the orphaned goal was worse than the fault

Withholding a redraft that would orphan the goal put `peak_proved` back to **1**.
The draft proposed 18 nodes; two were rejected (one restated an axiom, one
restated the conjecture); the rejected conjecture-restatement was the only name
in `goal_parents`; so the guard withheld the whole redraft and the run began
with a bare goal again. 8 iterations, 2,420.0s charged / 483.7s new, and the
first approach is recorded as `(unnamed)` because no draft ever applied.

That is the same failure the `goal_parents` repair had just fixed, reintroduced
one level up, and it is the more expensive of the two: an orphaned goal wastes
the target attempt, a discarded draft wastes everything. Replaying that exact
draft through the corrected review keeps **16 of 18 nodes**.

So the rule is now: **repair, warn, and keep the work; never discard a
decomposition over a reference error.** The orphaned goal is instead reported by
the loop every turn at reject severity, naming the proved nodes available to
wire it to -- persistent pressure that costs nothing, where withholding cost the
entire run. Three rounds of this now say the same thing: in a loop whose
proposals are cheap and whose verification is expensive, the correct response to
a malformed proposal is almost never to throw it away.

### Sixth run: rejecting a duplicate was injecting wrong edges

18-21 nodes proved, three approaches, the target attempted every iteration with
its three declared parents as axioms. 8 iterations, 9,244.1s charged / 2,406.0s
new, no proof. The machinery now works end to end, and one more repair was still
too weak.

**A duplicate is a renamed lemma, not a lost one.** The model repeatedly
proposed lemmas the sketch already held under other names. `duplicates_a_node`
rejected them -- correctly -- and then `repair` dropped those names from every
parent list that cited them, because the name no longer resolved. So a node that
genuinely had a parent in the sketch lost the edge. That is the pipeline
*creating* the wrong edges this file elsewhere records as costlier than missing
ones, and it happened across three redrafts of one run.

`duplicates_a_node` now reports *which* node states the equation, and review
carries a proposed-name -> existing-name alias through the batch so references
are rewired instead of deleted. Replaying that run's iteration-2 redraft:
`assoc_y_mul_zx_x_zero -> assoc_yz_x_outer_repeat`,
`x_assoc_yzx_zero_via_outer -> x_assoc_yzx_zero`, and nothing dropped, against
three parent references silently lost before. The goal node is deliberately
excluded as an alias target -- rewiring a goal restatement would make the goal
its own parent, a cycle produced by a repair.

**And the substantive result: `goal_contact.both` sat at 152 for all eight
iterations.** Every edit scored `inconclusive` or `regressed`; none moved the one
quantity that vetoes. The sketch churned -- 24 to 26 nodes, three approaches, two
reverts -- while the target's support stayed the same three lemmas throughout.

### Seventh run: a redraft deadlock, and where review and apply disagreed

The clearest harness failure of the series, because the run did *nothing* for six
iterations and reported no error at all: 8 iterations, one approach, `n_proved`
frozen at 14/22 from iteration 2, and **`cpu_new` frozen at 1,444.2s** -- six
model calls and zero prover work.

Review and `apply` disagree about what a redraft's parents may name. Review
checks against the CURRENT sketch, so a parent naming any existing node passes.
`apply` then rebuilds the sketch from `keep` plus the proposed nodes and deletes
everything else -- so a parent naming a real node the model did not happen to
list in `keep` becomes an unknown parent, and the whole redraft raises.

Six consecutive iterations proposed a waypoint citing
`assoc_prod_flexible_rewrite`, a node that existed and was not kept. Every
redraft raised, so nothing applied; the sketch never changed; the approach never
rotated, because rotation requires an *applied* redraft; the approach-budget
controller never fired, because the batch did contain a redraft; and the loop
span on `retry_after_rejection` until `max_iterations`.

Review now closes `keep` over what the new nodes cite, transitively -- a node
pulled in brings its own parents, or it dangles one level down, which is exactly
what the first version of this fix did. Replaying the run's redrafts: iterations
2, 3, 5 and 7 all apply, with 2-3 real edits each, against raising every time.

Two general lessons. **Any disagreement between what review accepts and what
`apply` builds is a silent deadlock**, not a visible error -- three separate bugs
in this series have been instances of it (`goal_parents`, duplicate aliasing,
`keep` closure). And **a loop that can spin without spending prover time can
spin invisibly**: the cost accounting is what exposed this one, since a run
burning model calls at constant `cpu_new` is doing nothing. That is now a stop
condition -- three consecutive iterations with no new prover time ends the run
and names the fault, rather than exhausting the iteration budget in silence.

### Eighth run: the repairs hold, and the goal keeps coming loose

Four approaches rotating, 19-20 nodes proved, every repair firing as intended --
duplicate references rewired, `keep` closed transitively. 8 iterations, 7,227.4s
charged / 2,764.7s new, no proof. No new harness fault in the edit path, which
is the first time in the series. Two things remain.

**The target had no proved support in three of eight iterations**, and this time
it is the sketch's fault rather than the harness's. The goal's declared parents
were empty at iterations 0 and 5, and at iteration 7 it named two nodes of which
*neither* proved. The `regressed` verdicts at 5 and 7 are correct. The pattern
across the run is that the model points the goal at nodes it has not yet
established, so the most expensive run of the iteration measures nothing.

**`goal_contact.both` sat at 152 for all eight iterations again** -- the same
value as the sixth run, with a different sketch and different approaches. Two
independent runs now agree that this decomposition family does not move the one
quantity that carries evidence.

One reporting bug fixed: a rolled-back iteration recorded the *restored*
sketch's target beside the *reverted* sketch's outcome, so the trajectory showed
"the target lost all of its proved support" next to a healthy two-lemma attempt.
The record now carries the judged sketch's target, with the post-rollback one
alongside it when they differ.

### Specialisations of a goal are accelerants: easy, and they transfer nothing

The convergent ladder FINDINGS has called unimplemented since the MVA005-1 work
-- rungs that are progressive approximations of the target rather than lateral
facts -- finally tested, on the cheapest version of the idea: relax the goal by
identifying its variables, walk from the fully-identified instance up to the
conjecture. RNG029-5, its own axioms, deterministic build, 60s a rung, both
directions:

| rung | result |
|---|---|
| all three variables identified, `(xx)(xx) = x((xx)x)` | **0.01s** |
| `identify_xy` | 1.33s |
| `identify_xz` | 1.35s |
| `identify_yz` | **Timeout 60.1s**, both directions |
| the goal itself | Timeout |

So there *is* a difficulty gradient -- 0.01s, 1.3s, timeout -- and it is useless.
Supplying the base rung as support to its own successor gives **1.33s against
1.33s**: the times agree to three significant figures, so the transfer is not
small, it is absent. Supplying both proved rungs to the target leaves it at a
60s timeout, matching the bare 60s baseline.

**The reading is that a specialisation of a goal is an accelerant**, in exactly
the sense this file already uses: cheap to prove, and no help. That is the
accelerant/waypoint split reappearing one level up, and it disposes of the whole
family of "walk from an easy instance to the conjecture" designs as *proof
support*. The lattice remains useful as a diagnostic -- `identify_yz` being as
hard as the goal while its two siblings are trivial localises which pair of
variables carries the difficulty -- but proving an instance is never evidence
about the general statement.

Two caveats, both against the negative half. The target arm ran at 60s, under
this file's own "screen at a realistic budget or not at all" rule, and the
contact fall reported alongside it (7 -> 5) is on 60s runs where the veto rule
was calibrated at 162 -> 102. So *supplying rungs hurts* is not established;
*they do not help, and transfer nothing* is, and the zero-transfer measurement
does not depend on the budget at all.

Recorded in `logs/ledger.jsonl` under `/tmp/rng029-lattice*`,
`/tmp/rng029-chain-transfer*` and `/tmp/rng029-baseline60*`.

### A waypoint derived from the goal's syntax takes RNG029-5 from 4000s to 6.7s

The first waypoint this project has *generated* rather than drafted or mined.
`scripts/residual_probe.py`, no prover and no model: expand the conjecture's two
sides in the free non-associative ring, and solve for the residual over a basis
of **universal** associator expressions -- terms true of any ring, so the answer
assumes nothing about alternativity and cannot smuggle in the axioms meant to
discharge it.

RNG029-5's residual comes back as **two terms**:

    (xy)(zx) - x((yz)x)  =  (x, y, zx)  -  x * (y, z, x)

so the conjecture holds exactly when
`associator(X,Y,multiply(Z,X)) = multiply(X,associator(Y,Z,X))`. Supplying that
one equation as an axiom:

| RNG029-5 | `--no-flatten-goal` | `--flatten-goal` |
|---|---|---|
| baseline | Timeout 4000s | Timeout 4000s |
| **+ the derived bridge** | **Unsatisfiable 6.7s** | Unsatisfiable 10.2s |

The bridge itself does **not** prove at 60s standalone, which is the honest
shape of the result: the decomposition is exact, so the bridge carries the whole
difficulty. What it buys is that the difficulty is now a single structural
obligation in the theory's own language, instead of a conjecture about products
-- which is what "waypoint" has meant in this file all along, and what eight
agent runs failed to invent. RNG033-8 decomposes the same way, into five terms.

**The integer constraint is not a formality.** The same residual over the
problem's *own* polarized axioms is in the rational span with coefficients of
1/2, and dividing by 2 is valid only in a ring without 2-torsion, which the
alternative-ring axioms do not provide. A Hermite-form solve over ℤ finds an
honest certificate -- 52 terms, largest coefficient 100. That certificate is a
genuine algebraic derivation of the target from the axioms, and it is **not a
decomposition**: it proves the conjecture without suggesting anything to prove
first. Length is what separates a route from an identity.

Two pieces of machinery earned their place. Polarization turns
`associator(X,X,Y) = 0` into `associator(X,W,Y) + associator(W,X,Y) = 0` --
`alt12_additive`, a node of the successful sketch that models keep failing to
prove. And the basis choice decides everything: the same target over raw
monomials gives a 52-term identity with coefficients past 100, and over
associator terms gives two.

#### The scaffold below the waypoint is generated too

The bridge is a restatement, so on its own it moves the difficulty rather than
reducing it. What makes it a *route* is that everything beneath it is derivable
by the same machinery, and cheap. (That first sentence carried the whole result:
see "A restatement is not a decomposition" below for what it cost an iterating
loop across eleven runs.) Verified against RNG029-5's own axioms, 60s a node,
deterministic build:

| node | how it is derived | cpu |
|---|---|---|
| `assoc_add_1/2/3` -- the associator is additive in each argument | universal, expands to 0 | 30.2 / 29.8 / 29.8s |
| `lin_left`, `lin_right` -- `associator(X+Y,X+Y,Z) = 0` etc. | instance of an axiom | **0.01s** |
| `alt12`, `alt23` | polarization, given `lin_*` + the two additivity lemmas it uses | **0.02s** |
| `assoc_cyclic` | integer certificate over `alt12`/`alt23` instances: `+1*alt12[X,Y,Z] -1*alt23[Y,X,Z]` | **0.01s** |
| `bridge` | the associator decomposition of the goal | unproven at 60s **and at 300s**, both directions |
| the conjecture | given `bridge` | **6.7s** |

Eight nodes, ~150s of new prover time, and every one of them produced from the
problem's own axioms and the goal's syntax -- no donor, no retrieval, nothing
from `scripts/rng_dag.py`.

Two things this pins down. **`alt12` goes from unproven at 60s to 0.02s when
given the three lemmas its own polarization uses**, which is the ~3000x
direct-parent effect this file records elsewhere, arrived at from the derivation
rather than from a guess -- and the derivation *names* those parents, which is
what the drafting model never manages. And the whole scaffold reduces RNG029-5
to exactly one obligation, `associator(X,Y,ZX) = X*associator(Y,Z,X)`, which is
the theorem's actual content: the analogous `right_moufang` in the hand-built
sketch cost 193.6s and needed its own decomposition beneath it.

`assoc_add_1/2/3` at ~30s each trip the diagnostic threshold, so by this file's
own rule a node is missing under them too.

#### Why the last step is hard, stated exactly: the linear route reaches 2x it

Recursing the generator on the remaining obligation -- closing the *proved*
lemmas (`alt12`, `alt23`, `assoc_cyclic`) under bounded consequence at degree 4,
912 elements, and solving for the bridge -- returns:

- **`2 x bridge` IS an integer combination** of the alternating laws (68 terms).
- **`bridge` is not.** It sits in the rational span with a factor of 1/2, and
  the solver reports where: `-763 is not divisible by 2`.

So the linearised alternative laws give exactly twice the Moufang residual, and
recovering the residual itself requires a ring without 2-torsion -- which
`RNG003-0.ax` does not assume. That is a precise, mechanical account of why this
family resists: the cheap linear route provably cannot finish, and the remaining
step needs a genuinely non-linear argument rather than more bookkeeping.

It also retires the idea that the integrality check was a formality. The same
system over ℚ "solves" and would have produced an unsound waypoint; the
distinction is the whole diagnostic.

### The standalone retry cost 8620.8s and answered the wrong question

`verify` re-attempted every failed node with all of its parents removed, at the
same budget that had just failed, racing both directions, on the layer's critical
path. `scripts/retry_cost.py` measures what that came to, over the 84 archived
`dag.json` files (3,478 rows):

| | rows | CPU |
|---|---|---|
| `scope_retry`, non-reused -- real prover time | 81 | 8,620.8s |
| ...that proved nothing | **75** | **8,532.8s -- 99.0%** |
| ...that proved something | 6 | 88.1s |

308 `scope_retry` rows exist; the ledger served 227 of them. A ledger-side count
of all empty-support CPU comes to 23.5% of everything ever spent, but it cannot
separate the automatic retry from deliberate `--scope none` control arms, so the
`dag.json` figure is the one to quote.

Three things were wrong with it, and only the first is about the price.

**It contradicted rule 1.** "Budget is a diagnostic, not a resource" -- and this
was the one place the code re-spent a budget that had just failed.

**It was all-or-nothing.** Dropping every parent cannot say *which* edge is
wrong. On `teichmuller` -- five parents, three of them trilinearity and off the
derivation path -- the useful answer is "drop those three", and the retry could
only ever say "not these five".

**It fired where scope is provably irrelevant.** Parents are proved or `given`
lemmas, so they are already entailed by the axioms and the model class is
identical with or without them. A saturated verdict cannot change when they are
removed. 75 of the 81 fresh retries were re-deriving something already settled.

**The certificate answers the same question for free.** twee names the supplied
axioms it used, both in the proof's axiom listing and in each rewrite step
(`= { by axiom 2 (parent_2) }`). Over the 154 proved parented artifacts on
record:

> **307 parents supplied, 143 cited in the certificate -- 164 (53%) never
> cited.** 89 of 154 proved runs carried at least one. `final` proved once with
> **0 of 21** used (91.5s); `assoc_of_sum_left` repeatedly at 39-57s with
> **0 of 3**.

What that does and does not license matters. It is exact about the certificate
and silent about the search: `agent/ledger.py` exists because a reordered axiom
list is a different search with its own outcome, and removing one is a larger
change than reordering. So an uncited parent is a hypothesis, and `agent/loop.py`
drops it **on probation** -- the next iteration re-runs the node anyway, and
anything that came back slower or stopped proving has its parents put back
automatically, at no prover cost. The agent is told both times.

Two guards were found by writing the tests rather than the code. A drop is
skipped when it would leave the parent with no children at all, because
`_target_node` falls back to the unique sink and an orphaned lemma is a second
one -- a drop can otherwise cost the run its target. And the node named by the
current probe is never touched, or `score_outcome` credits the controller's edit
to the agent.

**What this gives up, stated plainly.** The six retries that did pay off proved
in 2.7s, 3.1s, 8.4s, 8.6s, 8.9s and 56.4s -- and every one of them under
`--flatten-goal`, the *second* of `DIRECTIONS`. Five of the six would fit inside
a 15s two-direction probe. That probe was designed and then cut, because no
leave-one-out arm has ever been run here and nothing in this file should rest on
an unmeasured mechanism. If the loop starts stalling on wrong edges, a
*planner-requested* empty-support probe on a named node is the cheap thing to add
back -- not an automatic one.

### Blocked is worse than failed, and the loop could not tell

First model run on a derived sketch (`--derive`, gpt-5.4, 10 iterations,
2,120.2s charged / 728.6s new, no proof). The scaffold behaved: iteration 0 cost
**0.0s of new prover time** because the ledger already held it, and the model
opened on 11 proved nodes and one named obligation.

Then it subdivided that obligation, replacing the bridge's seven **proved**
parents with three intermediates that did not prove -- and the run went blind
for nine iterations. `verify` schedules a node only when every parent has
proved, so:

| | iter 0 | iters 1-9 |
|---|---|---|
| bridge | `failed` -- ran, 60.1s, left an artifact | `blocked` -- never scheduled again |
| goal | blocked | blocked |
| target attempt | skipped | skipped |
| `goal_contact` | none | none |

With the target never attempted there is no contact, with no contact there is no
`regressed` verdict, and with no regression there is no revert. **The one edit
that mattered was invisible to every instrument the loop has.** A node that runs
and fails is strictly better than one that cannot run: the failing one produces
a search, candidates and a contact reading, and the blocked one produces
nothing. The loop now reports a blocked goal every turn at reject severity and
names the whole dead chain, nearest first.

Two smaller faults from the same run. The model wrote the full equation into
`lhs` *and* supplied the correct `rhs` seven times -- and the repair for that
shape bailed whenever `rhs` was set at all, so `well_formed` rejected every one.
Six were confirmable, since the right half and the supplied `rhs` agreed
verbatim; a seventh was a `=?` truncation where `rhs` is authoritative. Only two
genuinely different claims about the same side stay rejected.

The derived scaffold itself needs no defence: it was ledger-served at zero cost
and the model never had to invent it. What this run tests is what the loop does
when the model damages a derived sketch, and the answer was: nothing, silently.

### Depth to the running frontier is the signal; contact on a derived sketch is not

Two model runs on derived sketches, same problem, same model, same budgets. Both
made the same first move and lost the same way, and the numbers say why.

|  | derive-01 | derive-02 |
|---|---|---|
| iterations / new CPU | 10 / 728.6s | 10 / 1,202.4s |
| depth at iteration 0 | 1 | 1 |
| after the iteration-0 subdivide | **2** | **2** |
| recovered? | no, 9 iterations | no |
| distinct contact sources | 3 | 6 |
| iterations with a comparable delta | 7 | 2 |

Both open at depth 1: the single obligation runs, fails, and leaves a search.
Both subdivide it into intermediates that do not prove, which takes it out of
the schedule entirely -- `verify` runs a node only when every parent has proved
-- and the nearest thing to the conjecture that still runs is a step further
away. Neither recovered.

**Contact alone could not see this.** The proxy gives a reading at nine of ten
iterations, but the source moves whenever the sketch does, and readings from
different nodes cannot be differenced: derive-02 had six sources and a
comparable delta at two iterations. **Depth could**, at the iteration it
happened, in both runs, from one integer.

So a depth increase now scores `regressed` and reverts, and it fires exactly at
the deciding edit in both runs (and again at derive-01's iteration 8, 2 -> 4).

Two guards, both learned from the same runs. A decrease is never a retreat, so
repairing the chain costs nothing. And **depth 0 is not a baseline to fall
from**: derive-02 reached it at iteration 5 by *disconnecting* the goal, which
makes it verify standalone and score the best contact of either run (`both` 7).
Holding that as the mark would reward severing the goal and punish reattaching
it, so a previous depth of 0 is ignored -- a disconnected goal is reported on
its own.

**And the blocked-goal report added before this was the wrong instrument.** A
derived sketch begins with a blocked goal by construction, since the bridge is
unproved at iteration 0, so reporting it every turn is noise; the model read it
at reject severity for nine consecutive iterations in both runs and correctly
ignored it. What discriminates is not whether the goal is blocked but how far
the blockage has pushed the frontier.

## The assumption set is the binding constraint, and it is not monotone (2026-08-17)

Established while checking, at Yousef's insistence, whether a "this decomposition
does not work" conclusion was really about the decomposition or about a badly
chosen assumption set. It was worth checking: one of the two conclusions it was
testing turned out to be wrong, and the check produced a sharper result than the
thing it was auditing.

All timings are the deterministic build, 300s node budget, both goal directions
raced, one sample per configuration. Reproduction drift against the archived
manual run is about 10% (`right_moufang` 197.8s here against 192.6s recorded,
`middle_moufang` 124.2s against 112.2s), so differences under ~25s are not
readable.

### Each node has a core, a set of poisons, and ballast -- and they differ per node

Sensitivity to the supplied set is NOT the single rule "more is worse". Two nodes
of the same family, one hop apart on the same route, behave completely
differently.

`right_moufang` is a knife edge. It proves in 197.8s from exactly
`{assoc_cyclic, assoc_def_246, assoc_def_247}` and from nothing else tried:
dropping any one member times out, and so does ADDING `assoc_def_add` -- which is
universal, proves in 0.0s, and is the lemma the other two are built from. Adding
`cp24`, also true and also cheap, likewise times out.

`middle_moufang`, its child, has a tolerance band:

    manual four                            124.2s
    drop assoc_cyclic                       97.0s     FASTER than the manual set
    drop assoc_def_246                     216.1s
    drop assoc_def_247                     timeout
    drop right_moufang                     timeout
    add assoc_def_add                      233.1s
    add assoc_xyx                          219.0s
    add flexible                           timeout

So `assoc_def_247` and `right_moufang` are core, `assoc_cyclic` is ballast that
costs 27s, `assoc_def_add` and `assoc_xyx` are tolerated at roughly 2x, and
`flexible` is a poison -- true, cheap, on the route, and fatal here while
harmless elsewhere. Which lemma is which cannot be read off the lemma; it is a
property of the pair.

### A CITED parent can still be worth dropping

The mechanism that already exists for this -- `probation_drops` on
`unused_support` -- cannot find the 27s improvement above, because the parent it
would need to drop is cited:

    m1 (manual four)   124.2s   used=[assoc_cyclic, assoc_def_246,
                                      assoc_def_247, right_moufang]  UNCITED=[]
    m2 (without it)     97.0s

`_support_usage` already warns of the converse, that an uncited parent is not
thereby proven droppable. This is the other direction and it is worse: removing
an axiom changes the rewrite system, so twee finds a DIFFERENT and shorter proof,
and the certificate of the run you have cannot predict that. Citation is a fact
about the proof found, not about whether the parent helped the search. Probation
therefore addresses only the uncited half of the space, and in this instance the
wrong half. Assumption-set choice has to be driven by measurement.

### The derived seed's obligation resists 45 assumption sets

`derive.py` reduces the conjecture to one obligation, the bridge

    associator(X,Y,multiply(Z,X)) = multiply(X,associator(Y,Z,X))

and every loop run on record attempts it with the same 7 parents and times out at
60s, never `saturated`. Swept properly it fails from standalone upward: 12 sets
in the first pass and 39 in the second -- every singleton over a 12-lemma pool,
every pair over the 7 plausible ones, and six triples including
`{def_246, def_247, perm_201}`, which is the exact structural analogue of
`right_moufang`'s working triple. Nothing proves at 300s.

This does not show the bridge is unprovable; there are 220 triples over that pool
and six were tried, and `right_moufang` demonstrates a single triple can be the
only one that works. What it does show is that the bridge is a bad decomposition
TARGET: the conjecture itself proves in 97-124s from four parents, so the seed
reduced a reachable goal to an obligation that is harder than it, and the
successful manual proof never proves the bridge at all.

### The definitional rearrangements are derivable and were missing

`derive.py` emits additivity, polarizations and permutation symmetries, and every
one of them relates associators to associators; the conjecture is pure
`multiply`. The rules that cross between the two vocabularies are mechanically
derivable and were absent. `associator(X,Y,Z) + X(YZ) = (XY)Z` expands to zero,
so it is universal and checkable; the two variants the manual route uses are that
composed with lemmas the seed ALREADY derives --

    def_246 residual = (X,Y,Z) - (Y,Z,X)  = assoc_cyclic     (= associator_perm_201)
    def_247 residual = (X,Y,Z) + (Y,X,Z)  = alt12_additive   (= left_alternative_polar)

-- and all three ground in 0.0s once added. Adding them does not make the bridge
provable, which is what condemns the bridge rather than the lemma set.

### Most of a hard node's derivation is already in the loop's evidence

`right_moufang`'s own proof is 131 lemmas, 26 deep. Cross-referenced against six
loop runs' evidence banks, **23 of the 27 steps on its critical path are already
there**, including the lemma directly beneath it,
`associator(Y,Z,multiply(X,Y)) = associator(X,Y,multiply(Z,Y))`, which is in 6 of
6 banks and which takes `right_moufang` from 192.6s to 0.0s when supplied. The
loop derives nearly the whole derivation and never assembles it -- but per the
knife-edge result above, assembling it is not the easy part either.

`middle_moufang` fails differently: its critical path is 14 steps, 9 are in the
banks, and the 5 missing ones are d8 through d12 unbroken -- the
product-of-products manipulation, which no run's search produces at all. A
scattered gap and a contiguous one are different problems and should not be
reported as one.


## A restatement is not a decomposition, and the machinery cannot make one (2026-08-17)

Eleven loop runs on a derived RNG029-5 seed, across four code configurations,
produced no proof and no meaningful refinement of the sketch. The reason is one
property of the seed that was recorded when the waypoint was first built -- "the
bridge is a restatement, so on its own it moves the difficulty rather than
reducing it" -- and whose consequence for an ITERATING loop was not followed
through.

### The bridge is equivalent to the conjecture, by construction, on every problem

Not approximately, and not only on RNG029-5. `freering.expand` of the bridge and
of the conjecture return the identical residual:

    conjecture: add(associator(VCX,VCY,multiply(VCZ,VCX)),
                    additive_inverse(multiply(VCX,associator(VCY,VCZ,VCX))))
    bridge:     add(associator(VCX,VCY,multiply(VCZ,VCX)),
                    additive_inverse(multiply(VCX,associator(VCY,VCZ,VCX))))

    RNG029-5  bridge==goal: True   RNG028-7  True   RNG027-5  True
    RNG033-8  bridge==goal: True   RNG025-4  True

It cannot be otherwise. `derive_sketch` has two branches and both restate the
residual: a two-term residual becomes `A = B`, anything else becomes
`residual = additive_identity`. Neither can produce a statement weaker than the
conjecture, so the seed emits no waypoint in the sense this file uses the word --
it emits the goal in the theory's own language.

**What that costs an iterating loop, as against a single verification.** Supplying
the bridge as an axiom does take the goal from a 4000s timeout to 6.7s, which is
what the original entry measured and is real. But a run that must PROVE the
bridge starts from a sketch with no interior: axioms, some scaffold lemmas, and
one obligation that is the whole problem. Every observation across the eleven
runs follows from that.

  * The frontier sits at depth 1 in every run -- there is only ever one open
    node and it is the conjecture.
  * The goal "proves from the bridge" in about 5s in every run. It is a
    restatement; that number measures nothing.
  * Nine of eleven runs never edit the bridge. It presents as a reasonable single
    node with seven parents.
  * Its own search scores `goal_contact both = 0` while touching each side in the
    hundreds (lhs 118, rhs 521).
  * It resists 45 assumption sets at 300s, standalone included -- as the
    conjecture should, its baseline being a 4000s timeout.
  * The successful manual proof never proves it at all.

The loop's actions all operate on structure -- `subdivide`, `set_parents`,
`redraft` -- so with no structure to operate on its edits necessarily land
BESIDE the single step rather than along a path. "The sketch is not being refined
meaningfully" is the correct reading, and this is the mechanism.

### The mechanical machinery cannot produce a real waypoint

Everything `derive.py` emits -- additivity, polarizations, permutation symmetries
-- is a linear consequence over the free ring, found by `freering.certificate`.
That is a real capability and it is bounded: the goal is NOT a linear consequence
of the scaffold. `certificate` cannot express `middle_moufang` over a basis of
the scaffold plus `right_moufang` under every renaming, even though that is
exactly the manual route -- because the step is 112.2s of equational search, not
a combination. The gap that matters lies outside the linear span, and a change of
representation is the only move the machinery has left when it reaches that edge.
The bridge is what that move produces.

### And the evidence bank cannot supply it either -- structurally

Across 20 evidence banks from every archived run, each route step and how many
banks hold it:

    assoc_def_add     20/20      assoc_cyclic      13/20
    assoc_xxy         20/20      assoc_def_246     13/20
    assoc_xyx         20/20      alt12/alt23       13/20
    flexible          20/20      assoc_def_247      4/20
    assoc_add_1/2/3   15-16/20   middle_moufang     6/20
                                 right_moufang     0/20

Nineteen of twenty route steps appear. `right_moufang` -- the 192.6s step the
whole route turns on -- appears in none. That is not sampling noise, it is
definitional: a bank holds what searches derived CHEAPLY, and a waypoint earns
its place by being what they do not derive. **A waypoint cannot be mined out of
the searches that failed to reach it.**

Which is why the evidence work moved gold recall not at all -- grounded means
10.0 with neither change, 9.0 with the scheduler alone, 10.0 with the bank fully
delivered. It made the cheap distribution visible, and the cheap distribution is
where the answer is not.

### What a waypoint has to be, and the check that is missing

A waypoint must be strictly between the axioms and the goal. Both ways of missing
that are on record here and neither is detected before prover time:

  * **Equivalent to the goal.** The bridge. No progress is possible, and the loop
    spends its iterations elsewhere because there is nowhere else to spend them.
  * **Stronger than the goal.** RNG029-5-bank-02 proved the bridge in 0.009s from
    four unproved parents, two of which asserted that the terms it was concluding
    were zero -- `multiply(X, associator(Y,Z,X)) = additive_identity` being the
    bridge's own right-hand side. `dag.grounding` refused it, which is the guard
    working, but nothing had stopped the node being PROPOSED.

Residual comparison decides which of the three a proposal is, before any prover
time, and nothing currently does it. Note the asymmetry that makes this hard:
the manual route's waypoint is not linearly derivable either, so CLASSIFYING a
proposal is mechanical while GENERATING one is not. That is the open problem,
not a missing function.


### The classifier is built, and the seed repair is where it pays

Residual comparison now decides where a proposal sits relative to the
conjecture, before any prover time: `freering.classify` returns `exact`,
`equivalent`, `instance`, `distinct` or `unsupported` in microseconds -- 29 nodes
in 0.015s.

**It is safe to act on, which had to be checked before it was wired.** A check
that condemned any node of the one decomposition known to work would forbid the
only route this project has. Over the 29-node manual sketch exactly one node is
not `distinct`: `middle_moufang`, which *is* RNG029-5's conjecture under another
name. The derived bridge classifies `equivalent`, as it must.

**Only an exact syntactic duplicate is rejected.** `equivalent` and `instance`
are reported as `no_decomposition` and never counted as structural progress --
a node so classified that proves scores `inconclusive`, so it cannot clear the
stall counter and buy four more iterations. Rejecting them outright was the first
design and is wrong: supplying the bridge really does take RNG029-5 from a 4000s
timeout in both directions to 6.7s, so an alternative representation has measured
value; it simply is not a step. (Credit to Codex's review for both corrections,
and for catching that dropping the bridge would leave the goal parentless.)

**Where the value actually is, measured.** Across **193 proposals from every
recorded run, one** was a restatement -- `goal_difference_zero`, aug-13-03
iteration 6. The reviewer half is cheap and correct and will rarely fire. What
dominated twelve runs was the *seed*: `derive_sketch` planted the decomposition
as the goal's only parent, and that node was the conjecture. It is now reported
as a diagnostic and not emitted, and `--derive` exits `no_waypoint_found` rather
than launching a run whose goal nothing supports -- because a run with a
parentless goal is the configuration already measured as blind, and refusing to
start is the correct outcome rather than a fallback.

**A general linear-redundancy check is not affordable.** Asking whether a node
lies in the linear span of the proved scaffold -- the natural way to separate
bookkeeping from real content -- did not finish in **600s** on RNG029-5. It
belongs offline under a budget, never in a reviewer that must cost microseconds.

What remains untouched is generation, exactly as the previous entry said: the
machinery can now say what a proposal is NOT, and still cannot produce one that
is strictly between the axioms and the goal.

### The waypoint pilot: generation is cheap, support is the whole problem

`scripts/waypoint_pilot.py` enumerates a bounded space of statements and
measures them, since the mechanical route cannot derive one. Two things came out
of running it, and the first correct one is not what the first write-up of this
entry said.

**Enumeration is not the hard part.** `freering.balanced_candidates` takes the
conjecture's own degree and variable-multiplicity partition and emits the
word-preserving rebracketings: 59 statements for RNG029-5, in 0.07s, containing
the right-Moufang identity under alpha and orientation normalisation and never
naming it. Nine of the 59 are consequences of the scaffold, found by giving each
one second with it supplied -- a practical form of the redundancy question whose
linear-algebra version did not finish in 600s.

**The seed was missing a lemma, and that is why the upstream arm could not
win.** `right_moufang` needs `assoc_cyclic`, `assoc_def_246` and
`assoc_def_247`. The scaffold had the first as `associator_perm_201` and could
not reach the other two: both are theory-specific (residue 4), so no universal
check emits them, and no certificate over the scaffold certified them. The
missing ingredient was one *universal* identity the seed simply never generated
-- the operator's own definition rearranged:

    associator(X,Y,Z) + X(YZ) = (XY)Z          residue 0

read straight off the normal form by moving the negative monomials across, and
mechanical for any defined operator (`commutator(X,Y) + XY = YX` by the same
rule). With it present both variants are certified from what is already derived,
in both orientations -- `assoc_def_247` is the anti-symmetric one,
`associator(X,Y,Z) = -associator(Y,X,Z)`. The scaffold went from 12 claims to 19
and now contains all three lemmas the waypoint needs.

**With them, the upstream arm wins outright:** the scaffold proves right-Moufang
in **179.2s**, against the manual route's 197.8s, and with the FULL 18-lemma core
rather than a hand-picked subset.

**Downstream is where support selection actually bites.** The same lemmas, the
same prover, only the size of the set differs:

| support for the conjecture | result |
|---|---|
| the exact four: cyclic, both def variants, right-Moufang | **Unsatisfiable 67.9s** |
| all 19 derived lemmas, which CONTAIN those four | **Timeout at 300s** |
| right-Moufang alone | Timeout at 300s |

Fifteen additional true, proved, derived lemmas turn a 67.9s proof into a
timeout. That is the poisoning effect `race_support` documents, measured here on
the step that matters, and it is the reason the pilot cannot close the chain by
itself: full, bare and leave-one-out never construct a 4-subset of 19.

**So the honest statement is that support is the bottleneck in two different
ways, and only one of them was combinatorial.** Availability -- whether the
needed lemma exists in the scaffold at all -- was a gap in the generator and is
now fixed. Selection -- which handful of the available lemmas to supply -- is
combinatorial, is worth a factor of at least 4.4x here, and nothing in this
project predicts it: the parent worth dropping is one the certificate CITES, so
`unused_support` cannot see it either.

Every lemma in the chain is derived from the problem file by `derive.py`. What is
not yet autonomous is choosing the four.

**One more selection bias worth recording.** Evidence ranked by source count is
the problem's own axioms -- the top four on RNG029-5 are `(XX)Y = X(XY)`,
`(XY)Y = X(YY)` and both again in associator form, which twee already has, so
assuming them changes nothing and the screen returned 0 hits in 59 candidates.
What every search re-derives is what every search already had. Ordering by
`evidence.relevance` after dropping axioms and scaffold yields real material.

### Support selection: the channel does not save it, and sampling cannot reach it

Two results, and a harness fault found on the way that matters more than either.

**A crash was being reported as a mathematical negative.** `race_support` named
each artifact after its assumption set's label, and an eighteen-lemma set joins
into 359 characters. The filename went past NAME_MAX at 255, `_job` raised,
`_support_worker` turned it into an Error row with `cpu 0.0`, and the sweep
printed **"none proved ... resists every set tried, standalone included"** -- a
clean negative from a run that never reached the prover, in 0.0s, with no
artifact on disk. Long labels are now hashed for the filename and kept whole for
the report, and `support_sweep.py` counts Error rows and says outright that a run
carrying any is not a measurement. The sweeps already in this file are unaffected:
they ran at sizes 0-2, whose labels are short.

**The channel does not dissolve the problem.** Supplying the whole pool as hints
rather than axioms is the one cheap move that could have, since a hint adds no
critical pairs -- and FINDINGS records the inversion on MVA005-1, 20 lemmas as
axioms timing out where the same set as hints proved in 173.6s. Measured here on
a 19-lemma pool that CONTAINS a sufficient four:

| channel | result |
|---|---|
| the exact four, as axioms | **67.9s** |
| all 19, as axioms | Timeout at 300s, both directions |
| all 19, as hints | Timeout at 300s, both directions |

So the RNG counter-evidence generalises: 234 mined lemmas in the hint channel
flipped nothing here either, and `alt12` never proved from any hint
configuration. Selection cannot be avoided by changing how the set is delivered.

**And uniform sampling cannot find the set.** A losing arm costs 90s x 2
directions; the winner proves in 67.9s. If winning sets are roughly unique:

| space | sets | expected sampling cost |
|---|---|---|
| C(18,3) | 816 | ~73,000s |
| C(18,4) | 3,060 | ~275,000s |
| C(14,3) after dropping the 3 commutator lemmas the goal never mentions | 364 | ~33,000s |
| C(8,3) | 56 | ~5,000s |

Nothing above a pool of about eight is affordable, and the planned randomised
sweep was not run because the arithmetic answers it: at one winner in 816, 24
samples buy a bound of "density < 1/24" that the prior already implies.

**So pool reduction is the prerequisite, not an optional refinement.** The
question is not how to search 3,060 sets but how to get the pool to eight
without losing the answer -- and any reduction has to be checked against the
known winning set before it is trusted, exactly as the goal classifier was.
Operator relevance alone (a lemma about an operator the target never mentions
cannot be on its derivation) takes 18 to 15, which is not nearly enough.

## Axioms and hints are not alternatives, and an arm should use both

The pool problem above has an escape the plan did not anticipate: **over-inclusion
can be made free.** Fifteen extra true lemmas turn a 67.9s proof into a timeout
when supplied as axioms. Supplied as hints alongside the same four axioms, they
make it *faster*.

**Why, from the reference implementation.** `build/twee-deterministic/twee-lib-2.6.1`:
`addHint` inserts into `st_hints :: !(Index f (Hint f))` (Twee.hs:89), an index
separate from the rule set, and the only thing that ever reads it is `CP.score`
(CP.hs:258), which charges `hint_cost` for a matching subterm instead of that
subterm's structure. Cost is `(len - nvars)*factor + skel_cost + dup_penalty`
(Twee.hs:618), so at factor 0.5 against `cfg_funweight = 1` a matching subterm
looks roughly half its size and its critical pair is picked sooner.

Two consequences, both structural rather than empirical:

* a hint has **no deductive power** -- it never becomes a rule, so it cannot
  rewrite anything, and a lemma the proof NEEDS cannot be supplied as one;
* a hint **cannot enlarge the search** -- it forms no critical pairs, so it
  cannot poison. Its whole cost is misdirected priority.

That is exactly the asymmetry the poisoning results describe from the other side.

**Measured on RNG029-5's conjecture**, over the 19-lemma derived pool that
contains a sufficient four:

| supply | result |
|---|---|
| all 19 as axioms | Timeout at 300s |
| all 19 as hints | Timeout at 300s |
| the exact four as axioms | 67.9s |
| **the four as axioms + the other 15 as hints** | **56.3s, 1.21x** |

All-as-hints times out for the reason above: hints alone prove nothing, so that
arm is the standalone attempt wearing a costume.

**But hints cannot substitute for a necessary axiom.** With all 19 steering,
`W` alone and each `W + one` pair (perm, def_yzx, def_yxz_neg) timed out at 300s
in both directions -- four arms, no winner. Priority cannot supply an inference
the rule set does not contain. So the necessary set is genuinely larger than two
and the selection problem survives; what changes is its shape.

**What this buys.** The search no longer has to find a *minimal* set, only a
*sufficient* one, because the remainder can always be dumped into the hint
channel at no cost and some benefit. `race_support(..., steer=pool)` implements
this: each arm supplies its own candidates as axioms and everything else in the
pool as hints (`dag.steer_split`). Over-inclusion is now cheap in one direction
only -- under-inclusion is still fatal -- which is why pool reduction remains the
prerequisite and why growing a set beats sampling one.

## Open

Whether McCune's Lemma 2 hints can drive twee through Lemma 2 is **unresolved**.
The first sweep used factor 0/0.2/0.5 but had no baseline and predates the
finding that factor 0 is pathological; the `0.5` arms were killed without
flushing. Rerun with factor 0.5 and a paired 1000s baseline before concluding
anything. The AC-association question is also open: EQP hints are AC-flattened
(`x+y+z`) and the translator picks one association, so some hints may never match.
