# Next iteration: two pipelines and an agentic runner

The RNG work was done as one undifferentiated activity -- draft a theory, verify
it, attack twelve problems at once -- and that conflation cost us two things
worth separating.

**Cost is unattributable.** Six lemmas took ~1122s to derive and then flipped ten
problems. Is that 112s per problem, or 1122s for the first and ~0s for the rest,
or 1122s each? All three are defensible and we never had to choose, because we
never solved one problem in isolation. No number in FINDINGS answers "how long
does this take on a problem".

**Encodings drift.** Sketch nodes were written from mathematical memory rather
than copied from the problem files. Twelve nodes match a TPTP conjecture exactly,
but `left_moufang` states `((xy)x)z = x(y(xz))` where RNG028-7 states
`(x(yx))z = x(y(xz))` -- equivalent given the flexible law, and *not the same
problem*. Two more match a conjecture whose axiom set differs from ours, which is
how RNG027-10 and RNG029-10 were briefly claimed and then withdrawn. twee is
sensitive enough to encoding that "equivalent" is not a safe word here.

Both follow from running one pipeline where two belong.

## Pipeline A -- per problem

**Input** one TPTP problem. **Output** a proof of *that file*, and a single
honest cost.

Rules, all mechanically checkable:

1. **The problem file is immutable.** The final attempt runs the original file
   with lemmas appended as axioms. No restating the conjecture, no substituting
   a sibling encoding.
2. **Every supplied lemma is verified against this problem's own axioms**, in
   this run, and its cost is charged to this run. A lemma that will not verify
   here does not get used here, whatever it proved elsewhere.
3. **Cost is everything spent**, including failed nodes, failed edges and
   abandoned drafts. One number, wall and CPU, no amortisation.
4. **No cross-problem state.** A fresh run cannot see another problem's library.
   This is what makes the number mean anything.

This is the pipeline that answers "can we solve X, and what did it cost", and it
is the one an evaluation should quote. Expect it to look far worse than the RNG
headline: RNG029-5 alone would carry the whole ~1122s sketch, not 1/10th of it.

## Pipeline B -- per theory

**Input** an axiom set plus a family of problems over it. **Output** a verified
lemma library and a per-problem marginal cost.

Here re-encoding is legitimate -- a library is *supposed* to state lemmas in the
form the prover likes -- and sharing is the point. Report two numbers, never one:

- **library cost**: deriving and verifying the DAG, once;
- **marginal cost**: the final attempt per problem, given the library.

And keep the containment check that the fixed-library path lacked: assert
`library_axioms ⊆ target_axioms` for every target, or re-verify the library
against that target before use. This is not optional -- it is the exact hole that
produced the two withdrawn results.

The RNG result is a Pipeline B result and is now labelled as one. Reproduced
through `scripts/theory.py`: **library 29/29 nodes at 2197.0s CPU over 58 runs;
marginal 0.1-313.1s per target; 12 of 12 eligible proved**, with RNG027-10 and
RNG029-10 rejected on containment before any proving.

One rule the first implementation lacked: **a library may not supply a target its
own conjecture.** This sketch contains nodes that *are* target conjectures --
`middle_moufang` is RNG029-5 -- and handing a problem its own statement proved
all twelve in 0.0s. Sound, and vacuous. Excluding the literal conjecture puts the
work back where it happened (RNG029-5: 0.0s -> 12.9s). Anything beyond the
literal conjecture stays supplied, because deriving one formulation from another
is exactly what a library is for.

### Which pipeline answers which question

| question | pipeline |
|---|---|
| can we solve this specific open problem, and at what cost | A |
| does a theory-level library pay for itself across a family | B |
| how much does the sketch loop cost per problem | A |
| is the drafting process finding the right mathematics | B |

## The agentic runner

This session ran the loop by hand: I drafted, the prover verified, I read the
failures and revised. That loop is regular enough to automate, and every piece
except the drafting and diagnosis is already built.

### State the agent sees

Derived from `agent/dag.py` and the run directory, not free text:

- the sketch: nodes, statements, edges, and per-node status and time;
- failures, classified: **slow** (proved above the diagnostic threshold),
  **blocked** (a parent failed), **failed with parents**, **failed standalone**;
- for a slow or failed node, candidate intermediates mined from its own run --
  derived rules for a failure, `proof_section` lemmas for a slow success;
- for a failed node, the parent-set diff against any structurally similar node
  that succeeded. This is the diagnostic that caught `left_moufang_a`, and it is
  not yet built.

### Actions

A closed set, each mechanically applied and verified:

    add_node(name, lhs, rhs, parents)
    remove_node(name)
    set_parents(name, parents)
    subdivide(name, [intermediate, ...])
    restate(name, lhs, rhs)
    attempt(target)

`restate` is the dangerous one and needs a guard: if a node is annotated with a
TPTP problem, its statement must be **copied from that problem file**, not
authored. That single rule would have prevented the `left_moufang` drift.

### Configuration

Following APE-Bench's shape -- a runner with the task, the model, the budget and
the verifier all declared rather than baked in:

    problem / theory        which pipeline, which target(s)
    model, temperature      the drafting and diagnosis agent
    node_budget             diagnostic threshold, default 60s
    slow_threshold          default 30s; above this a proved node is suspect
    final_budget            the attempt
    max_iterations          revision rounds before giving up
    total_cpu_budget        hard cap; the honest denominator for Pipeline A
    donor                   off | consult | require, with the strength test below
    actions                 which of the above the agent may use
    workers                 parallel node verification

### Donor policy

Default `consult`, and only when a donor is strong on all three tests, which are
checkable before any proving:

    target_axioms ⊇ donor_axioms
    donor proof is deep (a shallow proof carries nothing -- LAT139-1 was 20
        lemmas and 18 of them transferred uselessly)
    donor's goal is plausibly a lemma the target needs

The third is what actually decided RNG and what nothing currently measures.
`find_donor` ranks by axiom similarity and must be changed to score
goal-relatedness.

### Stopping

Terminate on: target proved; `max_iterations`; `total_cpu_budget`; or no action
available (every failure diagnosed and every proposed revision already tried).
Report the trajectory either way -- a failed run with its diagnoses is the
training data the loop exists to produce.

## Evaluation

Pre-register targets and the selection rule before running, as
`scripts/overnight_rng.py` did (removed at 8712094; its pre-registered target list is now `data/lists/rng_moufang.txt` and its job is `scripts/theory.py`). That discipline is why the RNG result reads
10/10 on a rule fixed in advance, while the four problems added afterwards
produced both withdrawn claims.

Report per pipeline:

- **A**: solved / attempted, with full cost per problem, against a paired no-hint
  baseline at equal CPU.
- **B**: library cost, marginal cost, family size, and the containment check.

Never mix them in one number.

## Build order

1. `sibling_diff` diagnostic in `agent/dag.py` -- small, and it caught one of
   the four faults this session.
2. Pipeline A as a script with hard cost accounting and no shared state. Re-run
   RNG029-5 through it to get the first honest per-problem number.
3. Pipeline B as a script, formalising what the RNG work did, with the
   containment assertion.
4. The runner: state, actions, config, trajectory logging -- with a scripted
   agent first, replaying this session's decisions, so the harness is tested
   before a model is attached.
5. Attach a model. Draft a second theory with no usable donor, which is the case
   the corpus mostly presents.
