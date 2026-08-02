"""Choosing which solved problem's proof to transfer from."""
from pathlib import Path

from overtone import batch, config
from overtone.problems import axiom_sets, problem_path
from overtone.terms import merged, similarity

PROOFS = config.LOGS / "screen" / "proofs"


def saved_proofs(domain: str, proofs_dir: Path | None = None):
    """{problem: proof path} for solved problems in `domain` with saved output.

    Parses `batch.PROOF_STEM`. If that format is ever changed, this silently
    returns nothing rather than failing -- see the note in overtone/batch.py.
    """
    root = Path(proofs_dir or PROOFS)
    out = {}
    for p in sorted(root.glob(f"{domain}*.out")):
        name = p.stem.removesuffix("_no-flatten-goal").removesuffix("_flatten-goal")
        out.setdefault(name, p)
    return out


def _coarse_rank(target_merged, candidates):
    """Cheap whole-problem Jaccard, used only to shortlist.

    Not a similarity measure: it unions every axiom's subtrees, so it cannot
    tell a problem with one matching axiom from one with several. It exists
    because the real metric is quadratic in axioms x subtrees and unusably slow
    over a whole domain of LCL-10 encodings.
    """
    ranked = []
    for name, (path, sets) in candidates.items():
        dm = merged(sets)
        j = len(target_merged & dm) / len(target_merged | dm) if dm else 0.0
        ranked.append((j, name, path, sets))
    ranked.sort(key=lambda x: -x[0])
    return ranked


def find_donor(problem: str, domain: str, exclude=(), shortlist: int = 5,
               proofs_dir: Path | None = None):
    """(similarity, donor name, donor proof path) for the best sibling.

    Two stages: coarse Jaccard shortlists, then Twitch's per-axiom structural
    similarity ranks the shortlist.
    """
    target_sets = axiom_sets(problem_path(problem))
    candidates = {}
    for name, path in saved_proofs(domain, proofs_dir).items():
        if name == problem or name in exclude:
            continue
        candidates[name] = (path, axiom_sets(problem_path(name)))

    best = (0.0, None, None)
    for _, name, path, sets in _coarse_rank(merged(target_sets), candidates)[:shortlist]:
        sim = similarity(target_sets, sets)
        if sim > best[0]:
            best = (sim, name, path)
    return best


def baseline(problem: str) -> dict:
    """Recorded no-hint outcomes, so every transfer is reported against one."""
    return batch.screen_baseline(problem)
