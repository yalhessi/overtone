"""Choosing which solved problem's proof to transfer from.

Two rankings, because they measure different things and each is right somewhere.

**Axiom similarity** asks whether the donor's theory is the target's theory. It
is what makes a transfer *sound* -- a lemma proved from one axiom set is a
theorem of another only if that other is at least as strong -- and it is the
right question when you want a library over a family.

**Goal relatedness** asks whether the donor's conjecture is a fact the target
needs. That is what actually decided the RNG result: RNG027-5 proves right
Moufang, which is exactly what the other twelve problems require, and its proof
carried the four lemmas that flipped them. Axiom similarity cannot see this --
two problems can share every axiom and prove unrelated things, which is why it
picked plausible donors that carried nothing for GRP, LAT and COL:

    GRP673-10   donor at 0.817 axiom similarity   177/260 lemmas held, none helped
    LAT138-1    donor at 0.930                    18/20 held, none helped
    COL003-1    donor at 0.897                    2/13 held

Neither subsumes the other. `rank_by="both"` multiplies them, which demands a
donor be strong on each -- the RNG case was.
"""
from pathlib import Path

from overtone import batch, config
from overtone.problems import axiom_sets, goal_set, problem_path
from overtone.terms import merged, similarity

PROOFS = config.LOGS / "screen" / "proofs"
RANKINGS = ("axioms", "goal", "both")


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


def goal_similarity(target: str, donor: str) -> float:
    """Jaccard over the two conjectures' alpha-normalised subtrees.

    Deliberately structural rather than exact: the useful case is a donor whose
    goal is *a lemma of* the target's proof, not one whose goal is identical, so
    this rewards shared shape rather than equality.
    """
    a = goal_set(problem_path(target))
    b = goal_set(problem_path(donor))
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def rank_donors(problem: str, domain: str, exclude=(), shortlist: int = 5,
                proofs_dir: Path | None = None, rank_by: str = "axioms"):
    """Every candidate donor, scored and sorted. `find_donor` returns its head.

    Exposed because the score is a judgement worth inspecting: the whole
    cross-theory failure was a donor that scored 0.817 and carried nothing.
    """
    if rank_by not in RANKINGS:
        raise ValueError(f"rank_by must be one of {RANKINGS}")
    target_sets = axiom_sets(problem_path(problem))
    candidates = {}
    for name, path in saved_proofs(domain, proofs_dir).items():
        if name == problem or name in exclude:
            continue
        candidates[name] = (path, axiom_sets(problem_path(name)))
    if not candidates:
        return []

    # The coarse pass only shortlists for the expensive axiom metric. Goal
    # scoring is cheap -- two conjectures -- so it runs over every candidate and
    # is not filtered by an axiom-based prefilter that would beg the question.
    shortlisted = {name: (path, sets) for _, name, path, sets
                   in _coarse_rank(merged(target_sets), candidates)[:shortlist]}

    rows = []
    for name, (path, sets) in candidates.items():
        ax = similarity(target_sets, sets) if name in shortlisted else 0.0
        gl = goal_similarity(problem, name)
        score = {"axioms": ax, "goal": gl, "both": ax * gl}[rank_by]
        rows.append({"donor": name, "path": path, "score": score,
                     "axioms": round(ax, 3), "goal": round(gl, 3)})
    rows.sort(key=lambda r: -r["score"])
    return rows


def find_donor(problem: str, domain: str, exclude=(), shortlist: int = 5,
               proofs_dir: Path | None = None, rank_by: str = "axioms"):
    """(score, donor name, donor proof path) for the best sibling.

    `rank_by="axioms"` is the default and unchanged, so every recorded result
    still reproduces. Use "goal" when you want a donor whose conjecture is a fact
    the target needs, and "both" to demand it be strong on each.
    """
    rows = rank_donors(problem, domain, exclude, shortlist, proofs_dir, rank_by)
    if not rows or rows[0]["score"] <= 0:
        return (0.0, None, None)
    top = rows[0]
    return (top["score"], top["donor"], top["path"])


def baseline(problem: str) -> dict:
    """Recorded no-hint outcomes, so every transfer is reported against one."""
    return batch.screen_baseline(problem)
