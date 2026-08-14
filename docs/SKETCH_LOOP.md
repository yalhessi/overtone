# The sketch loop

A design for transferring human-style proof sketches into twee's hint channel,
and refining them from the prover's failure state.

This is P1 in `docs/EXPECTATIONS.md`. Read that first for why this line is
prioritised over learned in-loop guidance, and `docs/FINDINGS.md` for the
measured constraints the design has to respect.

## Why this line

Three facts, each measured or sourced rather than assumed:

1. **Curated hints are the only intervention with open-problem kills on its
   record.** Robbins, Boolean algebra single axioms, AIM progress, lattice
   axioms — all came from human-authored hints and proof sketches, not learned
   guidance. See EXPECTATIONS for the literature survey.
2. **Mined hints cannot serve the frontier.** TSTP donor coverage is 100% below
   rating 0.3 and **5.8% at >= 0.9** (FINDINGS). The problems we care about have
   no same-problem donor to mine, by construction — TSTP runs at competition
   time limits.
3. **The Twitch authors name this gap themselves.** §7 of
   [arXiv:2603.06849](https://arxiv.org/abs/2603.06849): "we do not attempt to
   automatically generate related or weakened conjectures in the style of proof
   sketches". We hold Veroff's corpus, which is exactly that material.

## Prior art, and what is actually new

Hints are not twee-specific. The same mechanism exists across the
saturation-prover family, which matters because it makes the method portable:

| prover | mechanism |
|---|---|
| Otter / EQP / Prover9 | native `list(hints)`; matched clauses get priority |
| E | **watchlist**; ProofWatch made it dynamic, steering by proof-completion ratios |
| twee | `$hint` + `--hint-skel-factor` / `--hint-skel-cost` |

What exists already:

- **Veroff's proof-sketch method** is this loop run by hand: prove weakened
  variants of a hard conjecture, use their proofs as hints, iteratively
  eliminate the added assumptions. It is the manual version of everything below.
- **ProofWatch / ENIGMAWatch** load many previous proofs and track how much of
  each has been reconstructed, feeding that to a learner. That completion-ratio
  idea is the state signal this design wants, and nobody has ported it to twee.
- **Twitch's partial-proof abstractions** are one iteration of the refine step:
  fail, extract from the failed attempt, retry.
- **DSP (draft/sketch/prove)** is the ITP analogue: informal draft, formal
  sketch, ATP fills the gaps.

What appears to be unclaimed, from the searches recorded in this project: an
LLM drafting sketches that are **compiled into saturation-prover hints and
refined against the prover's returned state**. The honest framing of this work
is *automating Veroff*, not inventing a new paradigm.

## Two channels, not one

The v0 run plus its instrumentation and ablation (all in `FINDINGS.md`) showed
that "add hints" conflates two mechanisms with opposite requirements.

**Waypoints** are specific terms marking critical points in the intended proof.
On MVA005-1 the 13 waypoint hints alone proved the conjecture in 852.9s where the
baseline timed out. They fire rarely — 36 times, once, once.

**Accelerants** are small generic terms like `join(X, Y)` that match almost
everything. On MVA005-1 they fired 82M times, could **not** prove the problem on
their own, but took the waypoint-only run from 852.9s to 546.8s. They behave
like an ITP's `simp`/rewrite-hint database: a theory-level scoring policy, not
proof content.

Three consequences the current mechanism cannot express:

1. **Waypoints get the smallest discount.** twee's hint cost grows with function
   symbol count, so the load-bearing hints are the most expensive and the
   dispensable ones the cheapest. One `--hint-skel-factor` governs both channels,
   and no value is right for both.
2. **Nothing steers the search toward a waypoint.** `Index.matches` is a discount
   *on arrival*: it fires only once a critical pair already contains the matching
   subterm. There is no partial credit and no gradient — a sparse terminal reward
   with no shaping. This is why LCL054-10's 25 waypoints fired 18 times in 600s
   and never again: the search never entered their neighbourhood and nothing
   pulled it there.
3. **Accelerants are per-theory, not per-problem.** They should be a profile
   tuned once for a theory and reused, not re-derived from each donor proof.

### Supplying direction

**(a) Decomposition — no prover change, do this first.** Make each waypoint a
*goal* rather than a hint. Run the ladder rung by rung: prove waypoint 1 from
the axioms; add it; prove waypoint 2; ... finally the conjecture. Direction then
comes for free, because each run's actual goal *is* the waypoint, so goal
flattening and all of twee's goal-directedness point at it. This is exactly
Veroff's method, it needs no patch, it gives per-rung progress signal, and a
failed rung localises the error instead of poisoning one long run.

**Measured, and it fails as first implemented** (`FINDINGS.md`, MVA005-1): the
rungs prove, then the final goal times out because the 20 promoted lemmas are
added as *axioms*, and axioms form critical pairs with every existing rule. The
localisation benefit is real — exactly one rung fails, naming the step to
subdivide — but it must be bought without the axiom blowup. Promote proven rungs
as hints, not axioms; the "strictly stronger" reasoning below is sound logically
and wrong operationally.

It also fixes a structural mistake in v0: flattening an ordered ladder into an
unordered bag of 25 hints discards the sketch's most useful content, its order.

**A ladder is still too flat: the sketch is a DAG** (`FINDINGS.md`, "Context
scope"). An order says what comes before what; it does not say which earlier
rungs a given rung actually *needs*, and that turns out to be the decisive
quantity. `alt12_additive` follows in four rewrite steps from five lemmas that
had all verified; proved standalone it timed out at 300s and needed 592.5s at a
larger budget, and given exactly those five parents as axioms it proves in 0.2s.
Supplying all thirteen verified lemmas is no better, so the right scope is the
*direct parents*, not the ancestor closure.

That also settles which channel to use, and the answer is not global:

| the supporting set is… | channel | evidence |
|---|---|---|
| this goal's direct parents, a handful | **axioms** | `alt12_additive` 592.5s → 0.2s; never proved from any hint configuration |
| a large approximate bag | **hints** | MVA005-1: 20 as axioms timed out, the same as hints proved in 173.6s |

So the channel follows from whether the lemmas are known to be this goal's
parents — a property of the sketch's *structure*, not its size. `agent/dag.py`
implements this: `Sketch` carries the edges, `scope()` reads them, and
`channel_for()` picks the channel from them. A sketch with no edges recorded
(what the donor path produces) degrades exactly to the standalone ladder, which
is the correct treatment for donor rungs — those came from a real proof and are
reachable from the axioms by construction, which is precisely what a drafted rung
is not.

TPTP supplies an independent instance: RNG025-4 and RNG025-5 share a conjecture
and an axiom include, and RNG025-5 adds seven true, relevant sign lemmas as
axioms. Same screen, build, budget, direction — 371.9s becomes a timeout, and
still times out at 4000s.

**(b) Graded proximity — needs a twee change, later.** Replace binary matching
with partial credit proportional to how much of a waypoint's structure is
present, i.e. a potential function over distance-to-waypoint. We now have the
instrumented build and know the exact site (`CP.score`), so this is feasible, but
it is research rather than plumbing and should wait for (a) to be exhausted.

### Cap policy

`overtone/agent/hints.py:build_hints` ranks by occurrence count in the donor proof, which favours
accelerants. On MVA005-1 the cap of 25 happened to admit 13 waypoints alongside
12 accelerants, so the structural content survived by luck — **a tighter cap
would have kept only accelerants and lost the problem.** Rank for specificity so
waypoints clear the cap first, then top up from the theory's accelerant profile.

## Architecture

The proposer's job is therefore not "produce 25 hints" but **produce and repair
an ordered ladder**, with accelerants supplied separately as a per-theory
profile. The executor runs rungs, not one flat job.

```
          ┌──────────────────────────────────────────────┐
          │ SKETCH LIBRARY (retrieval corpus)            │
          │ Veroff 168 hint files, McCune ROB rungs,      │
          │ screen proofs, TSTP easy-band derivations     │
          └───────────────────┬──────────────────────────┘
                              ▼
 problem ─► PROPOSER   analogy-map to a known sketch; draft a lemma
                       ladder; select 9-33 hints for this run
                              ▼
            BRIDGE     variabilise donor-only symbols; enumerate AC
                       associations; verify symbols occur in the target
                              ▼
            EXECUTOR   both goal directions x hint variants, factor 0.5,
                       paired no-hint baseline
                              ▼
            CRITIC     parse output: proven lemmas, fired vs inert hints,
                       peaks, saturation status
                              ▼
            REFINER    promote proven lemmas to hints; drop inert ones;
                       weaken or descend the ladder ──────────► loop
```

**The prover is a sound verifier, so the proposer is allowed to be wrong.**
Every proposal is checked; every accepted lemma is a theorem. A bad sketch
wastes CPU and cannot corrupt a result. This is what makes an unreliable
generator acceptable here and is the central design property.

### Components

**Proposer.** Retrieval over the sketch library plus a frozen LLM. Two modes:
*retrieve* (find the structurally closest sketch and analogy-map it) and *draft*
(generate weakened conjectures from scratch, Veroff-style). Draft mode is the
genuinely novel bet and is needed where we hold no matching sketch — notably GRP,
with 22 resisted problems and thin sketch material.

**Bridge.** Turns sketch terms into `$hint` clauses. Not glamorous and the
highest-risk component: FINDINGS records that hints whose symbols are absent from
the problem are **inert rather than harmful** (821ms vs 844ms baseline, versus
252ms for a useful hint), so a perfect sketch can silently become a no-op. It
must variabilise donor-only constants, drop terms using absent non-nullary
symbols, and enumerate AC associations (open question in FINDINGS: EQP hints are
AC-flattened and the translator picks one association).

**Executor.** Reuses `scripts/screen.py` infrastructure. Enforces the FINDINGS
guardrails as code, not advice: `--hint-skel-factor 0.5` (factor 0 is
pathological, measured four ways), 9-33 hints, both goal directions, paired
baseline in the same batch.

**Critic.** twee's failure state is rich and we already parse most of it:
`--all-lemmas` prints proofs of every lemma found before timeout, `--show-peaks`
marks frontier terms, `--print-score` gives every derived rule a score. A failed
1000s run is a corpus, not a bit.

**Refiner.** Proven lemmas become hints or axioms for the next iteration; inert
hints are dropped; unreached ladder rungs get weakened. This is Veroff's
assumption-elimination loop.

## Instrument hint firing first

Everything downstream depends on distinguishing *bad sketch* from *sketch never
reached the search*. Because inert hints are silent, the loop cannot be debugged
without measuring how many hints actually matched a critical pair.

This is also where the Twitch authors report their mechanism is weakest. §7:
the implementation "is currently quite brittle" because twee demodulates
critical pairs, so a term matching an abstraction can be rewritten into one that
does not — their example is abstraction `f(x,x)` with associativity turning
`f(f(x,x),y)` into `f(x,f(x,y))`. That is twee's own author saying the hint
channel leaks. **Every hint result in this project, ours and theirs, is
therefore a lower bound.** Quantifying the leak is a prerequisite, and if it is
large, fixing the mechanism may beat improving selection.

## SFT or agentic?

Agentic, with SFT as the harvest rather than the seed.

Labelled (problem → winning hint set) pairs we actually hold: 19 from Twitch's
`hard_successes`, ~168 Veroff input files, 3 McCune ROB rungs — order a few
hundred, from roughly six theory families. The 2.38M Veroff hints are pool
items, not labelled selections. And by the coverage measurement above, labelled
pairs are absent exactly at the frontier.

That is far too little for supervised fine-tuning, and training on it would
memorise theory families — the same leakage failure flagged for the train/eval
split, baked into weights instead. So:

- **Now**: frozen model, retrieval over the sketch library, prover as verifier.
  DSP itself worked few-shot without fine-tuning.
- **Later**: every successful trajectory (sketch, refinements, final hint set,
  proof) is a minted training example. Expert iteration on trajectories becomes
  viable once the loop has produced enough successes. The loop is how you create
  the dataset you would need.

## Evaluation protocol

Pre-registered, because expected yield is a handful of flips and post-hoc target
selection makes the result unfalsifiable.

- **Targets** are fixed in `examples/sketch_loop/` before any hinted run.
- **Baseline** is the recorded screen result for the same problem, both goal
  directions, at the same or larger budget. Never compare against a single
  direction.
- **A flip counts** only if the paired baseline fails at equal budget. Given 21
  problems have already flipped on budget and direction alone (FINDINGS), CPU is
  the alternative hypothesis to beat, not a formality.
- **Negative control**: the 260 SAT UEQ problems, 520 jobs, 0 false proofs. Any
  hinted configuration must preserve that.
- **Report inert-hint counts** with every result, so a null result can be
  attributed to content or to plumbing.

## Status

This document is the **design** and is kept for its analysis of the hint channel,
which still holds: waypoints and accelerants do different jobs, twee's hint cost
is inverted with respect to informativeness, and nothing steers the search
*toward* a waypoint. What changed is the conclusion drawn from it.

The hint channel is no longer the mechanism. A sketch is a DAG whose nodes are
verified with their **direct parents supplied as axioms** — worth ~3000x over
standalone verification, where the same lemmas as hints were worth nothing and
234 mined lemmas in the hint channel flipped no target at all. See
`docs/SKETCHES.md` for every sketch attempted and `docs/FINDINGS.md` for the
measurements.

Current implementation:

- `agent/dag.py` — the DAG, topological verification, the final attempt.
- `agent/pipeline.py` — per-problem and per-theory runs, separately accounted.
- `agent/loop.py` — draft → verify → diagnose → revise, with a scripted agent.
- `agent/llm.py` — Anthropic and OpenAI behind one action schema.
- `agent/sketch.py` — v0 donor-chain hints, retained for the ablation whose
  result this document analyses, and for the tracked bundles in
  `examples/sketch_loop/` (disjoint from `data/lists/twitch19.txt`).

**Judging an edit needs a measurement, and the obvious one is wrong.** Rules
derived, and the two sides of a goal counted separately, all rose across an
RNG033-8 refinement that made the problem harder. `proofs.goal_contact` counts
rules touching **both** sides — the only ones that can close a goal — and it fell
from 162 to 102 across the same edit. It is on `State.contact` and in the model's
prompt, because an agent that cannot tell a good edit from a bad one will loop.

**Having the measurement is not the same as taking it.** For a whole agent run on
RNG029-5 `State.contact` was `None` at every iteration: it was read by globbing
the *goal node's* artifacts, and the goal node was blocked, so nothing was there
to glob — while the target attempt in the same iteration left a failed search
that scores perfectly well. Contact now comes from that attempt's own result row,
as `State.target`, with the previous iteration's value beside it so the model
reads a delta rather than a level. A fall reverts the edit; a rise still endorses
nothing. See FINDINGS for what else that audit turned up — the attempt was 58%
and 83% of those two runs' prover budgets, spent on the loose-bag-as-axioms
configuration this document argues against.

Getting there required discarding the method it replaces: counting term shapes in
twee's output. `--flatten-goal` names every goal subterm and rewrites matching
terms to the name, so the shape is not there to find, and one RNG033-8 iteration
plus a `--precedence` experiment were both drafted against that artefact.

The drafting half is still unproven: everything measured so far was drafted by a
human or mined from a donor proof. `docs/PLAN.md` sets the direction.
