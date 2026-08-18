"""Everything twee derived, kept, deduplicated, and made searchable.

The loop showed the planner eight equations per failing node per turn. Measured
on `logs/loop/RNG029-5-derive-01`, iteration 0, the `bridge` node -- the most
expensive search of the iteration and the one aimed straight at the conjecture:

    2,618 rules derived in the no-flatten direction, 3,711 in the flatten one
    1,099 and 1,043 of those survive filtering as usable equations
        8 reached the model

and the eight were `commutator(X,X) = 0`, `associator(X,X,Y) = 0` and six more
of the same kind -- plumbing the sketch already had. The same artifact holds 202
rules relating `associator` to non-trivial product structure, the first at rank
62. Across both ten-iteration runs, 166,705 derived rules were written to disk.
Neither run proved its target.

Three separate causes, all in `loop._candidates` and `llm.render_state`:

  * mining stopped at the FIRST artifact with any output (`if out: break`), so
    one of a node's two goal directions was never read at all;
  * the listing was truncated to 12 and then to 8;
  * the order was twee's own score, ascending. That is a *search* heuristic --
    it ranks a rule by how cheap it is to keep, which is exactly why the small
    trivial ones come first. `_useful` conceded as much: it "does not try to
    rank what remains, which nothing here has earned the right to do."

So this does not rank. It keeps everything usable, groups it by what kind of
equation it is, and lets the planner page through the groups without spending an
iteration or a prover-second.

**Permanent filters at mine time, sketch-relative filters at read time.** A rule
naming a run-local constant can never be a lemma, so it is dropped forever. A
rule the sketch already states is uninteresting *today* and may be worth having
the moment that node is removed, so it is stored and hidden on the way out. The
bank outlives any one sketch -- notably a `redraft`, which used to discard every
candidate found so far.

**Deduplicated by `terms.eq_key`**, the same orientation- and alpha-insensitive
identity used everywhere else here, so `a = b` and `b = a` under renamed
variables are one record with two sources. Two sources is itself the signal
`recurring` is built on: an equation twee reached from two different searches is
one the theory keeps producing.
"""
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from overtone import proofs
from overtone.terms import eq_key

# Run-local names twee mints for goal subterms and flattening constants. A rule
# mentioning one cannot become a reusable lemma: the name means nothing outside
# the run that created it. This is a PERMANENT filter -- such a rule is never
# worth storing.
RUN_LOCAL = re.compile(r"\b(sk_dag_\d+|[a-z_]+\d+)\b")

# twee writes an oriented rule `l -> r` and a permutative one `l <-> r`. Both are
# equations and both are candidates; splitting on `->` alone lands INSIDE the
# second arrow, leaving a left side ending in `<` and handing the model the
# literal string `multiply(a,b) < = multiply(b,a)`. One artifact of a single
# iteration carried 17 such rules.
ARROW = re.compile(r"\s*<?->\s*")

# Operators the free-ring normal form defines in terms of `multiply` and `add`.
# A rule tying one of these to real product structure is a *definition bridge*,
# which is the family that was invisible.
DEFINED = ("associator", "commutator")
ZERO = "additive_identity"

# What kind of equation this is. Not a ranking, and each was kept or cut on a
# measurement over `logs/loop/RNG029-5-derive-01` iteration 0 (1,927 usable
# equations, of which the planner saw 8).
#
# Two candidate facets were CUT for failing that measurement, and the reasons
# are worth keeping, because both are the original mistake in a new costume:
#
#   * `recurring` -- an equation derived by many different nodes. Ubiquity turns
#     out to be anti-correlated with usefulness: the top of that ordering is
#     `commutator(X,X) = 0`, `additive_inverse(0) = 0` and the additive group
#     laws, at 10-12 nodes each. Excluding the ones with a bare zero side does
#     not rescue it -- the next tier is `add(X,add(Y,-X)) = Y`. A rule the
#     theory produces from everywhere is a rule that says nothing about
#     anywhere.
#   * `residual_shape` -- an equation whose free-ring expansion overlaps the
#     goal's. Measured: zero matches out of 1,927. The RNG029-5 residual is two
#     degree-4 monomials and the derived rules are low-degree, so the test is
#     empty rather than selective.
FACETS = ("proof_lemma", "definition_bridge", "theory_content")

# Origin, most authoritative first. A proof lemma is a step twee HAD to derive;
# a derived rule is something it merely tried.
ORIGINS = ("proof_lemma", "goal_cited", "derived_rule")


def split_equation(body):
    """`(lhs, rhs)` from a twee rule body, or None if it is not one equation."""
    parts = ARROW.split(body, maxsplit=1)
    if len(parts) != 2:
        return None
    lhs, rhs = parts[0].strip(), parts[1].strip()
    return (lhs, rhs) if lhs and rhs else None


def evidence_id(lhs, rhs):
    """Stable, citable identity over `eq_key`, so the planner can name a rule.

    Over the equation and not the text: two spellings of one fact must resolve
    to one id, or `promote_evidence` could copy a statement the bank never saw.
    """
    key = json.dumps(eq_key(lhs, rhs), sort_keys=True, default=list)
    return "e" + hashlib.sha256(key.encode()).hexdigest()[:9]


@dataclass
class Evidence:
    """One equation, with every run that produced it."""
    id: str
    lhs: str
    rhs: str
    origin: str = "derived_rule"
    first_seen: int = 0
    sources: list = field(default_factory=list)
    # True when the free-ring expansion is empty, i.e. the equation holds in
    # ANY ring and so carries no information about this problem's axioms. Five
    # of the eight equations the planner was shown at derive-01 iteration 0 were
    # this, and the other three were the alternative laws it already had.
    #
    # Not the same as useless, which is why it is a flag and not a filter:
    # `assoc_def_add`, the most valuable node added in this project (18x on
    # `assoc_add_1`), is universal. A definitional rearrangement changes how the
    # rewrite system reaches a term without changing what is true. So the label
    # says "this cannot encode theory content", never "do not use this".
    universal: bool | None = None

    @property
    def artifacts(self):
        return {s.get("artifact") for s in self.sources}

    @property
    def nodes(self):
        return {s.get("node") for s in self.sources}

    def best_rank(self):
        ranks = [s.get("rank") for s in self.sources if s.get("rank") is not None]
        return min(ranks) if ranks else None

    def text(self):
        return f"{self.lhs} = {self.rhs}"

    def to_json(self):
        return {"id": self.id, "lhs": self.lhs, "rhs": self.rhs,
                "origin": self.origin, "first_seen": self.first_seen,
                "universal": self.universal, "sources": self.sources}

    def merge(self, other):
        self.origin = min(self.origin, other.origin,
                          key=lambda o: ORIGINS.index(o)
                          if o in ORIGINS else len(ORIGINS))
        self.first_seen = min(self.first_seen, other.first_seen)
        if self.universal is None:
            self.universal = other.universal
        have = {(s.get("artifact"), s.get("rank")) for s in self.sources}
        for s in other.sources:
            if (s.get("artifact"), s.get("rank")) not in have:
                self.sources.append(s)


def is_universal(lhs, rhs):
    """Does this hold in ANY ring? None when the free-ring normaliser cannot say.

    `freering.expand` returns the defect polynomial, empty when the two sides
    have the same normal form. That is the one cheap, principled discriminator
    available here -- 1,927 equations classify in 0.1s -- and it separates
    exactly the bucket that wasted the planner's attention.
    """
    from overtone import freering as F
    a, b = F.safe_parse(lhs), F.safe_parse(rhs)
    if a is None or b is None:
        return None
    try:
        return not F.expand(a, b)
    except Exception:                                             # noqa: BLE001
        return None


def families_of(ev):
    """Which facets this equation belongs to. A rule may be in several.

    Not a ranking and not a score. Each facet answers a different question, and
    the one that was missing is `definition_bridge`: an equation relating a
    defined operator to actual product structure, as against the accelerants
    (`associator(X,X,Y) = 0`) that dominate a score-ordered listing and that
    FINDINGS records as unable to flip a target on their own. The measured
    artifact holds 459 of them and showed the planner none.
    """
    out = []
    body = f"{ev.lhs} = {ev.rhs}"
    if ev.origin in ("proof_lemma", "goal_cited"):
        out.append("proof_lemma")
    if (any(d + "(" in body for d in DEFINED) and "multiply(" in body
            and ev.lhs.strip() != ZERO and ev.rhs.strip() != ZERO):
        out.append("definition_bridge")
    if ev.universal is False:
        out.append("theory_content")
    return tuple(out)


def relevance(e):
    """Order for a MIXED listing, where the facets are not doing the filtering.

    Shortest-first is right inside a facet and wrong across all of them: the
    shortest equations in any run are `commutator(X,X) = 0` and the additive
    group laws, so a plain length sort reproduces the score-ordered listing this
    module exists to replace -- measured, it did exactly that on the `bridge`
    node's own candidates.

    So the facet does the work first. A definition bridge is what was invisible
    and what the 18x node was an instance of; then anything that needs this
    problem's axioms; then length, as a proxy for generality.
    """
    fams = families_of(e)
    return (0 if "definition_bridge" in fams else 1,
            0 if e.universal is False else 1,
            len(e.text()), e.text())


def _order(facet):
    """Within-facet order. Every one is justified by the facet, never by score.

    twee's score ranks a rule by how cheap it is to keep, which is why a
    score-ordered listing opens with the smallest and most trivial equations in
    the run. Nothing here reuses it.
    """
    if facet is None:
        return relevance
    if facet == "proof_lemma":
        # Goal-cited first: on RNG027-5 a donor proof ran 234 lemmas deep, its
        # goal cited four, and those four flipped ten problems while all 234 in
        # the hint channel flipped none.
        return lambda e: (0 if e.origin == "goal_cited" else 1, len(e.text()))
    # Shortest first. A shorter identity is the more general one and the more
    # reusable as a node; measured, it puts the clean definitional bridges at
    # the top and the accreted eight-term variants at the bottom.
    return lambda e: (len(e.text()), e.text())


def provenance(artifact):
    """Which corpus an evidence source came from: `run`, `scratch` or `unknown`.

    Every source already records the artifact it was mined from; nothing could
    filter on it. One bank held 15 of its 51 artifacts from a `/tmp` scratchpad
    smoke test -- a scripted agent at a 120s budget, run while wiring a flag --
    mixed indiscriminately with the run's own searches. Nothing unsound follows,
    since the equations are theorems either way, but a bank that cannot tell a
    deliberate corpus from a temp directory cannot be an input to a reproducible
    experiment.
    """
    a = str(artifact or "")
    if "/scratchpad/" in a or a.startswith("/tmp/"):
        return "scratch"
    if "/logs/" in a or a.startswith("logs/"):
        return "run"
    return "unknown"


class Bank:
    """The evidence for one run, persisted as `evidence.jsonl`.

    Append-only and merged on load, so a crashed iteration loses nothing and two
    writers cannot corrupt each other's records -- the same reason
    `agent/ledger.py` is a JSONL append.
    """

    def __init__(self, path):
        self.path = Path(path)
        self.items = {}
        self.mined = set()
        self._load()

    # ------------------------------------------------------------- storage

    def _load(self):
        if not self.path.exists():
            return
        for line in self.path.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue                      # a torn final line; skip it
            if obj.get("_mined"):
                self.mined.add(obj["_mined"])
                continue
            ev = Evidence(obj["id"], obj["lhs"], obj["rhs"],
                          obj.get("origin", "derived_rule"),
                          obj.get("first_seen", 0), list(obj.get("sources", [])),
                          universal=obj.get("universal"))
            if ev.id in self.items:
                self.items[ev.id].merge(ev)
            else:
                self.items[ev.id] = ev

    def _append(self, records):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

    def __len__(self):
        return len(self.items)

    def all(self, corpus=None):
        """Every item, or only those with a source from `corpus`.

        `corpus="run"` is what a reproducible experiment wants: evidence mined
        from recorded runs under `logs/`, never from a scratchpad smoke test.
        """
        items = list(self.items.values())
        if corpus is None:
            return items
        want = {corpus} if isinstance(corpus, str) else set(corpus)
        return [e for e in items
                if any(provenance(s.get("artifact")) in want
                       for s in e.sources)]

    def by_provenance(self):
        """`{corpus: count}` over sources -- what this bank was actually built
        from, so a run can say so rather than being asked to be trusted."""
        from collections import Counter
        out = Counter()
        for e in self.items.values():
            for s in e.sources:
                out[provenance(s.get("artifact"))] += 1
        return dict(out)

    def get(self, eid):
        return self.items.get(eid)

    # -------------------------------------------------------------- mining

    def update(self, rows, *, iteration=0):
        """Mine every artifact these rows name that has not been mined before.

        EVERY artifact and BOTH directions. The predecessor stopped at the first
        one with any output, so a node's second direction -- 1,043 usable
        equations on the measured artifact -- was never read.

        Mining is keyed by artifact path and recorded in the bank, because these
        files are 350-550 KB each and there are thousands: re-reading them every
        turn is not affordable and, since an artifact never changes, not needed.
        """
        fresh, new_ids = [], 0
        for row in rows or ():
            path = row.get("output")
            if not path or path in self.mined or not Path(path).exists():
                continue
            self.mined.add(path)
            fresh.append({"_mined": path})
            for ev in _mine(path, row, iteration):
                if ev.id in self.items:
                    self.items[ev.id].merge(ev)
                else:
                    self.items[ev.id] = ev
                    new_ids += 1
                fresh.append(ev.to_json())
        if fresh:
            self._append(fresh)
        return new_ids

    # --------------------------------------------------------------- reading

    def visible(self, sketch=None):
        """Everything the sketch does not already state.

        Applied here rather than at mine time: a node removed two iterations
        later makes its equation interesting again, and a bank that had dropped
        it could not say so.
        """
        if sketch is None:
            return self.all()
        known = {eq_key(l, r) for l, r, _ in sketch.nodes.values()}
        return [e for e in self.items.values()
                if eq_key(e.lhs, e.rhs) not in known]

    def families(self, sketch=None):
        """`{facet: [Evidence]}` over what the sketch does not already have."""
        out = {f: [] for f in FACETS}
        for ev in self.visible(sketch):
            for fam in families_of(ev):
                out[fam].append(ev)
        for name, items in out.items():
            items.sort(key=_order(name))
        return out

    def summary(self, sketch=None, per_family=10):
        """What the planner is shown each turn: counts and some representatives.

        Counts, because "1,431 definition bridges" is itself the finding -- it
        says the search produced a whole seam the sketch does not name, which no
        truncated list of eight could ever convey. Representatives, because a
        listing of 1,431 is not readable either. `inspect_evidence` is how the
        planner sees the rest, and it costs no prover time and no iteration.

        Ten and not three. Three was measured: two runs were shown 3 of 1,431
        bridges and 3 of 5,238 theory-content equations, promoted fewer gold
        identities than the runs with no bank at all, and never once paged for
        more. The whole state payload was 17 KB, so the truncation was buying
        nothing -- it was the same reflex that showed the old listing eight
        equations out of two thousand.
        """
        fams = self.families(sketch)
        out = {}
        for name, items in fams.items():
            if not items:
                continue
            out[name] = {
                "count": len(items),
                "examples": [_row(e) for e in items[:per_family]],
            }
        out["_total"] = len(self.visible(sketch))
        return out

    def page(self, *, facet=None, contains=None, sketch=None, universal=None,
             page=0, per_page=20):
        """A read-only slice, for `inspect_evidence`.

        No prover time and no iteration: paging the bank is reading a file the
        run already wrote.
        """
        if facet and facet not in FACETS:
            raise ValueError(f"unknown facet {facet!r}; expected one of {FACETS}")
        items = (self.families(sketch)[facet] if facet
                 else sorted(self.visible(sketch), key=_order(None)))
        if contains:
            needle = contains.lower()
            items = [e for e in items if needle in e.text().lower()]
        if universal is not None:
            items = [e for e in items if e.universal is universal]
        page = max(0, int(page))
        start = page * per_page
        out = {"facet": facet or "all", "contains": contains,
               "n_matching": len(items), "page": page,
               "n_pages": max(1, -(-len(items) // per_page)),
               "items": [_row(e) for e in items[start:start + per_page]]}
        if not items:
            out.update(self._explain_empty(contains, sketch, facet, universal))
        return out

    def _explain_empty(self, contains, sketch, facet, universal):
        """Why a query matched nothing. Silence here is worse than useless.

        `n_matching: 0` conflates two opposite situations, and a run measured
        the cost. `visible` hides an equation the sketch already states -- right,
        or a promoted node would be re-offered as a candidate forever -- but the
        planner cannot see that from the outside. One run promoted
        `assoc_push_left_factor` at iteration 0 and then queried that same shape
        at iterations 1 through 6, getting a bare zero each time; 51 of its 99
        lookups came back empty, most of them this. It was being told "no" and
        hearing "not found" when the answer was "you already have it".

        So an empty result says which of these it is: the sketch has it, the
        facet filter excluded it, or no search ever produced it -- the last being
        the only one that means stop looking here.
        """
        matches = [e for e in self.items.values()
                   if not contains or contains.lower() in e.text().lower()]
        if not matches:
            return {"why_empty": "no run in this loop has derived anything "
                                 "matching that. This is not a filter -- the "
                                 "search has not produced it, so look for a "
                                 "different shape rather than rephrasing."}
        known = {}
        if sketch is not None:
            known = {eq_key(a, b): n for n, (a, b, _) in sketch.nodes.items()}
        have = [{"eq": e.text(), "node": known[eq_key(e.lhs, e.rhs)]}
                for e in matches if eq_key(e.lhs, e.rhs) in known]
        if have:
            return {"why_empty": "your sketch ALREADY STATES these, so they are "
                                 "hidden from candidate listings. You have them "
                                 "-- do not look again.",
                    "already_in_your_sketch": have[:10]}
        return {"why_empty": f"{len(matches)} equation(s) match the text but "
                             f"were excluded by this query's filters "
                             f"(facet={facet!r}, universal={universal!r}). "
                             f"Retry without them.",
                "excluded_by_filters": [_row(e) for e in matches[:5]]}


def _row(e):
    """One equation as the planner sees it. `id` is what `promote_evidence` takes."""
    out = {"id": e.id, "eq": e.text(), "origin": e.origin,
           "from": sorted(e.nodes)[:4]}
    if e.universal:
        # Said explicitly, because it bounds what the equation can do: it holds
        # in any ring, so it cannot carry this problem's content -- though it
        # can still be the rearrangement that makes a rewrite go through.
        out["universal"] = True
    return out


def _goal_cited(section):
    """Lemma numbers the GOAL's own derivation cites.

    Not `proofs.used_lemma_refs`, which also counts every `Lemma N:` header and
    so would mark the whole proof as goal-cited. The distinction is worth
    drawing precisely: on RNG027-5 a donor proof ran 234 lemmas deep, its goal
    cited exactly four, and those four flipped ten problems while all 234 in the
    hint channel flipped none.
    """
    lines = section.splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith("Goal ")), None)
    if start is None:
        return set()
    return {int(x)
            for x in proofs.USED_REF_RE.findall("\n".join(lines[start:]))}


def _mine(path, row, iteration):
    """Every usable equation in one artifact, proof lemmas first."""
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        return []
    node = row.get("node")
    direction = row.get("direction")
    support = list(row.get("support") or ())
    out, seen = [], set()

    def add(lhs, rhs, origin, score, rank):
        if RUN_LOCAL.search(f"{lhs} {rhs}"):
            return                            # a name that dies with the run
        try:
            eid = evidence_id(lhs, rhs)
        except Exception:                                         # noqa: BLE001
            return                            # unparseable is unusable
        if eid in seen:
            return
        seen.add(eid)
        out.append(Evidence(eid, lhs, rhs, origin, iteration,
                            [{"node": node, "direction": direction,
                              "artifact": str(path), "score": score,
                              "rank": rank, "iteration": iteration,
                              "support": support}],
                            universal=is_universal(lhs, rhs)))

    # A proof states its dependencies, so its lemmas are recorded steps rather
    # than things the search merely tried. They go first and outrank everything.
    section = proofs.proof_section(text)
    if section:
        cited = _goal_cited(section)
        for n, lhs, rhs in proofs.lemmas(section):
            add(lhs, rhs, "goal_cited" if n in cited else "proof_lemma",
                None, n)

    # The pre-proof search. A failed run has only these -- and a failed run is
    # the one worth mining, since it is where the missing node is hiding.
    rules = proofs.derived_rules(text)
    for rank, (num, r) in enumerate(
            sorted(rules.items(), key=lambda kv: kv[1]["score"]), start=1):
        eq = split_equation(r["body"])
        if eq:
            add(eq[0], eq[1], "derived_rule", r["score"], rank)
    return out


def load(run_dir, name="evidence.jsonl"):
    """The bank for a run directory, creating an empty one if there is none."""
    return Bank(Path(run_dir) / name)
