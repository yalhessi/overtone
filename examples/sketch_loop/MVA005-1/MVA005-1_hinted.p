%------------------------------------------------------------------------------
% File     : MVA005-1 : TPTP v9.2.1. Released v8.1.0.
% Domain   : MV-algebras
% Problem  : (x V y) @ (z V u) = (x @ z) V (y @ u)
% Version  : [Ver10] (equality) axioms.
% English  :

% Refs     : [GT05]  Galatos & Tsinakis (2005), Generalized MV-algebras
%          : [GJ+07] Galatos et al. (2007), Residuated Lattices: An Algebra
%          : [Ver10] Veroff (2010), Email to Geoff Sutcliffe
%          : [Sma21] Smallbone (2021), Email to Geoff Sutcliffe
% Source   : [Ver10]
% Names    : gmv5.p [Sma21]

% Status   : Unsatisfiable
% Rating   : 1.00 v8.1.0
% Syntax   : Number of clauses     :   19 (  19 unt;   0 nHn;   1 RR)
%            Number of literals    :   19 (  19 equ;   1 neg)
%            Maximal clause size   :    1 (   1 avg)
%            Maximal term depth    :    5 (   2 avg)
%            Number of predicates  :    1 (   0 usr;   0 prp; 2-2 aty)
%            Number of functors    :   11 (  11 usr;   5 con; 0-2 aty)
%            Number of variables   :   39 (   6 sgn)
% SPC      : CNF_UNS_RFO_PEQ_UEQ

% Comments : See https://www.cs.unm.edu/~veroff/GMV/
%------------------------------------------------------------------------------
include('Axioms/MVA001-0.ax').
%------------------------------------------------------------------------------
cnf(goal,negated_conjecture,
    at(join(x,y),join(z,u)) != join(at(x,z),at(y,u)) ).

%------------------------------------------------------------------------------


cnf(hint_1, axiom,
	 $hint( op(X, Y) )).

cnf(hint_2, axiom,
	 $hint( at(X, unit) )).

cnf(hint_3, axiom,
	 $hint( rd(unit, X) )).

cnf(hint_4, axiom,
	 $hint( join(X, unit) )).

cnf(hint_5, axiom,
	 $hint( join(X, meet(X, Y)) )).

cnf(hint_6, axiom,
	 $hint( ld(X, Y) )).

cnf(hint_7, axiom,
	 $hint( join(X, Y) )).

cnf(hint_8, axiom,
	 $hint( at(X, Y) )).

cnf(hint_9, axiom,
	 $hint( ld(X, X) )).

cnf(hint_10, axiom,
	 $hint( rd(X, X) )).

cnf(hint_11, axiom,
	 $hint( op(X, join(Y, unit)) )).

cnf(hint_12, axiom,
	 $hint( join(meet(X, Y), X) )).

cnf(hint_13, axiom,
	 $hint( join(X, ld(unit, X)) )).

cnf(hint_14, axiom,
	 $hint( op(X, op(ld(X, unit), ld(ld(Y, unit), unit))) )).

cnf(hint_15, axiom,
	 $hint( op(X, ld(X, unit)) )).

cnf(hint_16, axiom,
	 $hint( join(X, rd(X, unit)) )).

cnf(hint_17, axiom,
	 $hint( meet(X, join(X, Y)) )).

cnf(hint_18, axiom,
	 $hint( meet(X, Y) )).

cnf(hint_19, axiom,
	 $hint( meet(rd(unit, X), ld(X, unit)) )).

cnf(hint_20, axiom,
	 $hint( ld(X, unit) )).

cnf(hint_21, axiom,
	 $hint( ld(ld(X, unit), unit) )).

cnf(hint_22, axiom,
	 $hint( at(unit, X) )).

cnf(hint_23, axiom,
	 $hint( op(at(X, unit), Y) )).

cnf(hint_24, axiom,
	 $hint( op(join(Y, unit), X) )).

cnf(hint_25, axiom,
	 $hint( meet(rd(ld(X, Y), Z), ld(X, rd(Y, Z))) )).
