include('Axioms/MVA001-0.ax').
cnf(rung_1, axiom,
    ( join(X, meet(X, Y)) = X )).
cnf(rung_2, axiom,
    ( join(X, ld(unit, X)) = ld(unit, X) )).
cnf(rung_goal, negated_conjecture,
    ( op(sk_rung_1, op(ld(sk_rung_1, unit), ld(ld(sk_rung_2, unit), unit))) != at(sk_rung_1, sk_rung_2) )).
