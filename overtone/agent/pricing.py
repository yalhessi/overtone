"""Token accounting for model-backed runs.

A loop iteration costs prover CPU *and* model tokens, and only one of those was
ever reported. A run whose cost is invisible cannot be budgeted, and "the agent
did something for a while" is not a result.

Rates are USD per million tokens, per provider:

  * Anthropic (platform.claude.com, 2026-06-24): cache reads bill at 0.1x input
    and cache writes at 1.25x (5-minute TTL), uniformly across models, so those
    two are derived rather than listed.
  * OpenAI (developers.openai.com/api/docs/pricing, retrieved 2026-08-04):
    cached input is quoted per model and is NOT a fixed multiple -- 0.1x on
    gpt-5, 0.5x on gpt-4o and o1 -- so it is listed explicitly. There is no
    separate cache-write charge.

A model absent from the table reports tokens with `cost=None` rather than a
guessed number: a confidently wrong cost is worse than an absent one.
"""
from dataclasses import dataclass, field

ANTHROPIC_CACHE_READ, ANTHROPIC_CACHE_WRITE = 0.1, 1.25


@dataclass(frozen=True)
class Price:
    """Per-million-token rates for the four counters we track."""
    input: float
    output: float
    cache_read: float
    cache_write: float


def _anthropic(inp, out):
    return Price(inp, out, inp * ANTHROPIC_CACHE_READ, inp * ANTHROPIC_CACHE_WRITE)


def _openai(inp, out, cached):
    # No cache-write charge; cached input is quoted directly.
    return Price(inp, out, cached if cached is not None else inp, 0.0)


PRICES = {
    # -- Anthropic -----------------------------------------------------------
    "claude-fable-5":    _anthropic(10.00, 50.00),
    "claude-mythos-5":   _anthropic(10.00, 50.00),
    "claude-opus-5":     _anthropic(5.00, 25.00),
    "claude-opus-4-8":   _anthropic(5.00, 25.00),
    "claude-opus-4-7":   _anthropic(5.00, 25.00),
    "claude-opus-4-6":   _anthropic(5.00, 25.00),
    # Sonnet 5 carries an introductory $2/$10 through 2026-08-31; the standard
    # rate is listed, so an estimate for it is an upper bound until then.
    "claude-sonnet-5":   _anthropic(3.00, 15.00),
    "claude-sonnet-4-6": _anthropic(3.00, 15.00),
    "claude-haiku-4-5":  _anthropic(1.00, 5.00),
    # -- OpenAI --------------------------------------------------------------
    "gpt-5.6-sol":       _openai(5.00, 30.00, 0.50),
    "gpt-5.6-terra":     _openai(2.00, 12.00, 0.20),
    "gpt-5.6-luna":      _openai(0.20, 1.20, 0.02),
    "gpt-5.5":           _openai(5.00, 30.00, 0.50),
    "gpt-5.5-pro":       _openai(30.00, 180.00, None),
    "gpt-5.4":           _openai(2.50, 15.00, 0.25),
    "gpt-5.4-mini":      _openai(0.75, 4.50, 0.075),
    "gpt-5.4-nano":      _openai(0.20, 1.25, 0.02),
    "gpt-5":             _openai(1.25, 10.00, 0.125),
    "gpt-5-mini":        _openai(0.25, 2.00, 0.025),
    "gpt-4o":            _openai(2.50, 10.00, 1.25),
    "gpt-4o-mini":       _openai(0.15, 0.60, 0.075),
    "o1":                _openai(15.00, 60.00, 7.50),
    "o1-pro":            _openai(150.00, 600.00, None),
    "o3":                _openai(2.00, 8.00, 0.50),
    "o3-pro":            _openai(20.00, 80.00, None),
    "o3-mini":           _openai(1.10, 4.40, 0.55),
}


@dataclass
class Usage:
    """Tokens across every model call in a run, and what they cost."""
    model: str = ""
    calls: int = 0
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    steps: list = field(default_factory=list)   # per-call rows, for the trajectory

    def add(self, model, step, usage: dict):
        """Accumulate one response's usage, normalising the two wire formats."""
        row = from_response(model, usage)
        self.model = self.model or model
        self.calls += 1
        for k in ("input", "output", "cache_read", "cache_write"):
            setattr(self, k, getattr(self, k) + row[k])
        self.steps.append({"step": step, **row, "cost": cost(model, row)})
        return self.steps[-1]

    def total(self):
        return self.input + self.output + self.cache_read + self.cache_write

    def cost(self):
        return cost(self.model, {"input": self.input, "output": self.output,
                                 "cache_read": self.cache_read,
                                 "cache_write": self.cache_write})

    def to_json(self):
        return {"model": self.model, "calls": self.calls, "input": self.input,
                "output": self.output, "cache_read": self.cache_read,
                "cache_write": self.cache_write, "tokens": self.total(),
                "cost_usd": self.cost(), "steps": self.steps}


def from_response(model, usage: dict) -> dict:
    """One provider's usage block as a common row.

    Anthropic reports `input_tokens`/`output_tokens` plus cache fields; OpenAI
    reports `prompt_tokens`/`completion_tokens` with cached tokens nested under
    `prompt_tokens_details.cached_tokens`. Reading all of them here keeps the
    accounting in one place rather than in each adapter.

    OpenAI's `prompt_tokens` INCLUDES the cached ones, so they are subtracted
    out; Anthropic reports uncached input separately and needs no adjustment.
    Getting that wrong double-counts the cached span at the full input rate --
    the more expensive direction, and invisible in the totals.
    """
    usage = usage or {}
    cached = ((usage.get("prompt_tokens_details") or {}).get("cached_tokens")
              or usage.get("cache_read_input_tokens") or 0)
    if "prompt_tokens" in usage:
        inp = max((usage.get("prompt_tokens") or 0) - cached, 0)
    else:
        inp = usage.get("input_tokens") or 0
    return {
        "input": inp,
        "output": usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0,
        "cache_read": cached,
        "cache_write": usage.get("cache_creation_input_tokens", 0) or 0,
    }


def cost(model, row) -> float | None:
    """USD for one usage row, or None when the model's price is not known."""
    p = PRICES.get(model)
    if p is None:
        return None
    return ((row["input"] * p.input
             + row["cache_read"] * p.cache_read
             + row["cache_write"] * p.cache_write
             + row["output"] * p.output) / 1e6)


def render(u: Usage) -> str:
    """A one-line summary. Says so where the price is unknown, never a guess."""
    c = u.cost()
    money = f"${c:.2f}" if c is not None else f"cost unknown for {u.model!r}"
    return (f"{u.calls} model call(s), {u.total():,} tokens "
            f"(in {u.input:,}, out {u.output:,}, "
            f"cache r{u.cache_read:,}/w{u.cache_write:,}) -- {money}")
