%------------------------------------------------------------------------------
% File     : GRP674-11 : TPTP v9.2.1. Released v8.1.0.
% Domain   : Group Theory (Quasigroups)
% Problem  : Extra loop commutation property 3
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

% Comments : UEQ version, converted from GRP674+1.p
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
    mult(asoc(op_x,op_y,op_z),asoc(op_x,op_y,op_t)) = asoc(op_x,op_y,mult(op_z,op_t)) ).

cnf(goal,negated_conjecture,
    mult(op_z,asoc(op_x,op_y,op_t)) != mult(asoc(op_x,op_y,op_t),op_z) ).

%------------------------------------------------------------------------------
