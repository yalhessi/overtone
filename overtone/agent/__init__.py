"""Sketch-loop work: donor selection, hint extraction, ladder execution.

ISOLATED ON PURPOSE. This is the exploratory half of the project
(docs/SKETCH_LOOP.md) and may be abandoned; the core must not depend on it.

Deletion contract
-----------------
Removing this package requires deleting `scripts/sketch_transfer.py` and
`scripts/ladder.py`, and nothing else. No module under `overtone/` outside this
directory may import from it, and importing `overtone` must not import
`overtone.agent`. Enforced by:

    grep -rnE "^(from|import) overtone\.agent|from overtone import .*agent" \
         overtone/*.py                    # must be empty

The boundary is about churn, not value: the v0 pipeline here has no LLM in it
and produced the project's clearest positive result so far -- the MVA005-1
axiom-vs-hint comparison in docs/FINDINGS.md.
"""
