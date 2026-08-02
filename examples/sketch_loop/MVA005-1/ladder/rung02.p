include('Axioms/MVA001-0.ax').
cnf(rung_1, axiom,
    ( join(X, meet(X, Y)) = X )).
cnf(rung_goal, negated_conjecture,
    ( join(sk_rung_1, ld(unit, sk_rung_1)) != ld(unit, sk_rung_1) )).
