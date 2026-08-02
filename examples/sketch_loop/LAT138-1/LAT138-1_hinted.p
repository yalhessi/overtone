%------------------------------------------------------------------------------
% File     : LAT138-1 : TPTP v9.2.1. Released v3.1.0.
% Domain   : Lattice Theory
% Problem  : Huntington equation H7 implies H6
% Version  : [McC05] (equality) axioms : Especial.
% English  :

% Refs     : [McC05] McCune (2005), Email to Geoff Sutcliffe
% Source   : [McC05]
% Names    :

% Status   : Unsatisfiable
% Rating   : 0.70 v9.1.0, 0.68 v8.2.0, 0.62 v8.1.0, 0.65 v7.5.0, 0.75 v7.4.0, 0.78 v7.3.0, 0.84 v7.1.0, 0.89 v6.4.0, 0.84 v6.3.0, 0.88 v6.2.0, 0.86 v6.1.0, 0.94 v6.0.0, 1.00 v5.0.0, 0.93 v4.1.0, 0.91 v4.0.1, 0.93 v4.0.0, 0.92 v3.7.0, 0.89 v3.4.0, 0.88 v3.3.0, 1.00 v3.1.0
% Syntax   : Number of clauses     :   10 (  10 unt;   0 nHn;   1 RR)
%            Number of literals    :   10 (  10 equ;   1 neg)
%            Maximal clause size   :    1 (   1 avg)
%            Maximal term depth    :    7 (   2 avg)
%            Number of predicates  :    1 (   0 usr;   0 prp; 2-2 aty)
%            Number of functors    :    5 (   5 usr;   3 con; 0-2 aty)
%            Number of variables   :   19 (   2 sgn)
% SPC      : CNF_UNS_RFO_PEQ_UEQ

% Comments :
%------------------------------------------------------------------------------
%----Include Lattice theory (equality) axioms
include('Axioms/LAT001-0.ax').
%------------------------------------------------------------------------------
cnf(equation_H7,axiom,
    meet(X,join(Y,meet(X,Z))) = meet(X,join(Y,meet(X,join(meet(X,Y),meet(Z,join(X,Y)))))) ).

cnf(prove_H6,negated_conjecture,
    meet(a,join(b,meet(a,c))) != meet(a,join(meet(a,join(b,meet(a,c))),meet(c,join(a,b)))) ).

%------------------------------------------------------------------------------


cnf(hint_1, axiom,
	 $hint( join(X, Y) )).

cnf(hint_2, axiom,
	 $hint( join(X, join(Y, Z)) )).

cnf(hint_3, axiom,
	 $hint( meet(X, Y) )).

cnf(hint_4, axiom,
	 $hint( join(meet(X, Y), meet(X, join(Z, meet(Y, join(W, meet(X, Y)))))) )).

cnf(hint_5, axiom,
	 $hint( meet(X, join(Z, meet(Y, join(W, meet(X, Y))))) )).

cnf(hint_6, axiom,
	 $hint( meet(X, join(Y, meet(X, Z))) )).

cnf(hint_7, axiom,
	 $hint( meet(Y, meet(X, Z)) )).

cnf(hint_8, axiom,
	 $hint( meet(meet(X, Z), Y) )).

cnf(hint_9, axiom,
	 $hint( join(X, meet(Y, X)) )).

cnf(hint_10, axiom,
	 $hint( join(X, meet(X, Y)) )).

cnf(hint_11, axiom,
	 $hint( join(join(Y, Z), X) )).

cnf(hint_12, axiom,
	 $hint( meet(X, meet(Y, join(X, Z))) )).

cnf(hint_13, axiom,
	 $hint( meet(X, meet(join(X, Z), Y)) )).

cnf(hint_14, axiom,
	 $hint( meet(meet(X, join(X, Z)), Y) )).

cnf(hint_15, axiom,
	 $hint( join(X, join(Y, meet(X, Z))) )).

cnf(hint_16, axiom,
	 $hint( join(X, join(meet(X, Z), Y)) )).

cnf(hint_17, axiom,
	 $hint( join(join(X, meet(X, Z)), Y) )).

cnf(hint_18, axiom,
	 $hint( meet(X, meet(Y, join(Z, meet(X, Y)))) )).

cnf(hint_19, axiom,
	 $hint( meet(X, meet(Y, join(Z, meet(Y, X)))) )).

cnf(hint_20, axiom,
	 $hint( meet(X, meet(Y, join(meet(Y, X), Z))) )).

cnf(hint_21, axiom,
	 $hint( meet(Y, meet(X, join(meet(Y, X), Z))) )).

cnf(hint_22, axiom,
	 $hint( meet(meet(Y, X), join(meet(Y, X), Z)) )).

cnf(hint_23, axiom,
	 $hint( join(X, join(Y, meet(Z, join(X, Y)))) )).

cnf(hint_24, axiom,
	 $hint( join(X, join(Y, meet(Z, join(Y, X)))) )).

cnf(hint_25, axiom,
	 $hint( join(X, join(Y, meet(join(Y, X), Z))) )).
