%------------------------------------------------------------------------------
% File     : LCL054-10 : TPTP v9.2.1. Released v7.3.0.
% Domain   : Puzzles
% Problem  : CN-35 depends on the Lukasiewicz system
% Version  : Especial.
% English  :

% Refs     : [CS18]  Claessen & Smallbone (2018), Efficient Encodings of Fi
%          : [Sma18] Smallbone (2018), Email to Geoff Sutcliffe
% Source   : [Sma18]
% Names    :

% Status   : Unsatisfiable
% Rating   : 0.83 v9.1.0, 0.82 v9.0.0, 0.86 v8.2.0, 0.83 v8.1.0, 0.85 v7.5.0, 0.92 v7.4.0, 1.00 v7.3.0
% Syntax   : Number of clauses     :    6 (   6 unt;   0 nHn;   1 RR)
%            Number of literals    :    6 (   6 equ;   1 neg)
%            Maximal clause size   :    1 (   1 avg)
%            Maximal term depth    :    5 (   2 avg)
%            Number of predicates  :    1 (   0 usr;   0 prp; 2-2 aty)
%            Number of functors    :    8 (   8 usr;   4 con; 0-4 aty)
%            Number of variables   :   11 (   2 sgn)
% SPC      : CNF_UNS_RFO_PEQ_UEQ

% Comments : Converted from LCL054-1 to UEQ using [CS18].
%------------------------------------------------------------------------------
cnf(ifeq_axiom,axiom,
    ifeq(A,A,B,C) = B ).

cnf(condensed_detachment,axiom,
    ifeq(is_a_theorem(implies(X,Y)),true,ifeq(is_a_theorem(X),true,is_a_theorem(Y),true),true) = true ).

cnf(cn_1,axiom,
    is_a_theorem(implies(implies(X,Y),implies(implies(Y,Z),implies(X,Z)))) = true ).

cnf(cn_2,axiom,
    is_a_theorem(implies(implies(not(X),X),X)) = true ).

cnf(cn_3,axiom,
    is_a_theorem(implies(X,implies(not(X),Y))) = true ).

cnf(prove_cn_35,negated_conjecture,
    is_a_theorem(implies(implies(a,implies(b,c)),implies(implies(a,b),implies(a,c)))) != true ).

%------------------------------------------------------------------------------
