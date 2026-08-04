"""Sketch-loop work: decomposition, verification, transfer, and rendering.

ISOLATED FROM CORE. Nothing under `overtone/` outside this directory imports it,
and importing `overtone` must not import `overtone.agent`. Enforced by:

    grep -rnE "^(from|import) overtone\.agent" overtone/*.py     # must be empty

The boundary is about churn, not value -- this is where the experiments live and
where they change fastest. It is no longer plausibly deletable: `dag.py` and
`pipeline.py` carry the results in docs/FINDINGS.md.

    dag.py        A sketch as a DAG. `Sketch`, topological `verify` with parents
                  supplied as axioms, `attempt` for the final run against the
                  real problem, `cost`, `diff`, `sibling_diff`, and
                  `sketch_from_proof` for reading a donor's proof as a DAG.
    pipeline.py   `run_problem` (one problem, one honest cost, nothing shared)
                  and `run_theory` (a library once, a marginal cost per target,
                  containment asserted). The two answer different questions and
                  their numbers are never added.
    blueprint.py  Rendering: SVG, DOT, and an interactive page with a trajectory
                  scrubber. Consumes `verify()["results"]` directly.
    donors.py     Choosing a solved sibling to transfer from. Ranks by axiom
                  similarity, which is measurably the wrong criterion -- what
                  decided the RNG result was the donor's *goal* being a lemma the
                  target needed, and nothing here measures that yet.
    hints.py      The `$hint` channel: extraction, adaptation, cap policy. Kept
                  because `HINT_FLAGS` and the specific/generic split are still
                  cited, not because hints beat axioms -- they do not, at any
                  quantity we have tried.
    sketch.py     v0 donor-chain transfer. Retained for `ablate`, whose
                  specific-vs-generic result is in FINDINGS, and `make_example`,
                  which regenerates the tracked bundles under `examples/`.

Consumers: `scripts/{prove,theory,blueprint,transfer_dag,sketch_transfer}.py`.
"""
