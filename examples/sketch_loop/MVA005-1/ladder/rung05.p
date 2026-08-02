include('Axioms/MVA001-0.ax').
cnf(rung_1, axiom,
    ( join(X, meet(X, Y)) = X )).
cnf(rung_2, axiom,
    ( join(X, ld(unit, X)) = ld(unit, X) )).
cnf(rung_3, axiom,
    ( op(X, op(ld(X, unit), ld(ld(Y, unit), unit))) = at(X, Y) )).
cnf(rung_4, axiom,
    ( op(X, ld(X, unit)) = at(X, unit) )).
cnf(rung_goal, negated_conjecture,
    ( join(sk_rung_1, rd(sk_rung_1, unit)) != rd(sk_rung_1, unit) )).
