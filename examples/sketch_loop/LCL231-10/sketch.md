# Sketch: LCL231-10

Target `LCL231-10` resisted the baseline screen in both goal
directions. The sketch is the proof of its most axiom-similar solved
sibling; hints are the intermediate terms of that proof's rewrite
chains (Twitch's extraction), adapted to the target signature.

- donor: `LCL192-10` (axiom similarity **1.000**)
- donor proof: `logs/screen/proofs/LCL192-10_flatten-goal.out`
- extracted 143 term occurrences (108 distinct)
- dropped 1 (absent non-nullary symbols, unparseable, or contentless)
- kept 25 (cap 25; donor-only constants variabilised to Wn)
- baseline: {"1000s --flatten-goal": "Timeout", "1000s --no-flatten-goal": "Timeout"}

| # | hint (adapted) | donor occurrences | donor term |
|---|---|---|---|
| 1 | `axiom(implies(X, implies(Y, X)))` | 1 |  |
| 2 | `axiom(implies(X, or(not(Y), X)))` | 1 |  |
| 3 | `axiom(implies(implies(X, Y), implies(implies(Z, X), implies(Z, Y))))` | 1 |  |
| 4 | `axiom(implies(implies(X, Y), implies(implies(Z, X), or(not(Z), Y))))` | 1 |  |
| 5 | `axiom(implies(implies(X, Y), implies(or(not(Z), X), or(not(Z), Y))))` | 1 |  |
| 6 | `theorem(implies(implies(X, Y), implies(implies(Z, X), implies(Z, Y))))` | 1 |  |
| 7 | `ifeq(true, true, theorem(implies(implies(X, Y), implies(implies(Z, X), implies(Z, Y)))), true)` | 1 |  |
| 8 | `ifeq(axiom(implies(implies(X, Y), implies(implies(Z, X), implies(Z, Y)))), true, theorem(implies(implies(X, Y), implies(implies(Z, X), implies(Z, Y)))), true)` | 1 |  |
| 9 | `theorem(implies(or(X, Y), or(Y, X)))` | 1 |  |
| 10 | `ifeq(true, true, theorem(implies(or(X, Y), or(Y, X))), true)` | 1 |  |
| 11 | `ifeq(axiom(implies(or(X, Y), or(Y, X))), true, theorem(implies(or(X, Y), or(Y, X))), true)` | 1 |  |
| 12 | `ifeq(theorem(implies(implies(or(X, Y), or(Y, X)), Z)), true, theorem(Z), true)` | 1 |  |
| 13 | `ifeq(theorem(implies(implies(or(X, Y), or(Y, X)), Z)), true, ifeq(true, true, theorem(Z), true), true)` | 1 |  |
| 14 | `ifeq(theorem(implies(implies(or(X, Y), or(Y, X)), Z)), true, ifeq(theorem(implies(or(X, Y), or(Y, X))), true, theorem(Z), true), true)` | 1 |  |
| 15 | `theorem(implies(implies(X, or(Y, Z)), implies(X, or(Z, Y))))` | 1 |  |
| 16 | `ifeq(true, true, theorem(implies(implies(X, or(Y, Z)), implies(X, or(Z, Y)))), true)` | 1 |  |
| 17 | `ifeq(theorem(implies(implies(or(Y, Z), or(Z, Y)), implies(implies(X, or(Y, Z)), implies(X, or(Z, Y))))), true, theorem(implies(implies(X, or(Y, Z)), implies(X, or(Z, Y)))), true)` | 1 |  |
| 18 | `theorem(implies(X, or(Y, X)))` | 1 |  |
| 19 | `ifeq(true, true, theorem(implies(X, or(Y, X))), true)` | 1 |  |
| 20 | `ifeq(axiom(implies(X, or(Y, X))), true, theorem(implies(X, or(Y, X))), true)` | 1 |  |
| 21 | `ifeq(theorem(implies(implies(X, or(Y, X)), Z)), true, theorem(Z), true)` | 1 |  |
| 22 | `ifeq(theorem(implies(implies(X, or(Y, X)), Z)), true, ifeq(true, true, theorem(Z), true), true)` | 1 |  |
| 23 | `ifeq(theorem(implies(implies(X, or(Y, X)), Z)), true, ifeq(theorem(implies(X, or(Y, X))), true, theorem(Z), true), true)` | 1 |  |
| 24 | `theorem(implies(X, or(X, Y)))` | 1 |  |
| 25 | `ifeq(true, true, theorem(implies(X, or(X, Y))), true)` | 1 |  |
