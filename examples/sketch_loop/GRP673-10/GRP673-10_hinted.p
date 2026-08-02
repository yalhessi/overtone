%------------------------------------------------------------------------------
% File     : GRP673-10 : TPTP v9.2.1. Released v8.1.0.
% Domain   : Group Theory (Quasigroups)
% Problem  : Extra loop commutation property 2
% Version  : Especial.
% English  : In an extra loop, z commutes with [x;y; t] if and only if t
%            commutes with [x;y; z] if and only if [x;y; z][x;y; t] = [x;y; zt].

% Refs     : [KK04]  Kinyon & Kunen (2004), The Structure of Extra Loops
%          : [PS08]  Phillips & Stanovsky (2008), Automated Theorem Proving
%          : [Sma21] Smallbone (2021), Email to Geoff Sutcliffe
% Source   : [Sma21]
% Names    : 

% Status   : Unsatisfiable
% Rating   : 1.00 v8.1.0
% Syntax   : Number of clauses     :   10 (  10 unt;   0 nHn;   2 RR)
%            Number of literals    :   10 (  10 equ;   1 neg)
%            Maximal clause size   :    1 (   1 avg)
%            Maximal term depth    :    4 (   2 avg)
%            Number of predicates  :    1 (   0 usr;   0 prp; 2-2 aty)
%            Number of functors    :    9 (   9 usr;   5 con; 0-3 aty)
%            Number of variables   :   16 (   0 sgn)
% SPC      : CNF_UNS_RFO_PEQ_UEQ

% Comments : UEQ version, converted from GRP673+1.p
%------------------------------------------------------------------------------
cnf(f01,axiom,
    mult(A,ld(A,B)) = B ).

cnf(f02,axiom,
    ld(A,mult(A,B)) = B ).

cnf(f03,axiom,
    mult(rd(A,B),B) = A ).

cnf(f04,axiom,
    rd(mult(A,B),B) = A ).

cnf(f05,axiom,
    mult(A,unit) = A ).

cnf(f06,axiom,
    mult(unit,A) = A ).

cnf(f07,axiom,
    mult(A,mult(B,mult(C,A))) = mult(mult(mult(A,B),C),A) ).

cnf(f08,axiom,
    asoc(A,B,C) = ld(mult(A,mult(B,C)),mult(mult(A,B),C)) ).

cnf(f09,axiom,
    mult(op_t,asoc(op_x,op_y,op_z)) = mult(asoc(op_x,op_y,op_z),op_t) ).

cnf(goal,negated_conjecture,
    mult(op_z,asoc(op_x,op_y,op_t)) != mult(asoc(op_x,op_y,op_t),op_z) ).

%------------------------------------------------------------------------------


cnf(hint_1, axiom,
	 $hint( rd(mult(X, Y), X) )).

cnf(hint_2, axiom,
	 $hint( mult(W1, W2) )).

cnf(hint_3, axiom,
	 $hint( mult(ld(W1, X), W2) )).

cnf(hint_4, axiom,
	 $hint( mult(X, mult(ld(X, Y), ld(Y, mult(unit, X)))) )).

cnf(hint_5, axiom,
	 $hint( mult(rd(unit, rd(Y, X)), Y) )).

cnf(hint_6, axiom,
	 $hint( ld(W1, rd(X, W2)) )).

cnf(hint_7, axiom,
	 $hint( mult(ld(ld(X, Y), Y), ld(Y, ld(X, Y))) )).

cnf(hint_8, axiom,
	 $hint( ld(ld(X, Y), mult(rd(unit, X), Y)) )).

cnf(hint_9, axiom,
	 $hint( rd(rd(X, W1), X) )).

cnf(hint_10, axiom,
	 $hint( mult(rd(X, ld(Y, Z)), rd(Z, Y)) )).

cnf(hint_11, axiom,
	 $hint( rd(mult(X, ld(ld(Y, Z), Z)), Y) )).

cnf(hint_12, axiom,
	 $hint( mult(rd(X, ld(Y, mult(Z, Y))), Z) )).

cnf(hint_13, axiom,
	 $hint( mult(rd(X, Y), ld(Z, mult(Y, Z))) )).

cnf(hint_14, axiom,
	 $hint( mult(mult(X, rd(Y, ld(X, Z))), Z) )).

cnf(hint_15, axiom,
	 $hint( mult(mult(X, Y), ld(Z, mult(X, Z))) )).

cnf(hint_16, axiom,
	 $hint( mult(rd(X, ld(W1, Y)), W2) )).

cnf(hint_17, axiom,
	 $hint( mult(mult(X, W1), ld(W1, unit)) )).

cnf(hint_18, axiom,
	 $hint( mult(mult(X, W1), W2) )).

cnf(hint_19, axiom,
	 $hint( mult(Y, ld(X, unit)) )).

cnf(hint_20, axiom,
	 $hint( mult(W1, mult(X, W1)) )).

cnf(hint_21, axiom,
	 $hint( ld(W1, rd(X, W1)) )).

cnf(hint_22, axiom,
	 $hint( rd(ld(W1, X), W1) )).

cnf(hint_23, axiom,
	 $hint( mult(W1, mult(W2, X)) )).

cnf(hint_24, axiom,
	 $hint( rd(rd(X, W1), W2) )).

cnf(hint_25, axiom,
	 $hint( rd(X, W1) )).
