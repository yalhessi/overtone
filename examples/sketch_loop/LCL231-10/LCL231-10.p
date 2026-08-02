%------------------------------------------------------------------------------
% File     : LCL231-10 : TPTP v9.2.1. Released v7.5.0.
% Domain   : Puzzles
% Problem  : Principia Mathematica 2.86
% Version  : Especial.
% English  :

% Refs     : [CS18]  Claessen & Smallbone (2018), Efficient Encodings of Fi
%          : [Sma18] Smallbone (2018), Email to Geoff Sutcliffe
% Source   : [Sma18]
% Names    :

% Status   : Unsatisfiable
% Rating   : 0.83 v9.1.0, 0.82 v9.0.0, 0.91 v8.2.0, 0.92 v8.1.0, 1.00 v7.5.0
% Syntax   : Number of clauses     :   10 (  10 unt;   0 nHn;   1 RR)
%            Number of literals    :   10 (  10 equ;   1 neg)
%            Maximal clause size   :    1 (   1 avg)
%            Maximal term depth    :    5 (   2 avg)
%            Number of predicates  :    1 (   0 usr;   0 prp; 2-2 aty)
%            Number of functors    :   10 (  10 usr;   4 con; 0-4 aty)
%            Number of variables   :   19 (   2 sgn)
% SPC      : CNF_UNS_RFO_PEQ_UEQ

% Comments : Converted from LCL231-3 to UEQ using [CS18].
%------------------------------------------------------------------------------
cnf(ifeq_axiom,axiom,
    ifeq(A,A,B,C) = B ).

cnf(axiom_1_2,axiom,
    axiom(implies(or(A,A),A)) = true ).

cnf(axiom_1_3,axiom,
    axiom(implies(A,or(B,A))) = true ).

cnf(axiom_1_4,axiom,
    axiom(implies(or(A,B),or(B,A))) = true ).

cnf(axiom_1_5,axiom,
    axiom(implies(or(A,or(B,C)),or(B,or(A,C)))) = true ).

cnf(axiom_1_6,axiom,
    axiom(implies(implies(A,B),implies(or(C,A),or(C,B)))) = true ).

cnf(implies_definition,axiom,
    implies(X,Y) = or(not(X),Y) ).

cnf(rule_1,axiom,
    ifeq(axiom(X),true,theorem(X),true) = true ).

cnf(rule_2,axiom,
    ifeq(theorem(implies(Y,X)),true,ifeq(theorem(Y),true,theorem(X),true),true) = true ).

cnf(prove_this,negated_conjecture,
    theorem(implies(implies(implies(p,q),implies(p,r)),implies(p,implies(q,r)))) != true ).

%------------------------------------------------------------------------------
