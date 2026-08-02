%--------------------------------------------------------------------------
% File     : COL003-1 : TPTP v9.2.1. Released v1.0.0.
% Domain   : Combinatory Logic
% Problem  : Strong fixed point for B and W
% Version  : [WM88] (equality) axioms.
% English  : The strong fixed point property holds for the set
%            P consisting of the combinators B and W alone, where ((Bx)y)z
%            = x(yz) and (Wx)y = (xy)y.

% Refs     : [Smu85] Smullyan (1978), To Mock a Mocking Bird and Other Logi
%          : [MW87]  McCune & Wos (1987), A Case Study in Automated Theorem
%          : [WM88]  Wos & McCune (1988), Challenge Problems Focusing on Eq
%          : [Wos88] Wos (1988), Automated Reasoning - 33 Basic Research Pr
%          : [Ove90] Overbeek (1990), ATP competition announced at CADE-10
%          : [LW92]  Lusk & Wos (1992), Benchmark Problems in Which Equalit
%          : [Wos93] Wos (1993), The Kernel Strategy and Its Use for the St
%          : [Ove93] Overbeek (1993), The CADE-11 Competitions: A Personal
%          : [LM93]  Lusk & McCune (1993), Uniform Strategies: The CADE-11
%          : [Zha93] Zhang (1993), Automated Proofs of Equality Problems in
% Source   : [WM88]
% Names    : C2 [WM88]
%          : Problem 2 [WM88]
%          : Test Problem 17 [Wos88]
%          : Sages and Combinatory Logic [Wos88]
%          : CADE-11 Competition Eq-8 [Ove90]
%          : CL2 [LW92]
%          : THEOREM EQ-8 [LM93]
%          : Question 3 [Wos93]
%          : Question 5 [Wos93]
%          : PROBLEM 8 [Zha93]

% Status   : Unsatisfiable
% Rating   : 0.74 v9.1.0, 0.68 v8.2.0, 0.62 v8.1.0, 0.65 v7.5.0, 0.75 v7.4.0, 0.74 v7.3.0, 0.79 v7.1.0, 0.72 v7.0.0, 0.74 v6.3.0, 0.71 v6.2.0, 0.57 v6.1.0, 0.75 v6.0.0, 0.86 v5.5.0, 0.84 v5.4.0, 0.80 v5.3.0, 0.75 v5.2.0, 0.79 v5.1.0, 0.80 v5.0.0, 0.79 v4.1.0, 0.64 v4.0.1, 0.71 v4.0.0, 0.69 v3.7.0, 0.67 v3.4.0, 0.75 v3.3.0, 0.71 v3.2.0, 0.79 v3.1.0, 0.78 v2.7.0, 0.73 v2.6.0, 0.67 v2.5.0, 0.25 v2.4.0, 0.33 v2.3.0, 0.67 v2.2.1, 1.00 v2.0.0
% Syntax   : Number of clauses     :    3 (   3 unt;   0 nHn;   1 RR)
%            Number of literals    :    3 (   3 equ;   1 neg)
%            Maximal clause size   :    1 (   1 avg)
%            Maximal term depth    :    4 (   2 avg)
%            Number of predicates  :    1 (   0 usr;   0 prp; 2-2 aty)
%            Number of functors    :    4 (   4 usr;   2 con; 0-2 aty)
%            Number of variables   :    6 (   0 sgn)
% SPC      : CNF_UNS_RFO_PEQ_UEQ

% Comments :
%--------------------------------------------------------------------------
cnf(b_definition,axiom,
    apply(apply(apply(b,X),Y),Z) = apply(X,apply(Y,Z)) ).

cnf(w_definition,axiom,
    apply(apply(w,X),Y) = apply(apply(X,Y),Y) ).

cnf(prove_strong_fixed_point,negated_conjecture,
    apply(Y,f(Y)) != apply(f(Y),apply(Y,f(Y))) ).

%--------------------------------------------------------------------------


cnf(hint_1, axiom,
	 $hint( apply(X, apply(X, Y)) )).

cnf(hint_2, axiom,
	 $hint( apply(apply(apply(w, b), X), Y) )).

cnf(hint_3, axiom,
	 $hint( apply(apply(apply(w, W1), X), Y) )).

cnf(hint_4, axiom,
	 $hint( apply(apply(w, apply(b, X)), Y) )).

cnf(hint_5, axiom,
	 $hint( apply(apply(apply(b, X), Y), Y) )).

cnf(hint_6, axiom,
	 $hint( apply(X, apply(Y, Y)) )).

cnf(hint_7, axiom,
	 $hint( apply(apply(w, apply(W1, Y)), X) )).

cnf(hint_8, axiom,
	 $hint( apply(apply(apply(W1, Y), X), X) )).

cnf(hint_9, axiom,
	 $hint( apply(X, apply(Y, X)) )).

cnf(hint_10, axiom,
	 $hint( apply(apply(apply(b, X), X), Y) )).

cnf(hint_11, axiom,
	 $hint( apply(apply(apply(W1, X), X), Y) )).

cnf(hint_12, axiom,
	 $hint( apply(apply(w, apply(apply(W1, X), Y)), Z) )).

cnf(hint_13, axiom,
	 $hint( apply(apply(apply(apply(W1, X), Y), Z), Z) )).

cnf(hint_14, axiom,
	 $hint( apply(apply(Y, apply(X, Z)), Z) )).

cnf(hint_15, axiom,
	 $hint( apply(apply(w, apply(b, X)), apply(apply(W1, Y), Z)) )).

cnf(hint_16, axiom,
	 $hint( apply(X, apply(apply(apply(W1, Y), Z), apply(apply(W1, Y), Z))) )).

cnf(hint_17, axiom,
	 $hint( apply(X, apply(Z, apply(Y, apply(apply(W1, Y), Z)))) )).

cnf(hint_18, axiom,
	 $hint( apply(apply(w, apply(apply(W1, X), apply(W1, Z))), Y) )).

cnf(hint_19, axiom,
	 $hint( apply(apply(apply(W1, Z), apply(X, Y)), Y) )).

cnf(hint_20, axiom,
	 $hint( apply(apply(X, Y), apply(Z, Y)) )).

cnf(hint_21, axiom,
	 $hint( apply(apply(w, apply(apply(W1, X), apply(apply(W1, Y), Z))), W) )).

cnf(hint_22, axiom,
	 $hint( apply(apply(apply(apply(W1, Y), Z), apply(X, W)), W) )).

cnf(hint_23, axiom,
	 $hint( apply(apply(Z, apply(Y, apply(X, W))), W) )).

cnf(hint_24, axiom,
	 $hint( apply(apply(w, apply(apply(W1, X), apply(W1, apply(apply(W1, Y), Z)))), W) )).

cnf(hint_25, axiom,
	 $hint( apply(apply(X, W), apply(apply(apply(W1, Y), Z), W)) )).
