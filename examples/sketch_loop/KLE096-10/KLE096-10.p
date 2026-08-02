%------------------------------------------------------------------------------
% File     : KLE096-10 : TPTP v9.2.1. Released v7.5.0.
% Domain   : Puzzles
% Problem  : Modal operators satisfy a star unfold law
% Version  : Especial.
% English  :

% Refs     : [CS18]  Claessen & Smallbone (2018), Efficient Encodings of Fi
%          : [Sma18] Smallbone (2018), Email to Geoff Sutcliffe
% Source   : [Sma18]
% Names    :

% Status   : Unsatisfiable
% Rating   : 1.00 v7.5.0
% Syntax   : Number of clauses     :   35 (  35 unt;   0 nHn;   1 RR)
%            Number of literals    :   35 (  35 equ;   1 neg)
%            Maximal clause size   :    1 (   1 avg)
%            Maximal term depth    :    6 (   2 avg)
%            Number of predicates  :    1 (   0 usr;   0 prp; 2-2 aty)
%            Number of functors    :   22 (  22 usr;   5 con; 0-4 aty)
%            Number of variables   :   62 (   5 sgn)
% SPC      : CNF_UNS_RFO_PEQ_UEQ

% Comments : Converted from KLE096+1 to UEQ using [CS18].
%------------------------------------------------------------------------------
cnf(ifeq_axiom,axiom,
    ifeq3(A,A,B,C) = B ).

cnf(ifeq_axiom_001,axiom,
    ifeq2(A,A,B,C) = B ).

cnf(ifeq_axiom_002,axiom,
    ifeq(A,A,B,C) = B ).

cnf(additive_commutativity,axiom,
    addition(A,B) = addition(B,A) ).

cnf(additive_associativity,axiom,
    addition(A,addition(B,C)) = addition(addition(A,B),C) ).

cnf(additive_identity,axiom,
    addition(A,zero) = A ).

cnf(additive_idempotence,axiom,
    addition(A,A) = A ).

cnf(multiplicative_associativity,axiom,
    multiplication(A,multiplication(B,C)) = multiplication(multiplication(A,B),C) ).

cnf(multiplicative_right_identity,axiom,
    multiplication(A,one) = A ).

cnf(multiplicative_left_identity,axiom,
    multiplication(one,A) = A ).

cnf(right_distributivity,axiom,
    multiplication(A,addition(B,C)) = addition(multiplication(A,B),multiplication(A,C)) ).

cnf(left_distributivity,axiom,
    multiplication(addition(A,B),C) = addition(multiplication(A,C),multiplication(B,C)) ).

cnf(right_annihilation,axiom,
    multiplication(A,zero) = zero ).

cnf(left_annihilation,axiom,
    multiplication(zero,A) = zero ).

cnf(order_1,axiom,
    ifeq2(leq(A,B),true,addition(A,B),B) = B ).

cnf(order,axiom,
    ifeq3(addition(A,B),B,leq(A,B),true) = true ).

cnf(star_unfold_right,axiom,
    leq(addition(one,multiplication(A,star(A))),star(A)) = true ).

cnf(star_unfold_left,axiom,
    leq(addition(one,multiplication(star(A),A)),star(A)) = true ).

cnf(star_induction_left,axiom,
    ifeq(leq(addition(multiplication(A,B),C),B),true,leq(multiplication(star(A),C),B),true) = true ).

cnf(star_induction_right,axiom,
    ifeq(leq(addition(multiplication(A,B),C),A),true,leq(multiplication(C,star(B)),A),true) = true ).

cnf(domain1,axiom,
    multiplication(antidomain(X0),X0) = zero ).

cnf(domain2,axiom,
    addition(antidomain(multiplication(X0,X1)),antidomain(multiplication(X0,antidomain(antidomain(X1))))) = antidomain(multiplication(X0,antidomain(antidomain(X1)))) ).

cnf(domain3,axiom,
    addition(antidomain(antidomain(X0)),antidomain(X0)) = one ).

cnf(domain4,axiom,
    domain(X0) = antidomain(antidomain(X0)) ).

cnf(codomain1,axiom,
    multiplication(X0,coantidomain(X0)) = zero ).

cnf(codomain2,axiom,
    addition(coantidomain(multiplication(X0,X1)),coantidomain(multiplication(coantidomain(coantidomain(X0)),X1))) = coantidomain(multiplication(coantidomain(coantidomain(X0)),X1)) ).

cnf(codomain3,axiom,
    addition(coantidomain(coantidomain(X0)),coantidomain(X0)) = one ).

cnf(codomain4,axiom,
    codomain(X0) = coantidomain(coantidomain(X0)) ).

cnf(complement,axiom,
    c(X0) = antidomain(domain(X0)) ).

cnf(domain_difference,axiom,
    domain_difference(X0,X1) = multiplication(domain(X0),antidomain(X1)) ).

cnf(forward_diamond,axiom,
    forward_diamond(X0,X1) = domain(multiplication(X0,domain(X1))) ).

cnf(backward_diamond,axiom,
    backward_diamond(X0,X1) = codomain(multiplication(codomain(X1),X0)) ).

cnf(forward_box,axiom,
    forward_box(X0,X1) = c(forward_diamond(X0,c(X1))) ).

cnf(backward_box,axiom,
    backward_box(X0,X1) = c(backward_diamond(X0,c(X1))) ).

cnf(goals,negated_conjecture,
    addition(domain(sK2_goals_X0),forward_diamond(star(sK1_goals_X1),forward_diamond(sK1_goals_X1,domain(sK2_goals_X0)))) != forward_diamond(star(sK1_goals_X1),domain(sK2_goals_X0)) ).

%------------------------------------------------------------------------------
