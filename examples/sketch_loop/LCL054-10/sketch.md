# Sketch: LCL054-10

Target `LCL054-10` resisted the baseline screen in both goal
directions. The sketch is the proof of its most axiom-similar solved
sibling; hints are the intermediate terms of that proof's rewrite
chains (Twitch's extraction), adapted to the target signature.

- donor: `LCL060-10` (axiom similarity **1.000**)
- donor proof: `logs/screen/proofs/LCL060-10_no-flatten-goal.out`
- extracted 286 term occurrences (215 distinct)
- dropped 1 (absent non-nullary symbols, unparseable, or contentless)
- kept 25 (cap 25; donor-only constants variabilised to Wn)
- baseline: {"1000s --flatten-goal": "Timeout", "1000s --no-flatten-goal": "Timeout", "4000s --flatten-goal": "Unsatisfiable", "4000s --no-flatten-goal": "Timeout"}

| # | hint (adapted) | donor occurrences | donor term |
|---|---|---|---|
| 1 | `ifeq(is_a_theorem(implies(implies(X, implies(not(X), Y)), Z)), true, is_a_theorem(Z), true)` | 1 |  |
| 2 | `ifeq(is_a_theorem(implies(implies(X, implies(not(X), Y)), Z)), true, ifeq(true, true, is_a_theorem(Z), true), true)` | 1 |  |
| 3 | `ifeq(is_a_theorem(implies(implies(X, implies(not(X), Y)), Z)), true, ifeq(is_a_theorem(implies(X, implies(not(X), Y))), true, is_a_theorem(Z), true), true)` | 1 |  |
| 4 | `is_a_theorem(implies(implies(implies(not(X), Y), Z), implies(X, Z)))` | 1 |  |
| 5 | `ifeq(true, true, is_a_theorem(implies(implies(implies(not(X), Y), Z), implies(X, Z))), true)` | 1 |  |
| 6 | `ifeq(is_a_theorem(implies(implies(X, implies(not(X), Y)), implies(implies(implies(not(X), Y), Z), implies(X, Z)))), true, is_a_theorem(implies(implies(implies(not(X), Y), Z), implies(X, Z))), true)` | 1 |  |
| 7 | `ifeq(is_a_theorem(implies(implies(implies(not(X), X), X), Y)), true, is_a_theorem(Y), true)` | 1 |  |
| 8 | `ifeq(is_a_theorem(implies(implies(implies(not(X), X), X), Y)), true, ifeq(true, true, is_a_theorem(Y), true), true)` | 1 |  |
| 9 | `ifeq(is_a_theorem(implies(implies(implies(not(X), X), X), Y)), true, ifeq(is_a_theorem(implies(implies(not(X), X), X)), true, is_a_theorem(Y), true), true)` | 1 |  |
| 10 | `is_a_theorem(implies(X, X))` | 1 |  |
| 11 | `ifeq(true, true, is_a_theorem(implies(X, X)), true)` | 1 |  |
| 12 | `ifeq(is_a_theorem(implies(implies(implies(not(X), X), X), implies(X, X))), true, is_a_theorem(implies(X, X)), true)` | 1 |  |
| 13 | `ifeq(is_a_theorem(X), true, is_a_theorem(implies(not(X), Y)), true)` | 1 |  |
| 14 | `ifeq(true, true, ifeq(is_a_theorem(X), true, is_a_theorem(implies(not(X), Y)), true), true)` | 1 |  |
| 15 | `ifeq(is_a_theorem(implies(X, implies(not(X), Y))), true, ifeq(is_a_theorem(X), true, is_a_theorem(implies(not(X), Y)), true), true)` | 1 |  |
| 16 | `is_a_theorem(implies(not(implies(X, X)), Y))` | 1 |  |
| 17 | `ifeq(true, true, is_a_theorem(implies(not(implies(X, X)), Y)), true)` | 1 |  |
| 18 | `ifeq(is_a_theorem(implies(X, X)), true, is_a_theorem(implies(not(implies(X, X)), Y)), true)` | 1 |  |
| 19 | `ifeq(is_a_theorem(implies(X, Y)), true, is_a_theorem(implies(implies(Y, Z), implies(X, Z))), true)` | 1 |  |
| 20 | `ifeq(true, true, ifeq(is_a_theorem(implies(X, Y)), true, is_a_theorem(implies(implies(Y, Z), implies(X, Z))), true), true)` | 1 |  |
| 21 | `ifeq(is_a_theorem(implies(implies(X, Y), implies(implies(Y, Z), implies(X, Z)))), true, ifeq(is_a_theorem(implies(X, Y)), true, is_a_theorem(implies(implies(Y, Z), implies(X, Z))), true), true)` | 1 |  |
| 22 | `is_a_theorem(implies(implies(X, Y), implies(not(implies(Z, Z)), Y)))` | 1 |  |
| 23 | `ifeq(true, true, is_a_theorem(implies(implies(X, Y), implies(not(implies(Z, Z)), Y))), true)` | 1 |  |
| 24 | `ifeq(is_a_theorem(implies(not(implies(Z, Z)), X)), true, is_a_theorem(implies(implies(X, Y), implies(not(implies(Z, Z)), Y))), true)` | 1 |  |
| 25 | `ifeq(is_a_theorem(implies(implies(not(X), Y), Z)), true, is_a_theorem(implies(X, Z)), true)` | 1 |  |
