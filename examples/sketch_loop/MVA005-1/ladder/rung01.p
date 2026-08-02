include('Axioms/MVA001-0.ax').
cnf(rung_goal, negated_conjecture,
    ( join(sk_rung_1, meet(sk_rung_1, sk_rung_2)) != sk_rung_1 )).
