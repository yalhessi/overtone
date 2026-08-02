# Sketch: GRP673-10

Target `GRP673-10` resisted the baseline screen in both goal
directions. The sketch is the proof of its most axiom-similar solved
sibling; hints are the intermediate terms of that proof's rewrite
chains (Twitch's extraction), adapted to the target signature.

- donor: `GRP664-10` (axiom similarity **0.817**)
- donor proof: `logs/screen/proofs/GRP664-10_no-flatten-goal.out`
- extracted 1123 term occurrences (1020 distinct)
- dropped 5 (absent non-nullary symbols, unparseable, or contentless)
- kept 25 (cap 25; donor-only constants variabilised to Wn)
- baseline: {"1000s --flatten-goal": "Timeout", "1000s --no-flatten-goal": "Timeout"}

| # | hint (adapted) | donor occurrences | donor term |
|---|---|---|---|
| 1 | `rd(mult(X, Y), X)` | 5 |  |
| 2 | `mult(W1, W2)` | 4 | `mult(x1, x0)` |
| 3 | `mult(ld(W1, X), W2)` | 3 | `mult(ld(x0, X), x1)` |
| 4 | `mult(X, mult(ld(X, Y), ld(Y, mult(unit, X))))` | 3 |  |
| 5 | `mult(rd(unit, rd(Y, X)), Y)` | 3 |  |
| 6 | `ld(W1, rd(X, W2))` | 3 | `ld(x1, rd(X, x0))` |
| 7 | `mult(ld(ld(X, Y), Y), ld(Y, ld(X, Y)))` | 3 |  |
| 8 | `ld(ld(X, Y), mult(rd(unit, X), Y))` | 3 |  |
| 9 | `rd(rd(X, W1), X)` | 3 | `rd(rd(X, x0), X)` |
| 10 | `mult(rd(X, ld(Y, Z)), rd(Z, Y))` | 3 |  |
| 11 | `rd(mult(X, ld(ld(Y, Z), Z)), Y)` | 3 |  |
| 12 | `mult(rd(X, ld(Y, mult(Z, Y))), Z)` | 3 |  |
| 13 | `mult(rd(X, Y), ld(Z, mult(Y, Z)))` | 3 |  |
| 14 | `mult(mult(X, rd(Y, ld(X, Z))), Z)` | 3 |  |
| 15 | `mult(mult(X, Y), ld(Z, mult(X, Z)))` | 3 |  |
| 16 | `mult(rd(X, ld(W1, Y)), W2)` | 3 | `mult(rd(X, ld(x0, Y)), x1)` |
| 17 | `mult(mult(X, W1), ld(W1, unit))` | 2 | `mult(mult(X, x1), ld(x1, unit))` |
| 18 | `mult(mult(X, W1), W2)` | 2 | `mult(mult(X, x0), x1)` |
| 19 | `mult(Y, ld(X, unit))` | 2 |  |
| 20 | `mult(W1, mult(X, W1))` | 2 | `mult(x1, mult(X, x1))` |
| 21 | `ld(W1, rd(X, W1))` | 2 | `ld(x0, rd(X, x0))` |
| 22 | `rd(ld(W1, X), W1)` | 2 | `rd(ld(x1, X), x1)` |
| 23 | `mult(W1, mult(W2, X))` | 2 | `mult(x0, mult(x1, X))` |
| 24 | `rd(rd(X, W1), W2)` | 2 | `rd(rd(X, x1), x0)` |
| 25 | `rd(X, W1)` | 2 | `rd(X, x1)` |
