# Plan: drafting first, donors when they are strong

Where the sketch line stands after the RNG work, and what to do next. Results are
in [FINDINGS.md](FINDINGS.md); the sketches themselves are in
[SKETCHES.md](SKETCHES.md) and `docs/img/rng_dag.svg`.

## What is settled

**A decomposition works, and it is small.** Six lemmas over the alternative-ring
axioms flip ten TPTP problems whose baseline timed out at 4000s in both goal
directions, seven of them rated 0.91-0.96, and take two others from ~3600s and
~3800s to 0.0s. The six: cyclicity of the associator, two rearrangements of its
definition, the flexible law, right Moufang, left Moufang.

**Scope and channel matter more than content.** Direct parents as axioms are
worth ~3000x over standalone verification; the same lemmas as hints are worth
nothing, and 234 lemmas in the hint channel flip nothing at all. Wrong parents
are worse than none -- `teichmuller` goes 3.3s -> 358.6s -> timeout as three
irrelevant lemmas are added.

**Budget is a diagnostic.** Every node in a correct decomposition verifies in
seconds. A node needing minutes means the sketch is wrong there, and the fix is
to revise it, not to raise the budget. Three of the four faults found this way
were mis-drafted edges, not hard lemmas.

**Chain length is an artifact of the starting point.** The donor's proof of right
Moufang is 234 lemmas deep; four of them do the work. Reading a prover's search
order as the structure of the proof is what made this look intractable.

## What is not

**Cross-theory transfer fails.** GRP, LAT and COL all time out, in three
distinguishable ways: the donor's goal is irrelevant (GRP), the donor is too easy
to carry useful content (LAT, whose proof is 20 lemmas long), or the similarity
metric overstates the shared theory (COL, where 2 of 13 lemmas hold). The
verification machinery worked in every case -- only selection failed.

**Donor selection optimises the wrong quantity.** RNG succeeded because the
donor's *goal* was itself the lemma every target needed. `find_donor` ranks by
axiom similarity, which does not detect that, and cannot: two problems can share
every axiom and prove unrelated things.

## The approach

**Draft from informal sources; use donors only when they are strong.**

The donor was never the source of the mathematics here. It told us *which* three
intermediates mattered, and all three then proved from the drafted sketch in
under a second. Meanwhile the drafted library reached alternating, trilinear and
Teichmüller unaided, and the classical route -- associator alternating, hence
flexible, hence Moufang -- is textbook material available from any account of
alternative rings. What the drafting missed was not the mathematics but the
*shape*: it stated Moufang as a rung when Moufang was the goal, and it omitted
the definitional rearrangements a rewriting prover needs.

So the loop is: draft the mathematical route from informal sources, verify it
node by node at a diagnostic budget, and let the failures say where to subdivide.
Consult a donor when one is strong, and ignore it otherwise.

**A donor is strong when all three hold**, which is testable before any proving:

| test | RNG (worked) | GRP / LAT / COL (failed) |
|---|---|---|
| target axioms ⊇ donor axioms | identical | overlapping only |
| donor's proof is deep | 234 lemmas, depth 34 | 278/23, 20/7, 13/4 |
| donor's goal is a lemma the target plausibly needs | right Moufang, needed by all 12 | unrelated |

The third is the one that decides it and the one nothing currently measures.

## Next

### 1. Finish RNG — cheap, and the containment check is mandatory

- **RNG027-10, RNG029-10** (rating 1.00). Both proved and both withdrawn: their
  [Sma18] encodings *lack* 3 and 4 of RNG029-5's axioms, so lemmas from the
  stronger theory are not theorems of theirs. Redo properly -- re-verify the six
  lemmas against each problem's own axioms first, drop whatever fails, attempt
  with the survivors. If the lemmas do not hold, draft the missing ones for that
  encoding.
- **Assert `donor_axioms <= target_axioms`** in every transfer path.
  `transfer_dag.py` re-verifies and is safe; the fixed-library path is not, and
  that is exactly how two invalid results were produced.
- **`right_moufang` at 193.6s** trips the diagnostic threshold, so a node is
  missing beneath it. Candidates from its own failed search are in
  `logs/decompose/candidates.json`, but ranking them by twee's score surfaces
  plumbing the sketch already has; rank by structural overlap with the goal.
- **RNG019-021, RNG023-026** are now proved as nodes and are TPTP problems in
  their own right. Confirm each as a real problem file, then report them.

### 2. Draft a second theory from scratch

The RNG result is one theory. Repeat the *drafting* process somewhere with no
usable donor, which is the honest test of the approach and the case the corpus
mostly presents: TSTP donor coverage is 5.8% at rating >= 0.9.

Pick a domain where the informal mathematics is well documented and the resisted
set is large -- GRP has 22 resisted problems, and lattice theory has an
extensive classical literature. Draft the route, verify at 60s a node, subdivide
what fails. Expect the first draft to be wrong in the way the RNG one was: right
mathematics, wrong shape.

### 3. Fix donor selection, but treat it as secondary

Rank candidate donors by whether their *goal* is plausibly a lemma the target
needs -- symbol and shape overlap between the donor's conjecture and the target's
-- not by axiom similarity. Test on the case already in hand: for GRP673-10 we
hold 177 verified theorems of its own theory and selected the 8 worst by depth.
Re-ranking those by overlap with the target's goal costs no proving.

If that fails too, the conclusion is that donor transfer works only when a
sibling has already proved the lemma you need, which is a narrow and largely
uninteresting condition -- and drafting is the whole game.

### 4. Not yet

The eight `Status: Unknown` RNG problems. The plain baseline does not touch them
(0 of 8 at 4000s), and drafting for them should wait until the drafting process
has been shown to work twice on problems where the answer is known.
