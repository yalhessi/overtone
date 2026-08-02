# Expectations

What the neural-guidance work can realistically deliver, anchored in published
results for more mature provers and in the ceilings already measured in
`FINDINGS.md`. Written before any training code exists, deliberately, so the
targets cannot drift to fit whatever comes out.

Read `FINDINGS.md` first for the measurements this reasons over.

## The calibration fact

**The baseline screen solved 18 of the 85 problems rated 1.00, with no hints and
no learning** — correct goal direction and a 1000s budget (`FINDINGS.md`,
2026-08-01). A TPTP rating of 1.00 on a problem whose status is UNS means no
state-of-the-art system solves it within the rating's time limit.

This was written when the number was one problem, ROB033-1. Eighteen is worse for
the thesis of this document, not better: the configuration-and-budget baseline is
far stronger than the ratings suggest, and every gain claimed for learning has to
clear it.

Two more results from the same screen sharpen the point. Goal direction alone
decides 67 of the 175 solved problems, which is the largest effect measured
anywhere in this project. And the solved-time distribution has not flattened at
the 1000s cap — 9 problems solved above 600s — so more of the 121 resisted
problems are probably reachable by spending CPU rather than by guiding search.

Everything below is measured against that bar. Two consequences:

1. The cheapest source of newly-solved problems in this project is configuration
   and CPU, not learning.
2. Any claim that learning flipped a problem must beat that alternative
   explanation, which means a paired baseline at the same budget in *both* goal
   directions. Without it the claim is unfalsifiable.

## What the literature delivered

| system | prover | mechanism | reported gain |
|---|---|---|---|
| ENIGMA (2017) | E | XGBoost on clause features | large, over many loop iterations |
| ENIGMA-NG (2019) | E | neural clause evaluation | ~20% more problems |
| ENIGMA Anonymous (2020) | E | symbol-anonymised GNN | ~40–70% after several loops |
| Deepire (2021) | Vampire | RNN over derivation history only | ~20% more problems |
| ProofWatch (2018) | E | dynamic watchlist/hint weighting | ~10–20% |

These figures are approximate — the shape and rough magnitude are reliable, the
exact numbers less so. Three observations matter more than the numbers:

**The gains are throughput on large homogeneous corpora at short time limits.**
"70% more problems" means many more solved in 10–30s, concentrated in the medium
band. It does not mean the frontier moved.

**ProofWatch is our hint-weighting line, and it is the weakest row.** ~10–20%,
achieved in a more mature prover with more engineering behind it.

**No learned guidance system appears to have settled a previously-open
mathematical problem.** Every ATP success on genuinely open questions — Robbins
(McCune/EQP), Boolean algebra single axioms, AIM progress, lattice axioms — came
from human-authored hints and proof sketches. That is exactly the corpus in
`data/external/veroff/`. If a frontier problem falls here, the prior strongly
favours it falling to hints rather than to a learned scorer.

## Ceilings from our own measurements

Both are oracle numbers, i.e. upper bounds that no learned model can exceed.

**Rule usefulness.** 91–98% of derived rules are waste, which looks like a 20x
prize. But the measured oracle — capping at the highest score any used rule
achieved — prunes 80% of work on hinted ROB and **~0% on LAT**. The ceiling is
therefore 5x on the best theory and nothing on others, before any learning loss.
The `FINDINGS.md` caveat lowers it further: "used" counts only rules referenced
in the post-processed proof, so rules that contributed by simplification are
miscounted as waste, meaning true waste is below the measured figure.

**Hint weighting.** McCune's actual proof steps as hints gave 3.3x and 1.8x on
ROB005-1. That is an oracle — the answer fed in as the hint set. Learned hint
selection is bounded above by it.

Single-digit multiples, theory-dependent, oracle-bounded.

**Against the frontier gap.** EQP needed 678,232s on ROB001-1. Against a 1000s
budget that is ~680x; a 3x win is not in the same universe. But that was 1996
hardware. Single-core throughput has improved perhaps 50–100x since, which would
put the same search in the 7,000–14,000s range today. That is a rough estimate,
not a measurement, and twee is not EQP — but it reframes ROB001-1 as plausibly a
*budget* question nobody has spent the CPU on rather than a guidance question.
Resolve it empirically before using it to motivate any ML.

## Why twee's immaturity cuts both ways

**More headroom:** twee's heuristic surface is tiny next to E's clause-selection
zoo. Less tuning has been done, so there is more slack to recover.

**Less headroom:** twee has won the CASC UEQ division repeatedly. In its niche
the baseline is not weak. Completion-based search also has fewer genuine choice
points than resolution, so there is less for a learner to influence.

**The binding constraint is engineering, not modelling.** twee derived 121,175
rules on the GRP corpus. Per-rule neural scoring at even 100µs adds 12s of pure
overhead per run, against theories where the oracle gain is 0%. E ships ENIGMA
hooks and Vampire ships Deepire; we have Haskell with no scorer API, no feature
extraction, and no per-hint weights. Deepire is the model to copy rather than
ENIGMA-NG: Suda deliberately used derivation history only, no clause content,
precisely so evaluation stayed cheap and cacheable. Assume any design that must
embed rule terms inside twee's inner loop is too slow until proven otherwise.

## Named flip candidates

The screen has already resolved the first tier and shrunk the target set: the
candidate pool is no longer the 156 rated >= 0.9 but the **121 that resisted both
directions at 1000s**. The 175 solved problems are now baselines, not targets.

| tier | problems | why | odds |
|---|---|---|---|
| already done | 18 problems rated 1.00, incl. ROB033-1 and 10 of 11 MVA | config + budget, no learning | done |
| best | ROB034-1, ROB032-1, ROB032-2, ROB031-1, ROB025-10 — all UNS@1.00, all in the resisted set | same theory as our successes, oracle hints in hand, ladder structure means Lemma hints should transfer | plausible |
| bulk | the 85 UNS@1.00, especially GRP (20) and LCL (14) | UNS means provable in principle; GRP's 500 UEQ problems give the densest donor pool for hint mining | a handful, maybe |
| prize | ROB001-1 | route is McCune + Veroff `r2h.in` hints + 24h + both goal directions, *not* learning | one honest attempt |
| do not promise | 48 UNK (30 of them BOO), 7 OPN incl. ROB027-1, ROB007-1 | genuinely open mathematics | no |

**The donor channel is empty at the frontier.** Measured after the harvest: TSTP
covers 100% of the UNS problems rated < 0.3 but only **5.8% of the 156 rated
>= 0.9** (see `FINDINGS.md`). Since those 156 are the flip candidate set, every
frontier hint has to be transferred from an easier problem — there is no
same-problem donor to mine. Two consequences for the tiers above: the "bulk" row
is weaker than its problem count suggests, because GRP's 500 UEQ problems are
donors for the easy band and not for the 20 GRP problems at 1.00; and the "best"
row holds up, because its hints come from McCune and Veroff rather than TSTP.

Plan for the distribution shift explicitly. A hint-mining model trained on TSTP
sees almost only easy problems and is evaluated where its input channel is 94%
empty. That is a harder problem than the train/eval split, and it is the main
reason to expect the measured gains to land in the medium band.

ETP's 1062 Vampire-unresolved implications look attractive — 19x TPTP's UNK+OPN,
uniform signature, no symbol bridge needed. Check before counting them: ETP was a
community effort and many were likely settled afterwards by Lean proofs or finite
counterexamples. "Vampire did not resolve it in 2025-08" is not "open".

## Sequencing

**1. Replicate a Twitch result before anything else.** Confirms our twee build,
hint encoding and flags match what the authors treated as a good configuration.
Without this, a weak result later is ambiguous between "the method is weak" and
"our setup is wrong". Target and outcome tracked in `docs/RUNS.md`.

**2. Run the high-budget screen before writing any training code.** Both goal
directions, realistic budget, over the 156 problems rated >= 0.9 plus the 0.7–0.9
band (140 more). Worst case ~310 CPU-hours, far less in practice since successes
terminate early.

It is the prerequisite for everything else: it identifies which problems sit
within a small multiple of budget — the only ones any realistic gain can flip —
produces the paired baselines without which no result is interpretable, doubles
as the label source for rule-usefulness training, and may flip problems on its
own, as ROB033-1 did. `FINDINGS.md` records that a bad 30s screen invalidated
three experiment designs.

**3. Static configuration selection is dropped.** Earlier revisions of this
document argued it should be line of work #1, on the grounds that goal direction
is the largest single effect measured. Both the data and the argument have moved
against it.

The data: 108 of 175 solved problems solve in *both* directions, so direction
decides 67, and a per-theory lookup table already keeps 91% of solved problems at
half the CPU. Headroom for a learned chooser is 15 problems.

The argument, which is the decisive part: the remaining benefit is a ~2x CPU
saving, and **we are not CPU-bound**. 64 cores against 121 open problems means
running every configuration in parallel costs nothing in wall-clock. A portfolio
dominates a predictor whenever the configuration space is small enough to
enumerate, and twee's is. Predicting a config you could simply have run is not
worth building.

**4. Dynamic reconfiguration is the version worth pursuing — and in twee it
mostly means adaptive bounds.** Not every knob can move mid-run:

| knob | switchable mid-run? |
|---|---|
| goal direction | **no** — set at parse time, changes the encoding; restart only, i.e. a portfolio |
| KBO term ordering | **no** — completed rules depend on it; changing invalidates the rewrite system |
| weight / size / CP limits | **yes** |
| hint costing | **yes** |
| critical-pair selection | **yes** — but this *is* the rule-usefulness line, relabelled |

So the genuinely new territory is adaptive resource bounds, and `FINDINGS.md`
now has the measurement supporting it: an oracle score cap prunes a median 58.6%
of derived rules, rising to 92–98% in LCL, ROB and CSR — three of the four
theories where twee's solve rate is *lowest*. Headroom concentrates where we are
weakest, which is the opposite of the usual pattern.

Why this could flip problems rather than just speed them up: a weight bound is
not a constant-factor prune. It changes the shape of the search. A bounded run
can saturate and terminate where an unbounded run diverges into ever-larger
terms, which is qualitatively different from a 5x speedup. The precedents are
real — McCune's Robbins ladder (`max_weight` 21/30/34/50/60/70/100, bracketing
our measured median used-cap of 55) and Vampire's limited-resource strategy,
which discards clauses it estimates will never be reached in the remaining
budget.

The first experiment needs no learning at all: run the 121 resisted problems
under a ladder of `--max-term-size` bounds and see whether bounded runs saturate
quickly, and whether any bound finds a proof the unbounded run missed. Establish
that the mechanism has headroom on the population we care about *before*
learning to control it. If it does, the learned component is "when to raise the
bound" — a far better-posed problem than clause selection, with an oracle we can
already measure.

**4. Pre-register the candidate set and the budget.** Expected yield is a handful
of flips out of ~156. At that N, choosing after the fact which problems count
makes the result unfalsifiable. `docs/RUNS.md` is the pre-registration.

## Summary of what to expect

| outcome | likelihood |
|---|---|
| 10–30% more problems solved at fixed budget in the medium band | likely |
| 2–5x speedup on specific theories with strong signal (hinted ROB) | plausible, theory-dependent |
| ~0 gain on theories where the oracle is flat (LAT) | expected |
| A near-frontier problem flips, attributable to learning over a paired baseline | possible, small N |
| ROB001-1 falls | unlikely, and if it does, to hints and CPU rather than learning |
| A UNK/OPN problem falls | no |
