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
cnf(rung_6, axiom,
    ( meet(X, join(X, Y)) = X )).
cnf(rung_7, axiom,
    ( meet(rd(unit, X), ld(X, unit)) = ld(X, unit) )).
cnf(rung_8, axiom,
    ( ld(ld(X, unit), unit) = at(unit, X) )).
cnf(rung_9, axiom,
    ( join(X, op(X, join(Y, unit))) = op(X, join(Y, unit)) )).
cnf(rung_10, axiom,
    ( join(X, op(X, Y)) = op(X, join(Y, unit)) )).
cnf(rung_11, axiom,
    ( op(X, op(ld(X, unit), Y)) = op(at(X, unit), Y) )).
cnf(rung_12, axiom,
    ( rd(X, ld(op(X, join(Y, unit)), X)) = op(X, join(Y, unit)) )).
cnf(rung_13, axiom,
    ( rd(X, rd(unit, join(Y, unit))) = op(X, join(Y, unit)) )).
cnf(rung_14, axiom,
    ( ld(rd(X, op(join(Y, unit), X)), X) = op(join(Y, unit), X) )).
cnf(rung_15, axiom,
    ( ld(rd(unit, join(X, unit)), Y) = op(join(X, unit), Y) )).
cnf(rung_16, axiom,
    ( meet(rd(ld(X, Y), Z), ld(X, rd(Y, Z))) = ld(X, rd(Y, Z)) )).
cnf(rung_17, axiom,
    ( op(X, op(rd(unit, X), Y)) = op(at(X, unit), Y) )).
cnf(goal, negated_conjecture,
    ( join(sk_rung_1, op(join(sk_rung_2, unit), sk_rung_1)) != op(join(sk_rung_2, unit), sk_rung_1) )).
