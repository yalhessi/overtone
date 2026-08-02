"""The bridge: donor proof terms -> hints that fit the target problem.

docs/SKETCH_LOOP.md calls this the highest-risk component, and the measurements
back that up. Two failure modes it has to survive:

  Inert hints. A hint whose symbols are absent from the target never matches, so
  the intervention silently does not exist -- measured at 821ms vs 844ms
  baseline, i.e. no effect at all rather than a bad one. `adapt` variabilises
  donor-only constants instead of shipping a hint that cannot fire.

  Generality mismatch. Tiny hints like `join(X, Y)` match almost every subterm
  (82M firings on MVA005-1) and act as a blanket size discount; large specific
  ones may never match at all (18 firings in 600s on LCL054-10). The ablation
  showed the specific ones carry the proof and the generic ones only accelerate,
  so ranking has to keep specific hints above the cap -- see `rank_by`.
"""
from overtone.terms import VAR, alpha, safe_term, unparse

# Twitch's wins used 9-33 hints; 227 hints ran 2.1x slower than none.
MAX_HINTS = 25
# Factor 0 is pathological: a hint then costs nothing, so any critical pair
# matching a large hint scores ~0 and monopolises the queue.
HINT_FLAGS = ("--hint-skel-factor 0.5", "--hint-skel-cost 0")


def adapt(t, target_syms, subst):
    """Fit a donor term to the target signature.

    Donor constants absent from the target (twee's flattening constants f2...,
    goal constants) become fresh variables. Terms using absent *non-nullary*
    functions cannot be fixed this way; return None to drop.
    """
    if isinstance(t, str):
        if VAR.match(t) or (t, 0) in target_syms:
            return t
        if t not in subst:
            subst[t] = f"W{len(subst) + 1}"
        return subst[t]
    if (t[0], len(t) - 1) not in target_syms:
        return None
    args = [adapt(a, target_syms, subst) for a in t[1:]]
    if any(a is None for a in args):
        return None
    return (t[0], *args)


def specificity(t) -> int:
    """Function-symbol count: how much structure a hint actually constrains."""
    if isinstance(t, str):
        return 0 if VAR.match(t) else 1
    return 1 + sum(specificity(a) for a in t[1:])


def build_hints(counts, target_syms, cap: int = MAX_HINTS, rank_by="frequency"):
    """Filter and adapt donor terms into a hint list of at most `cap`.

    `rank_by="frequency"` reproduces v0: order by occurrences in the donor proof.
    Note this favours the *least* informative terms, because generic subterms
    recur most. On MVA005-1 the cap of 25 happened to admit 13 specific hints
    alongside 12 generic ones and the structural content survived by luck; a
    tighter cap would have kept only accelerants and lost the problem.

    `rank_by="specificity"` puts structural hints first so they clear the cap.
    """
    scored, dropped, seen = [], 0, set()
    for raw, n in counts.most_common():
        t = safe_term(raw)
        if t is None or isinstance(t, str):
            dropped += 1                      # unparseable, or no content
            continue
        adapted = adapt(t, target_syms, {})
        if adapted is None:
            dropped += 1
            continue
        key = alpha(adapted)
        if key in seen:
            continue
        seen.add(key)
        scored.append((unparse(adapted), n, raw, specificity(adapted)))
        # Frequency order is already the output order, so stop at the cap --
        # this also keeps `dropped` counting only what was examined, matching
        # the artifacts in examples/. Specificity ranking has to see everything.
        if rank_by == "frequency" and len(scored) >= cap:
            break

    if rank_by == "specificity":
        scored.sort(key=lambda r: (-r[3], -r[1]))
    kept = [(h, n, raw) for h, n, raw, _ in scored[:cap]]
    return kept, dropped


def split_by_specificity(hints, threshold: int = 3):
    """Partition hints into (specific, generic) by symbol count.

    The ablation that this supports: on MVA005-1 the 12 generic hints alone
    could not prove the conjecture, the 13 specific ones alone proved it in
    852.9s, and together 546.8s -- so the transferred structure is the mechanism
    and the generic hints are accelerant.
    """
    specific, generic = [], []
    for h in hints:
        term = h[0] if isinstance(h, tuple) else h
        t = safe_term(term)
        n = len(str(term).replace("(", " ").replace(")", " ").replace(",", " ").split()) \
            if t is None else _symbol_count(t)
        (generic if n <= threshold else specific).append(h)
    return specific, generic


def _symbol_count(t) -> int:
    if isinstance(t, str):
        return 1
    return 1 + sum(_symbol_count(a) for a in t[1:])
