# Sketch: COL003-1

Target `COL003-1` resisted the baseline screen in both goal
directions. The sketch is the proof of its most axiom-similar solved
sibling; hints are the intermediate terms of that proof's rewrite
chains (Twitch's extraction), adapted to the target signature.

- donor: `COL066-1` (axiom similarity **0.897**)
- donor proof: `logs/screen/proofs/COL066-1_flatten-goal.out`
- extracted 48 term occurrences (43 distinct)
- dropped 1 (absent non-nullary symbols, unparseable, or contentless)
- kept 25 (cap 25; donor-only constants variabilised to Wn)
- baseline: {"1000s --flatten-goal": "Timeout", "1000s --no-flatten-goal": "Timeout", "4000s --flatten-goal": "Timeout", "4000s --no-flatten-goal": "Timeout"}

| # | hint (adapted) | donor occurrences | donor term |
|---|---|---|---|
| 1 | `apply(X, apply(X, Y))` | 3 |  |
| 2 | `apply(apply(apply(w, b), X), Y)` | 2 |  |
| 3 | `apply(apply(apply(w, W1), X), Y)` | 2 | `apply(apply(apply(w, q), X), Y)` |
| 4 | `apply(apply(w, apply(b, X)), Y)` | 1 |  |
| 5 | `apply(apply(apply(b, X), Y), Y)` | 1 |  |
| 6 | `apply(X, apply(Y, Y))` | 1 |  |
| 7 | `apply(apply(w, apply(W1, Y)), X)` | 1 | `apply(apply(w, apply(q, Y)), X)` |
| 8 | `apply(apply(apply(W1, Y), X), X)` | 1 | `apply(apply(apply(q, Y), X), X)` |
| 9 | `apply(X, apply(Y, X))` | 1 |  |
| 10 | `apply(apply(apply(b, X), X), Y)` | 1 |  |
| 11 | `apply(apply(apply(W1, X), X), Y)` | 1 | `apply(apply(apply(q, X), X), Y)` |
| 12 | `apply(apply(w, apply(apply(W1, X), Y)), Z)` | 1 | `apply(apply(w, apply(apply(q, X), Y)), Z)` |
| 13 | `apply(apply(apply(apply(W1, X), Y), Z), Z)` | 1 | `apply(apply(apply(apply(q, X), Y), Z), Z)` |
| 14 | `apply(apply(Y, apply(X, Z)), Z)` | 1 |  |
| 15 | `apply(apply(w, apply(b, X)), apply(apply(W1, Y), Z))` | 1 | `apply(apply(w, apply(b, X)), apply(apply(q, Y), Z))` |
| 16 | `apply(X, apply(apply(apply(W1, Y), Z), apply(apply(W1, Y), Z)))` | 1 | `apply(X, apply(apply(apply(q, Y), Z), apply(apply(q, Y), Z)))` |
| 17 | `apply(X, apply(Z, apply(Y, apply(apply(W1, Y), Z))))` | 1 | `apply(X, apply(Z, apply(Y, apply(apply(q, Y), Z))))` |
| 18 | `apply(apply(w, apply(apply(W1, X), apply(W1, Z))), Y)` | 1 | `apply(apply(w, apply(apply(q, X), apply(q, Z))), Y)` |
| 19 | `apply(apply(apply(W1, Z), apply(X, Y)), Y)` | 1 | `apply(apply(apply(q, Z), apply(X, Y)), Y)` |
| 20 | `apply(apply(X, Y), apply(Z, Y))` | 1 |  |
| 21 | `apply(apply(w, apply(apply(W1, X), apply(apply(W1, Y), Z))), W)` | 1 | `apply(apply(w, apply(apply(q, X), apply(apply(q, Y), Z))), W)` |
| 22 | `apply(apply(apply(apply(W1, Y), Z), apply(X, W)), W)` | 1 | `apply(apply(apply(apply(q, Y), Z), apply(X, W)), W)` |
| 23 | `apply(apply(Z, apply(Y, apply(X, W))), W)` | 1 |  |
| 24 | `apply(apply(w, apply(apply(W1, X), apply(W1, apply(apply(W1, Y), Z)))), W)` | 1 | `apply(apply(w, apply(apply(q, X), apply(q, apply(apply(q, Y), Z)))), W)` |
| 25 | `apply(apply(X, W), apply(apply(apply(W1, Y), Z), W))` | 1 | `apply(apply(X, W), apply(apply(apply(q, Y), Z), W))` |
