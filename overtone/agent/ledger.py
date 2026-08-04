"""A record of what has already been asked of the prover, so nothing is re-run.

The motivating waste: `rng033_goal` was verified standalone at 300s in one
iteration, failed, and the next iteration re-ran the *identical* configuration at
900s -- which is both a repeat and the "wait it out" move this project's
diagnostic-budget rule exists to forbid.

**Identity is over bytes, not meaning.** twee's search depends on the order rules
enter the system, so a reordered axiom list is a different search and may well
have a different outcome. Any semantic key -- alpha-normalised equations, sorted
axiom sets -- would wrongly collapse those and skip a run that could have
succeeded. So the key is a hash of:

  * the exact bytes of the input file handed to twee;
  * the flag list, in order, including the goal direction;
  * the binary, since the deterministic and stock builds search differently;
  * TWEE_STEPS_PER_SECOND, which sets the deterministic build's schedule;
  * the TPTP root, since the input's `include(...)` lines resolve against it.

Budget is deliberately *not* in the key, because outcomes are monotone in it and
that is what makes reuse useful:

  * proved at any budget      -> proved at a larger one. Reuse.
  * timed out at B, want <= B -> more time is the only thing that could help,
                                 and we are asking for less. Reuse.
  * timed out at B, want > B  -> genuinely unanswered. Run it.

Anything else -- a different file, a different flag, a different build -- is a
different question and is always run.
"""
import hashlib
import json
import os
from pathlib import Path

from overtone import config

LEDGER = "ledger.jsonl"
# Environment that changes the search rather than merely where things are.
ENV_KEYS = ("TWEE_STEPS_PER_SECOND",)


def key_for(input_path, flags, binary, *, tptp_root=None) -> str:
    """Identity of a prover invocation: the bytes, the flags, the build.

    Reading the file rather than reconstructing it from arguments is the point.
    `write_problem` decides axiom order, prefixes and formatting, and any of
    those can change a search; hashing its output cannot drift from what was
    actually run.
    """
    h = hashlib.sha256()
    h.update(Path(input_path).read_bytes())
    h.update(b"\0flags\0" + "\0".join(str(f) for f in flags).encode())
    h.update(b"\0binary\0" + str(binary or "").encode())
    h.update(b"\0root\0" + str(tptp_root or config.tptp_root()).encode())
    for k in ENV_KEYS:
        h.update(f"\0{k}\0{os.environ.get(k, '')}".encode())
    return h.hexdigest()


def path(ledger=None) -> Path:
    return Path(ledger) if ledger else (config.LOGS / LEDGER)


def load(ledger=None) -> dict:
    """{key: best known row}. A proof beats a timeout; a longer timeout wins."""
    p = path(ledger)
    if not p.exists():
        return {}
    best = {}
    with open(p) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue                      # a torn line from a killed writer
            k, prev = rec.get("key"), best.get(rec.get("key"))
            if not k:
                continue
            if (prev is None
                    or (rec.get("proved") and not prev.get("proved"))
                    or (rec.get("proved") == prev.get("proved")
                        and (rec.get("budget") or 0) > (prev.get("budget") or 0))):
                best[k] = rec
    return best


def lookup(key, budget, index=None, ledger=None):
    """A prior row that answers this question, or None.

    Monotonicity in budget is the whole basis for reuse; see the module
    docstring. A recorded failure at a *smaller* budget answers nothing.
    """
    rec = (index if index is not None else load(ledger)).get(key)
    if rec is None:
        return None
    if rec.get("proved"):
        return rec
    if (rec.get("budget") or 0) >= budget:
        return rec
    return None


def record(key, row, budget, ledger=None):
    """Append one outcome. Line-buffered append so parallel workers can share."""
    p = path(ledger)
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {"key": key, "budget": budget,
           **{k: row.get(k) for k in ("node", "direction", "channel",
                                      "n_support", "result", "proved", "cpu",
                                      "wall")}}
    with open(p, "a") as fh:
        fh.write(json.dumps(rec) + "\n")
    return rec
