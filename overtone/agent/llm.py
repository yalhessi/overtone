"""Model-backed agents for the loop, Anthropic and OpenAI, behind one protocol.

Deliberately stdlib-only. `pyproject.toml` keeps `dependencies = []` so
`import overtone` works in any interpreter, and both providers are a JSON POST --
carrying two SDKs to send one request would cost that invariant and add version
drift between them. It also means the trajectory can record exactly what was
sent, which matters when a run is the training data.

**One action schema, two wire formats.** The closed action set from `loop.py` is
expressed once as JSON Schema and adapted to Anthropic's `input_schema` and
OpenAI's `function.parameters`. A model that emits an illegal action is rejected
by `loop.apply`, not here -- there is exactly one validator.

**The system prompt is the findings.** Everything the model is told about how to
revise a sketch was measured, and is cited with its number. A model that "knows"
to add lemmas when a node is slow, or to raise a budget instead of subdividing,
would be wrong in the specific ways this project already paid for.
"""
import json
import urllib.error
import urllib.request
from pathlib import Path

from overtone import config
from overtone.agent import pricing
from overtone.agent.loop import ACTIONS, State

ENDPOINTS = {
    "anthropic": "https://api.anthropic.com/v1/messages",
    "openai": "https://api.openai.com/v1/chat/completions",
}
KEYS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
# Anthropic's current most capable model. OpenAI's is deliberately not guessed --
# pass --model or set OPENAI_MODEL, so a stale identifier here cannot silently
# select something other than what was intended.
DEFAULT_MODEL = {"anthropic": "claude-opus-5", "openai": None}

SYSTEM = """\
You revise a proof sketch for the twee equational theorem prover. A sketch is a
DAG: each node is an equation, and its parents are the lemmas supplied as axioms
when that node is verified against the problem's own axioms.

Everything below was measured on this project. Follow it over your own priors.

1. BUDGET IS A DIAGNOSTIC, NOT A RESOURCE. Every node of a correct decomposition
   verifies in seconds. A node that is slow or times out means the sketch is
   wrong THERE. Subdivide it or fix its parents; never ask for more time.
   A node at 32.9s was missing one node beneath it; adding that node gave 18x.

2. WRONG PARENTS COST MORE THAN MISSING ONES. An axiom forms critical pairs with
   every rule, so an irrelevant parent is pure cost. One node went 3.3s with no
   parents, 358.6s with two plausible ones, and timed out at 900s with five --
   and it blocked six downstream nodes. TWO FIELDS TELL YOU WHERE TO LOOK.

   `unused_support` on a node that PROVED lists the parents its proof never
   cited. Across 154 proved runs here, 164 of 307 supplied parents were never
   cited. Each is a candidate for `set_parents` WITHOUT it -- a hypothesis, not
   a verdict: removing an axiom changes the search, so it can come back slower.
   Declare a `speed_up` probe and find out. The controller may already be
   testing one for you; `review_of_your_last_edits` says so when it is, and puts
   the parents back by itself if the node got slower.

   `failure` on a node that did NOT prove says why, and the three want opposite
   repairs:
   * `saturated` -- the search CLOSED and your statement does not follow from
     what was supplied. Time cannot help and neither can re-parenting: parents
     are lemmas already entailed by the axioms, so removing them cannot make a
     saturated goal provable. Suspect the STATEMENT -- it is false, or far too
     big a step. Restate it or subdivide it. An agent that re-parented such a
     node three iterations running ended its run having proved nothing new; the
     node was full associativity, which is false in the very theory the problem
     is about.
   * `timeout` -- the budget ran out with the question open. Either the step is
     too big (subdivide) or a parent costs more than it pays (drop it and see).
   * `error` -- nothing was proved about anything. Not mathematics; do not
     redesign the sketch around it.

3. PREFER FEW, EXACT PARENTS. Direct parents beat the full ancestor closure:
   five lemmas and thirteen performed identically, and supplying the right five
   was worth ~3000x over supplying none.

4. COMPARE AGAINST A SIBLING THAT WORKED. Every wrong-edge fault here was found
   that way. If a failing node has the SAME parents as a same-shape sibling that
   proved, that is the bug: mirrored statements need mirrored parents. One such
   substitution was a 300s timeout against 1.0s.

5. MINE THE NODE'S OWN RUN. The candidates you are given are equations twee
   derived but the sketch does not name. The single most valuable node added in
   this project was read off exactly that listing.

6. NEVER AUTHOR A STATEMENT FOR A NODE THAT IS A TPTP PROBLEM. Use
   restate(from_problem=...) so it is copied. A node here once drifted from a
   problem's conjecture by one rewrite and stopped being that problem.

7. `goal_contact.both` VETOES EDITS; IT DOES NOT RANK THEM. It counts derived
   rules touching BOTH sides of the goal, and only such a rule can close it. A
   FALL is real evidence the edit hurt: one refinement here raised the rule count
   and both sides while cutting `both` from 162 to 102, and it made the problem
   harder. Revert an edit that cuts it. But a RISE proves nothing -- on the same
   node, supplying NO parents scores 371, the highest measured, and did not prove
   the goal at 300s. Never maximise it, and never read it as progress.
   Rules derived, and each side on its own, are not evidence in either
   direction. Do not reason about term shapes you expect in the output -- twee
   renames goal subterms, so what you would grep for is not there.

8. READ `review_of_your_last_edits` FIRST. Proposals are reviewed before they
   reach the prover: a `reject` was withheld and never ran, so re-proposing it
   unchanged wastes a turn. A `note` is information, not an objection -- in
   particular "needs the theory's own axioms" is the normal case for a useful
   lemma. But if you derived a node as pure rearrangement of definitions and it
   is reported non-universal, your algebra is wrong; fix the statement rather
   than subdividing it. An agent here subdivided an unsound node for three
   iterations, which produced more unsound nodes.

9. DECLARE WHAT YOUR EDIT PREDICTS. Put `probe` and `hypothesis` on the first
   action of your batch: which node should change, and to what -- `prove`,
   `speed_up`, or `target`. The next turn reports
   `outcome_of_your_last_edits` scored against it. Only a probe that comes true
   counts as progress. A node proving that your probe did not name is
   `inconclusive`: it does not clear a stall, because a run here proved 27 nodes
   across ten iterations while never getting closer to the conjecture. An edit
   that cuts `target_attempt.contact_delta_both` is `regressed` and is REVERTED
   automatically -- you will be told what was undone, and re-proposing it is a
   wasted turn.

10. REDRAFT WHEN `stalled_iterations` >= 2 OR `iterations_on_approach` >= 4.
   Two different failures, and the second is the one that hides. Stalled means
   no new node has been PROVED, however many you added. But proving nodes is not
   the objective -- closing the goal is, and an approach can prove node after
   node while never getting closer. One run here proved 27 nodes across ten
   iterations, never stalled once, never changed approach, and spent 11,647
   prover-seconds without a proof. One run here sat at 15 proved nodes
   for four iterations while adding five more, each a small local edit; the
   sketch grew and nothing moved. Small edits cannot rescue a decomposition that
   is aimed wrong -- they can only make it bigger. Call `redraft` with a NAMED
   approach that is genuinely different from everything in
   `approaches_already_tried`, keep the proved nodes worth carrying, and design
   the new set as a whole. The one success this project has had is a 29-node
   library designed coherently, not a sketch nudged into shape.
   At `iterations_on_approach` >= 4 this stops being advice: every edit that is
   not a redraft is withheld, and a turn that offers none ends the run.
   A REDRAFT MUST PROPOSE NEW LEMMAS. Keeping the nodes that already proved and
   deleting the rest is a retreat to a subset that was already not enough, and
   it is withheld. Beware especially of retreating to small generic lemmas like
   `associator(X,X,Y) = 0` or `commutator(X,X) = 0`: those are ACCELERANTS,
   measured here as unable to prove a target on their own, and a sketch made
   only of them proves every node and closes nothing. What is missing in that
   situation is a WAYPOINT -- a big structural identity partway to the goal.

Reply only with tool calls. Emit no actions if you have nothing well-founded to
try; an empty list ends the run cleanly and is better than a guess."""

DRAFT_SYSTEM = """\
You are drafting the FIRST proof sketch for a problem, before anything has been
run. You are given the problem's axioms and its conjecture, and nothing else --
there is no runtime evidence yet, because nothing has been proved or attempted.

A sketch is a DAG of lemmas. Each node is an equation; its parents are supplied
as axioms when it is verified against the problem's own axioms. Beneath it all
sits the goal, which already exists -- see the end of these instructions.

What makes a good intermediate lemma, measured on this project:

* IT MUST BE FAR FROM BOTH ENDS. A restatement of the conjecture, or an instance
  of it with two variables identified, is still the conjecture -- it decomposes
  nothing. A lemma one rewrite from an axiom buys nothing either. Aim for the
  middle: real work from the axioms, real progress toward the goal.
* PREFER LEMMAS TRUE IN EVERY MODEL OF THE SIGNATURE, not just this theory.
  Those are sound by construction and cannot be an accident of this problem. The
  single most useful node in this project's best sketch is of exactly this kind:
  an identity relating a defined operator to products, true in every ring.
* RELATE THE OPERATORS THE CONJECTURE MIXES. If the goal combines two defined
  symbols, lemmas connecting them are where the decomposition lives.
* FEW, EXACT PARENTS. An axiom forms critical pairs with every rule, so an
  irrelevant parent is pure cost. One node here went 3.3s with no parents and
  timed out at 900s with five.
* EVERY NODE SHOULD BE PROVABLE IN SECONDS. If you expect a node to be hard, it
  is not a waypoint -- subdivide it further before proposing it.

THE AXIOMS ARE ALREADY NODES. Every axiom of the problem is in the sketch under
its own name, listed for you as `axiom_nodes`. Cite one as a parent to record
that your lemma rests on it. NEVER restate an axiom as a new node: it is already
there, it is true by assumption, and a copy is pure cost. A node's `parents` may
name an axiom node or a node appearing EARLIER in your own list.

Write terms in the problem's own syntax, using the same function symbols the
axioms use, with single uppercase letters for variables (X, Y, Z, W).

THE GOAL NODE ALREADY EXISTS. Its name is given to you as `goal_node`, and its
statement was copied from the problem file -- do NOT restate it or add a node
for it. Name the nodes that should be supplied when it is attempted in
`goal_parents` instead.

SIZE. Call draft_sketch exactly once, with 8-30 lemma nodes in dependency
order. Do not aim for the smallest sketch that looks plausible: the one route
this project has ever driven to a proof on a problem of this difficulty is a
29-lemma library, designed as a coherent whole. A five-node sketch of generic
identities proves every node and closes nothing."""

# Drafting emits a DAG, not a stream of edits. Expressed as ONE tool taking the
# whole node list, because a per-node action schema gets one node per response:
# a real run drafted a single node in 55 output tokens and stopped.
_DRAFT_NODE = {
    "type": "object",
    "required": ["name", "lhs", "rhs"],
    "properties": {
        "name": {"type": "string",
                 "description": "snake_case identifier for this lemma"},
        "lhs": {"type": "string",
                "description": "left side, in the problem's own syntax, e.g. "
                               "add(multiply(X,Y),Z). Variables are single "
                               "uppercase letters."},
        "rhs": {"type": "string", "description": "right side, same syntax"},
        "parents": {"type": "array", "items": {"type": "string"},
                    # This used to read "Never an axiom name", contradicting
                    # DRAFT_SYSTEM, which tells the model axioms ARE nodes and
                    # to cite one to record what a lemma rests on. Citing an
                    # axiom is free -- `Sketch.equations` drops given nodes, so
                    # it documents the derivation without re-supplying the text.
                    "description": "names of an axiom node, or of a node "
                                   "appearing EARLIER in this list. Citing an "
                                   "axiom records what your lemma rests on and "
                                   "costs nothing."},
        # Declared so a claim can be CONTRADICTED. `universal` is checkable by
        # exact expansion in the free ring with no prover, and a node claimed
        # universal that leaves a residue is an algebra error, not a hard lemma
        # -- one run subdivided such a node for three iterations, producing more
        # unsound nodes each time. The other classes are recorded, not checked:
        # needing the theory's own axioms is the normal case for a useful lemma
        # and must never be treated as a defect.
        "justification": {
            "type": "string",
            "enum": ["universal", "theory_specific", "proof_mined", "derived"],
            "description": "universal: true in EVERY model of this signature, "
                           "by expanding the defined operators. "
                           "theory_specific: needs this problem's own axioms. "
                           "proof_mined: read off a prover's own output. "
                           "derived: computed exactly, e.g. by free-ring "
                           "expansion.",
        },
    },
}

_DRAFT_SCHEMA = {
    "type": "object",
    "required": ["approach", "nodes", "goal_parents"],
    "properties": {
        "approach": {"type": "string",
                     "description": "One line naming the mathematical route "
                                    "this decomposition takes, e.g. 'expand "
                                    "the defined operators and work additively'. "
                                    "Recorded, and shown back to you if it "
                                    "stalls so you do not retry it."},
        "nodes": {"type": "array", "items": _DRAFT_NODE,
                  "description": "8-30 lemma nodes, in dependency order. Do not "
                                 "include the goal node; it already exists."},
        "goal_parents": {
            "type": "array", "items": {"type": "string"},
            "description": "Which of your nodes should be supplied when the goal "
                           "itself is attempted. Few and exact -- an irrelevant "
                           "one is pure cost."},
    },
}

# What this batch predicts, declared BEFORE it runs. The loop scores the
# iteration against it and only a probe that comes true counts as progress -- a
# node proving that nothing asked for is `inconclusive` and does not clear a
# stall. Attached to the edits rather than requested separately so a batch and
# its prediction cannot be recorded apart from one another.
_PROBE = {
    "type": "object",
    "required": ["node", "expect"],
    "description": "What this edit predicts. Declare it on the FIRST action of "
                   "your batch.",
    "properties": {
        "node": {"type": "string",
                 "description": "the node whose behaviour should change"},
        "expect": {"type": "string",
                   "enum": ["prove", "speed_up", "target"],
                   "description": "prove: a currently failing/blocked node "
                                  "verifies. speed_up: a slow node drops below "
                                  "the diagnostic threshold. target: the "
                                  "conjecture itself moves."},
    },
}
_HYPOTHESIS = {"type": "string",
               "description": "One line: why you expect that, in terms of the "
                              "mathematics. Recorded and shown back to you."}

_SCHEMA = {
    "add_node": ({"name": "string", "lhs": "string", "rhs": "string",
                  "parents": {"type": "array", "items": {"type": "string"},
                             "description": "node names"}},
                 ["name", "lhs", "rhs"], "Add a new lemma node."),
    "remove_node": ({"name": "string"}, ["name"],
                    "Remove a node and every edge into it."),
    "set_parents": ({"name": "string", "parents": {"type": "array", "items": {"type": "string"},
                             "description": "node names"}},
                    ["name", "parents"],
                    "Replace a node's parents. The usual fix for a wrong edge."),
    "subdivide": ({"name": "string",
                   "intermediates": {"type": "array", "items": _DRAFT_NODE,
                                     "description": "new nodes to insert "
                                                    "beneath, in dependency "
                                                    "order"},
                   "parents": {"type": "array", "items": {"type": "string"},
                             "description": "node names"}},
                  ["name", "intermediates"],
                  "Insert intermediate nodes beneath a node and rewire it onto "
                  "them. The usual fix for a slow or failing node."),
    # `nodes` carries the full node schema, not a bare "array". A structured
    # field described only in prose is a field the model guesses at: that is
    # what produced a one-node draft from a tool asking for five to fifteen.
    "redraft": ({"approach": "string",
                 "nodes": {"type": "array", "items": _DRAFT_NODE,
                           "description": "the new decomposition, in dependency "
                                          "order. Must be non-empty: a redraft "
                                          "that proposes no new lemmas only "
                                          "deletes, and retreating to the nodes "
                                          "that already proved is not a new "
                                          "route."},
                 "keep": {"type": "array", "items": {"type": "string"},
                          "description": "names of PROVED nodes to carry over; "
                                         "axioms and the goal are kept "
                                         "automatically"},
                 "goal_parents": {"type": "array", "items": {"type": "string"},
                                  "description": "which new nodes the goal is "
                                                 "attempted with"}},
                ["approach", "nodes"],
                "Replace the decomposition wholesale with a new one under a "
                "NAMED approach, keeping the axioms, the goal, and any proved "
                "nodes you list in `keep`. Use this when the sketch has "
                "stalled: the other actions only nudge, and a different route "
                "needs a different set of lemmas, not another nudge. `nodes` "
                "takes the same shape as draft_sketch: {name, lhs, rhs, "
                "parents} in dependency order."),
    "restate": ({"name": "string", "lhs": "string", "rhs": "string",
                 "from_problem": "string"}, ["name"],
                "Change a node's statement. If the node is a TPTP problem you "
                "must pass from_problem so the statement is copied, not written."),
}


def draft_schema(provider):
    """The single drafting tool in one provider's format."""
    desc = ("Propose the initial proof sketch: the full list of lemma nodes "
            "plus the goal, in dependency order. Call this exactly once.")
    if provider == "anthropic":
        return [{"name": "draft_sketch", "description": desc,
                 "input_schema": _DRAFT_SCHEMA}]
    return [{"type": "function",
             "function": {"name": "draft_sketch", "description": desc,
                          "parameters": _DRAFT_SCHEMA}}]


def tool_schemas(provider):
    """The action set in one provider's tool format."""
    out = []
    for name, (props, required, desc) in _SCHEMA.items():
        # A property is either a bare type name or a full JSON Schema fragment,
        # so a structured field can describe its items instead of being an
        # untyped array the model has to infer.
        # Every edit op can carry the batch's prediction. Not required by the
        # schema -- a model that omits it still gets its edits applied, and the
        # loop scores that turn on the weakest available reading ("did anything
        # move at all") rather than refusing to run.
        params = {"type": "object", "required": required,
                  "properties": {k: ({"type": v} if isinstance(v, str) else v)
                                 for k, v in props.items()}}
        params["properties"]["probe"] = _PROBE
        params["properties"]["hypothesis"] = _HYPOTHESIS
        if provider == "anthropic":
            out.append({"name": name, "description": desc, "input_schema": params})
        else:
            out.append({"type": "function",
                        "function": {"name": name, "description": desc,
                                     "parameters": params}})
    return out


def render_state(state: State, *, max_candidates=8):
    """The state as compact JSON. Structured, because prose invites invention."""
    nodes = []
    for n in state.nodes:
        row = {"name": n.name, "eq": f"{n.lhs} = {n.rhs}", "status": n.status,
               "parents": list(n.parents)}
        if n.cpu is not None:
            row["cpu"] = round(n.cpu, 1)
        # Both omitted rather than sent as null. A node has one or the other at
        # most, and rows carrying two dead keys apiece cost tokens on every node
        # of every turn to say nothing.
        if n.unused_support:
            row["unused_support"] = list(n.unused_support)
        if n.failure:
            row["failure"] = n.failure
        nodes.append(row)
    payload = {
        "problem": state.problem,
        "iteration": state.iteration,
        "cpu_spent": round(state.cpu_spent, 1),
        "nodes": nodes,
        "needs_attention": {
            "slow": [n.name for n in state.slow()],
            "failing": [n.name for n in state.failing()],
        },
        # Where the starting sketch came from, when it was derived rather than
        # drafted. A node whose provenance says "polarization of an axiom, using
        # these lemmas" is one the model can reason about instead of re-deriving.
        "derived_from": list(state.sources),
        "candidates_from_their_own_runs": {
            k: v[:max_candidates] for k, v in state.candidates.items()},
        "same_shape_siblings_that_proved": state.diffs,
        # Judge an edit by `both`, not by rules or either side alone. On
        # RNG033-8 a refinement raised the rule count and both sides while
        # cutting `both` from 162 to 102, and every other number endorsed it.
        "goal_contact": state.contact,
        # The attempt on the REAL problem file with the goal's declared parents
        # supplied. `contact_delta_both` is the only number here that carries
        # evidence about your last edit, and only when it is negative.
        "target_attempt": state.target,
        # How your last edits scored against the probe you declared with them.
        "outcome_of_your_last_edits": state.outcome,
        # Review of YOUR last proposals. `reject` means the edit was withheld
        # and never reached the prover. Do not re-propose it unchanged.
        "review_of_your_last_edits": [f.to_json() for f in state.findings],
        "approach": state.approach,
        "approaches_already_tried": list(state.approaches_tried),
        # Iterations in a row whose declared probe did not come true. Adding
        # nodes is not progress, and neither is proving one nothing asked for.
        "stalled_iterations": state.stalled,
        "iterations_on_approach": state.iterations_on_approach,
    }
    return json.dumps(payload, indent=1)


def _post(url, headers, body, timeout=120):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"content-type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{url} -> {e.code}: {e.read()[:400].decode(errors='replace')}") from None


class LLMAgent:
    """An `Agent` backed by a model. Records every exchange for offline replay.

    `transcript` accumulates {request, response} pairs; the loop writes them into
    the trajectory so a run can be attributed to what the model was actually
    shown. A run whose inputs are not recorded cannot be replayed, and a
    trajectory that cannot be replayed is not training data.
    """

    def __init__(self, provider="anthropic", model=None, *, max_tokens=4096,
                 temperature=0.0, api_key=None, transcript_dir=None):
        if provider not in ENDPOINTS:
            raise ValueError(f"provider must be one of {sorted(ENDPOINTS)}")
        self.provider = provider
        self.model = model or DEFAULT_MODEL[provider] or config.env(
            "OPENAI_MODEL" if provider == "openai" else "ANTHROPIC_MODEL")
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.api_key = api_key or config.env(KEYS[provider])
        self.transcript_dir = Path(transcript_dir) if transcript_dir else None
        self.transcript = []
        self.usage = pricing.Usage()

    def draft(self, problem, axioms, conjecture, goal_name="goal"):
        """Propose an initial sketch from the problem statement alone.

        Without this the loop starts by verifying whatever seed it was handed --
        for a goal-only seed, that is one guaranteed-failing run before the agent
        is consulted at all, and no drafting ever happens. Drafting is the first
        half of draft -> verify -> diagnose -> revise; running the loop without it
        exercises only the second.
        """
        payload = json.dumps({"problem": problem, "axiom_nodes": axioms,
                              "goal_node": goal_name,
                              "conjecture": {"lhs": conjecture[0],
                                             "rhs": conjecture[1]}}, indent=1)
        rows = self._call(DRAFT_SYSTEM, payload, step="draft",
                          tools=draft_schema(self.provider), force="draft_sketch")
        # A draft IS a redraft from an empty sketch: same operation, one code
        # path, and the initial approach gets named like any later one. Naming
        # only later approaches left the first entry of every history blank.
        out = []
        for r in rows:
            nodes = [n for n in (r.get("nodes") or [])
                     if n.get("name") and n.get("lhs") and n.get("rhs")]
            out.append({"op": "redraft",
                        "approach": r.get("approach", "") or "(unnamed)",
                        "nodes": nodes, "keep": [], "goal": goal_name,
                        "goal_parents": list(r.get("goal_parents") or [])})
        # `_call` logs tool CALLS; one draft_sketch call is a whole DAG, so the
        # node count is the number that means anything here.
        n = sum(len(a.get("nodes", [])) for a in out)
        what = out[0]["approach"] if out else "nothing"
        print(f"  drafted {n} node(s) in {len(rows)} call(s): {what!r}", flush=True)
        return out

    def act(self, state: State):
        prompt = render_state(state)
        return self._call(SYSTEM, prompt, step=f"iter{state.iteration:02d}")

    def _call(self, system, prompt, *, step, tools=None, force=None):
        if self.provider == "anthropic":
            body = {"model": self.model, "max_tokens": self.max_tokens,
                    "temperature": self.temperature, "system": system,
                    "tools": tools or tool_schemas("anthropic"),
                    "messages": [{"role": "user", "content": prompt}]}
            if force:
                body["tool_choice"] = {"type": "tool", "name": force}
            headers = {"x-api-key": self.api_key,
                       "anthropic-version": "2023-06-01"}
        else:
            # `max_completion_tokens`, not `max_tokens`: the o-series and gpt-5
            # families reject the older name. Without any ceiling a long draft
            # is at the mercy of the model's default.
            body = {"model": self.model, "temperature": self.temperature,
                    "max_completion_tokens": self.max_tokens,
                    "tools": tools or tool_schemas("openai"),
                    "messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": prompt}]}
            if force:
                body["tool_choice"] = {"type": "function",
                                       "function": {"name": force}}
            headers = {"authorization": f"Bearer {self.api_key}"}

        resp = _post(ENDPOINTS[self.provider], headers, body)
        actions = self._parse(resp)
        row = self.usage.add(self.model, step, resp.get("usage") or {})
        money = f"${row['cost']:.4f}" if row["cost"] is not None else "cost n/a"
        print(f"  agent[{step}]: {len(actions)} action(s), "
              f"in {row['input']:,} / out {row['output']:,} tokens, {money}",
              flush=True)
        self.transcript.append({"step": step, "request": body,
                                "response": resp, "actions": actions,
                                "usage": row})
        if self.transcript_dir:
            self.transcript_dir.mkdir(parents=True, exist_ok=True)
            (self.transcript_dir / f"llm.{step}.json").write_text(
                json.dumps(self.transcript[-1], indent=2) + "\n")
        return actions

    def _parse(self, resp):
        """Tool calls -> actions. Unknown names are dropped here with a note; a
        malformed *argument* is left for `loop.apply` to reject, so there is one
        validator rather than two that can disagree."""
        out = []
        if self.provider == "anthropic":
            for block in resp.get("content", []):
                if block.get("type") == "tool_use":
                    out.append({"op": block["name"], **(block.get("input") or {})})
        else:
            for choice in resp.get("choices", []):
                for call in (choice.get("message") or {}).get("tool_calls") or []:
                    fn = call.get("function") or {}
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        continue
                    out.append({"op": fn.get("name"), **args})
        if any(a.get("op") == "draft_sketch" for a in out):
            return [a for a in out if a.get("op") == "draft_sketch"]
        keep = [a for a in out if a.get("op") in ACTIONS]
        for a in out:
            if a.get("op") not in ACTIONS:
                print(f"  dropping unknown action {a.get('op')!r}", flush=True)
        return keep
