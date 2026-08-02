# Sketch: MVA005-1

Target `MVA005-1` resisted the baseline screen in both goal
directions. The sketch is the proof of its most axiom-similar solved
sibling; hints are the intermediate terms of that proof's rewrite
chains (Twitch's extraction), adapted to the target signature.

- donor: `MVA001-1` (axiom similarity **1.000**)
- donor proof: `logs/screen/proofs/MVA001-1_flatten-goal.out`
- extracted 1021 term occurrences (774 distinct)
- dropped 3 (absent non-nullary symbols, unparseable, or contentless)
- kept 25 (cap 25; donor-only constants variabilised to Wn)
- baseline: {"1000s --flatten-goal": "Timeout", "1000s --no-flatten-goal": "Timeout", "4000s --no-flatten-goal": "Unsatisfiable", "4000s --flatten-goal": "Unsatisfiable"}

| # | hint (adapted) | donor occurrences | donor term |
|---|---|---|---|
| 1 | `op(X, Y)` | 7 |  |
| 2 | `at(X, unit)` | 6 |  |
| 3 | `rd(unit, X)` | 6 |  |
| 4 | `join(X, unit)` | 6 |  |
| 5 | `join(X, meet(X, Y))` | 5 |  |
| 6 | `ld(X, Y)` | 5 |  |
| 7 | `join(X, Y)` | 5 |  |
| 8 | `at(X, Y)` | 4 |  |
| 9 | `ld(X, X)` | 4 |  |
| 10 | `rd(X, X)` | 4 |  |
| 11 | `op(X, join(Y, unit))` | 4 |  |
| 12 | `join(meet(X, Y), X)` | 3 |  |
| 13 | `join(X, ld(unit, X))` | 3 |  |
| 14 | `op(X, op(ld(X, unit), ld(ld(Y, unit), unit)))` | 3 |  |
| 15 | `op(X, ld(X, unit))` | 3 |  |
| 16 | `join(X, rd(X, unit))` | 3 |  |
| 17 | `meet(X, join(X, Y))` | 3 |  |
| 18 | `meet(X, Y)` | 3 |  |
| 19 | `meet(rd(unit, X), ld(X, unit))` | 3 |  |
| 20 | `ld(X, unit)` | 3 |  |
| 21 | `ld(ld(X, unit), unit)` | 3 |  |
| 22 | `at(unit, X)` | 3 |  |
| 23 | `op(at(X, unit), Y)` | 3 |  |
| 24 | `op(join(Y, unit), X)` | 3 |  |
| 25 | `meet(rd(ld(X, Y), Z), ld(X, rd(Y, Z)))` | 3 |  |
