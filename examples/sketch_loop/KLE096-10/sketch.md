# Sketch: KLE096-10

Target `KLE096-10` resisted the baseline screen in both goal
directions. The sketch is the proof of its most axiom-similar solved
sibling; hints are the intermediate terms of that proof's rewrite
chains (Twitch's extraction), adapted to the target signature.

- donor: `KLE108-10` (axiom similarity **0.933**)
- donor proof: `logs/screen/proofs/KLE108-10_flatten-goal.out`
- extracted 6088 term occurrences (4682 distinct)
- dropped 3 (absent non-nullary symbols, unparseable, or contentless)
- kept 25 (cap 25; donor-only constants variabilised to Wn)
- baseline: {"1000s --flatten-goal": "Timeout", "1000s --no-flatten-goal": "Timeout", "4000s --flatten-goal": "Timeout", "4000s --no-flatten-goal": "Timeout"}

| # | hint (adapted) | donor occurrences | donor term |
|---|---|---|---|
| 1 | `domain(X)` | 40 |  |
| 2 | `c(X)` | 26 |  |
| 3 | `codomain(X)` | 23 |  |
| 4 | `c(domain(X))` | 19 |  |
| 5 | `coantidomain(X)` | 17 |  |
| 6 | `domain_difference(X, Y)` | 16 |  |
| 7 | `multiplication(X, Y)` | 15 |  |
| 8 | `forward_diamond(X, Y)` | 13 |  |
| 9 | `backward_diamond(X, Y)` | 13 |  |
| 10 | `multiplication(one, X)` | 10 |  |
| 11 | `domain(domain(X))` | 10 |  |
| 12 | `backward_box(X, zero)` | 10 |  |
| 13 | `multiplication(X, one)` | 10 |  |
| 14 | `forward_box(X, Y)` | 9 |  |
| 15 | `backward_box(X, Y)` | 9 |  |
| 16 | `domain(codomain(X))` | 9 |  |
| 17 | `backward_box(domain(X), zero)` | 9 |  |
| 18 | `domain_difference(domain(X), Y)` | 9 |  |
| 19 | `c(c(X))` | 8 |  |
| 20 | `c(codomain(X))` | 8 |  |
| 21 | `c(coantidomain(X))` | 8 |  |
| 22 | `forward_box(X, c(Y))` | 8 |  |
| 23 | `codomain(domain(X))` | 8 |  |
| 24 | `backward_box(one, X)` | 8 |  |
| 25 | `multiplication(c(X), Y)` | 8 |  |
