"""Translate Otter/EQP equations into twee $hint terms.

Otter syntax differs from TPTP in three ways that matter here:
  * '+' is infix and declared xfy (right associative), so a+b+c means a+(b+c)
  * variables are the symbols beginning u,v,w,x,y,z; everything else is a constant
  * 'n' is negation, '+' is addition; the TPTP ROB problems call these negate/add

Twee hints are terms, not equations, so each equation contributes both sides.
"""
import re

VAR_INITIALS = set("uvwxyz")


def tokenize(s):
    return re.findall(r'\(|\)|\+|[A-Za-z][A-Za-z0-9_]*|\S', s)


class P:
    def __init__(self, toks):
        self.t = toks
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def eat(self, x=None):
        tok = self.t[self.i]
        assert x is None or tok == x, f"expected {x} got {tok}"
        self.i += 1
        return tok

    def expr(self):
        """'+' is xfy: parse one atom, and recurse right on the tail."""
        left = self.atom()
        if self.peek() == '+':
            self.eat('+')
            return ['add', left, self.expr()]
        return left

    def atom(self):
        tok = self.eat()
        if tok == '(':
            e = self.expr()
            self.eat(')')
            return e
        if self.peek() == '(':          # function application, e.g. n(...)
            self.eat('(')
            args = [self.expr()]
            while self.peek() == ',':
                self.eat(',')
                args.append(self.expr())
            self.eat(')')
            name = 'negate' if tok == 'n' else tok
            return [name] + args
        return tok                       # variable or constant


def to_tptp(tree, constmap):
    if isinstance(tree, str):
        if tree[0] in VAR_INITIALS and tree.islower():
            return tree.upper()          # Otter variable -> TPTP variable
        return constmap.get(tree, tree.lower())
    return f"{tree[0]}({', '.join(to_tptp(a, constmap) for a in tree[1:])})"


def parse_equation(line):
    line = line.split('%')[0].strip().rstrip('.')
    if not line or '!=' in line:
        return None                       # denials are goals, not hints
    if '=' not in line:
        return None
    lhs, rhs = line.split('=', 1)
    return P(tokenize(lhs)).expr(), P(tokenize(rhs)).expr()


def hints_from_otter(path, constmap, section='hints'):
    """Pull a list(<section>) block and return TPTP hint terms, deduplicated."""
    out, inside = [], False
    for line in open(path):
        s = line.strip()
        if s.startswith(f'list({section})'):
            inside = True
            continue
        if inside and s.startswith('end_of_list'):
            break
        if not inside:
            continue
        eq = parse_equation(s)
        if eq:
            for side in eq:
                out.append(to_tptp(side, constmap))
    seen, uniq = set(), []
    for t in out:
        if t not in seen and '(' in t:     # drop bare variables/constants
            seen.add(t)
            uniq.append(t)
    return uniq


def hints_from_proof(path, constmap):
    """Otter proof lines look like '123 [just] <equation>.' -- take the equations."""
    out = []
    for line in open(path):
        m = re.match(r'^\s*\d+(?:,\d+)?\s*\[[^\]]*\]\s*(.+)$', line)
        if not m:
            continue
        eq = parse_equation(m.group(1))
        if eq:
            for side in eq:
                out.append(to_tptp(side, constmap))
    seen, uniq = set(), []
    for t in out:
        if t not in seen and '(' in t:
            seen.add(t)
            uniq.append(t)
    return uniq
