"""Learned guidance for equational theorem proving with twee.

    from overtone import Twee, summarise
    tw = Twee()
    r  = tw.run("ROB034-1", budget=1000, label="demo", direction="--flatten-goal")
    print(r.status, r.cpu, r.run_dir)

Layout:

    config     paths and .env
    problems   locating and reading TPTP problems
    terms      TPTP prefix terms: parse, alpha-normalise, symbols, similarity
    runner     running twee; TweeResult; per-run directories
    proofs     parsing twee output
    batch      resumable parallel sweeps and the results.jsonl format
    otter      Otter/EQP equations -> twee $hint terms
    agent      the sketch loop -- isolated, deletable, and NOT imported here

`batch` and `otter` are reachable by full path but not re-exported; `agent` is
never imported by core, so `import overtone` must not pull it in.
"""
from overtone.config import (DATA, LISTS, LOGS, ROOT, RUNS, env, tptp_root,
                             twee_path)
from overtone.problems import (axiom_sets, conjecture, contains_axioms,
                               equations, problem_path, problem_symbols,
                               ueq_scan)
from overtone.proofs import (PROVED, SATURATED, chain_terms, derived_rules,
                             hint_firings, lemmas, parse_status,
                             proof_section, used_lemma_refs)
from overtone.runner import (ALWAYS, BASE_FLAGS, Twee, TweeResult, as_cnf_hint,
                             run, skolemise, summarise, write_problem)
from overtone.terms import (alpha, alpha_key, eq_key, safe_term, similarity,
                            symbols,
                            term, unparse)

__all__ = [
    # config
    "ROOT", "DATA", "LOGS", "RUNS", "LISTS", "env", "tptp_root", "twee_path",
    # problems
    "problem_path", "equations", "problem_symbols", "axiom_sets", "ueq_scan",
    # terms
    "term", "safe_term", "unparse", "alpha", "alpha_key", "symbols", "similarity",
    # runner
    "Twee", "TweeResult", "run", "write_problem", "as_cnf_hint", "skolemise",
    "summarise", "ALWAYS", "BASE_FLAGS",
    # proofs
    "PROVED", "SATURATED", "parse_status", "derived_rules", "lemmas",
    "chain_terms", "used_lemma_refs", "hint_firings",
]
