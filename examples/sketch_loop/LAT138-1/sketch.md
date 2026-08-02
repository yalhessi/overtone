# Sketch: LAT138-1

Target `LAT138-1` resisted the baseline screen in both goal
directions. The sketch is the proof of its most axiom-similar solved
sibling; hints are the intermediate terms of that proof's rewrite
chains (Twitch's extraction), adapted to the target signature.

- donor: `LAT139-1` (axiom similarity **0.930**)
- donor proof: `logs/screen/proofs/LAT139-1_no-flatten-goal.out`
- extracted 97 term occurrences (84 distinct)
- dropped 1 (absent non-nullary symbols, unparseable, or contentless)
- kept 25 (cap 25; donor-only constants variabilised to Wn)
- baseline: {"1000s --flatten-goal": "Timeout", "1000s --no-flatten-goal": "Timeout"}

| # | hint (adapted) | donor occurrences | donor term |
|---|---|---|---|
| 1 | `join(X, Y)` | 6 |  |
| 2 | `join(X, join(Y, Z))` | 2 |  |
| 3 | `meet(X, Y)` | 2 |  |
| 4 | `join(meet(X, Y), meet(X, join(Z, meet(Y, join(W, meet(X, Y))))))` | 2 |  |
| 5 | `meet(X, join(Z, meet(Y, join(W, meet(X, Y)))))` | 2 |  |
| 6 | `meet(X, join(Y, meet(X, Z)))` | 2 |  |
| 7 | `meet(Y, meet(X, Z))` | 1 |  |
| 8 | `meet(meet(X, Z), Y)` | 1 |  |
| 9 | `join(X, meet(Y, X))` | 1 |  |
| 10 | `join(X, meet(X, Y))` | 1 |  |
| 11 | `join(join(Y, Z), X)` | 1 |  |
| 12 | `meet(X, meet(Y, join(X, Z)))` | 1 |  |
| 13 | `meet(X, meet(join(X, Z), Y))` | 1 |  |
| 14 | `meet(meet(X, join(X, Z)), Y)` | 1 |  |
| 15 | `join(X, join(Y, meet(X, Z)))` | 1 |  |
| 16 | `join(X, join(meet(X, Z), Y))` | 1 |  |
| 17 | `join(join(X, meet(X, Z)), Y)` | 1 |  |
| 18 | `meet(X, meet(Y, join(Z, meet(X, Y))))` | 1 |  |
| 19 | `meet(X, meet(Y, join(Z, meet(Y, X))))` | 1 |  |
| 20 | `meet(X, meet(Y, join(meet(Y, X), Z)))` | 1 |  |
| 21 | `meet(Y, meet(X, join(meet(Y, X), Z)))` | 1 |  |
| 22 | `meet(meet(Y, X), join(meet(Y, X), Z))` | 1 |  |
| 23 | `join(X, join(Y, meet(Z, join(X, Y))))` | 1 |  |
| 24 | `join(X, join(Y, meet(Z, join(Y, X))))` | 1 |  |
| 25 | `join(X, join(Y, meet(join(Y, X), Z)))` | 1 |  |
