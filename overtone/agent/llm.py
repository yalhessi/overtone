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
   and it blocked six downstream nodes. If a node fails WITH parents but its
   standalone retry also fails, suspect the parents before the statement.

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

Reply only with tool calls. Emit no actions if you have nothing well-founded to
try; an empty list ends the run cleanly and is better than a guess."""

_SCHEMA = {
    "add_node": ({"name": "string", "lhs": "string", "rhs": "string",
                  "parents": "array"}, ["name", "lhs", "rhs"],
                 "Add a new lemma node."),
    "remove_node": ({"name": "string"}, ["name"],
                    "Remove a node and every edge into it."),
    "set_parents": ({"name": "string", "parents": "array"}, ["name", "parents"],
                    "Replace a node's parents. The usual fix for a wrong edge."),
    "subdivide": ({"name": "string", "intermediates": "array",
                   "parents": "array"}, ["name", "intermediates"],
                  "Insert intermediate nodes beneath a node and rewire it onto "
                  "them. The usual fix for a slow or failing node."),
    "restate": ({"name": "string", "lhs": "string", "rhs": "string",
                 "from_problem": "string"}, ["name"],
                "Change a node's statement. If the node is a TPTP problem you "
                "must pass from_problem so the statement is copied, not written."),
}


def tool_schemas(provider):
    """The action set in one provider's tool format."""
    out = []
    for name, (props, required, desc) in _SCHEMA.items():
        params = {"type": "object", "required": required,
                  "properties": {k: {"type": v} for k, v in props.items()}}
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
        "candidates_from_their_own_runs": {
            k: v[:max_candidates] for k, v in state.candidates.items()},
        "same_shape_siblings_that_proved": state.diffs,
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

    def act(self, state: State):
        prompt = render_state(state)
        if self.provider == "anthropic":
            body = {"model": self.model, "max_tokens": self.max_tokens,
                    "temperature": self.temperature, "system": SYSTEM,
                    "tools": tool_schemas("anthropic"),
                    "messages": [{"role": "user", "content": prompt}]}
            headers = {"x-api-key": self.api_key,
                       "anthropic-version": "2023-06-01"}
        else:
            body = {"model": self.model, "temperature": self.temperature,
                    "tools": tool_schemas("openai"),
                    "messages": [{"role": "system", "content": SYSTEM},
                                 {"role": "user", "content": prompt}]}
            headers = {"authorization": f"Bearer {self.api_key}"}

        resp = _post(ENDPOINTS[self.provider], headers, body)
        actions = self._parse(resp)
        self.transcript.append({"iteration": state.iteration, "request": body,
                                "response": resp, "actions": actions})
        if self.transcript_dir:
            self.transcript_dir.mkdir(parents=True, exist_ok=True)
            (self.transcript_dir / f"llm.{state.iteration:02d}.json").write_text(
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
        keep = [a for a in out if a.get("op") in ACTIONS]
        for a in out:
            if a.get("op") not in ACTIONS:
                print(f"  dropping unknown action {a.get('op')!r}", flush=True)
        return keep
