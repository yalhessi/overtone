include('Axioms/MVA001-0.ax').
cnf(rung_1, axiom,
    ( join(X, meet(X, Y)) = X )).
cnf(rung_2, axiom,
    ( join(X, ld(unit, X)) = ld(unit, X) )).
cnf(rung_3, axiom,
    ( op(X, op(ld(X, unit), ld(ld(Y, unit), unit))) = at(X, Y) )).
cnf(rung_4, axiom,
    ( op(X, ld(X, unit)) = at(X, unit) )).
cnf(rung_5, axiom,
    ( join(X, rd(X, unit)) = rd(X, unit) )).
cnf(goal, negated_conjecture,
    ( meet(sk_rung_1, join(sk_rung_1, sk_rung_2)) != sk_rung_1 )).
