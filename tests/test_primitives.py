"""Regression tests for bugs this project actually hit.

Every test here corresponds to a specific incident, named in its docstring. The
repo had no tests at all until now, and the selection is deliberately not
"coverage" -- it is the set of mistakes that cost real results: two withdrawn
proofs, three stale-artifact incidents, and a matcher that silently matched
nothing.
"""
import json
from pathlib import Path

import pytest

from overtone import problems
from overtone.agent.dag import Sketch, cost, sibling_diff
from overtone.terms import eq_key


# --------------------------------------------------------------- equation identity

def test_eq_key_ignores_variable_names_and_orientation():
    """The TPTP matcher returned 0 of 29 hits until goal constants were
    normalised. Equation identity has to survive both renaming and flipping."""
    assert eq_key("f(X,Y)", "g(Y)") == eq_key("g(A)", "f(B,A)")
    assert eq_key("a", "b") == eq_key("b", "a")


def test_eq_key_distinguishes_repeated_variables():
    """The predecessor (`ladder.norm`) mapped every variable to `*` and so
    wrongly equated f(X,Y) with f(X,X)."""
    assert eq_key("f(X,Y)", "a") != eq_key("f(X,X)", "a")


# --------------------------------------------------------------- axiom containment

def test_contains_axioms_accepts_identical_and_stronger_theories():
    ok, missing = problems.contains_axioms("RNG029-5", "RNG029-5")
    assert ok and missing == []
    # RNG028-9 has every RNG029-5 axiom plus seven more.
    ok, missing = problems.contains_axioms("RNG028-9", "RNG029-5")
    assert ok and missing == []


def test_contains_axioms_rejects_the_withdrawn_encodings():
    """RNG027-10 and RNG029-10 were briefly claimed as rating-1.00 solves. Their
    re-encodings drop axioms, so lemmas proved from the stronger theory are
    assumptions there, not lemmas."""
    for weaker, n in (("RNG029-10", 4), ("RNG027-10", 3)):
        ok, missing = problems.contains_axioms(weaker, "RNG029-5")
        assert not ok, f"{weaker} must not be treated as containing RNG029-5"
        assert len(missing) == n


# --------------------------------------------------------------- sketch structure

def test_sketch_rejects_unknown_parents_and_cycles():
    with pytest.raises(ValueError, match="unknown parents"):
        Sketch({"x": ("a", "b", ["nope"])})
    with pytest.raises(ValueError, match="cycle"):
        Sketch({"x": ("a", "b", ["y"]), "y": ("c", "d", ["x"])})


def test_sketch_json_round_trip():
    """The runner persists a sketch between iterations; a lossy round trip would
    silently drop edges, which are the thing worth ~3000x."""
    s = Sketch({"a": ("f(X)", "g(X)", []), "b": ("h(X)", "k(X)", ["a"])})
    assert Sketch.from_json(json.loads(json.dumps(s.to_json()))).nodes == s.nodes


def test_layers_are_topological():
    s = Sketch({"a": ("p", "q", []), "b": ("r", "s", ["a"]), "c": ("t", "u", ["a", "b"])})
    seen = set()
    for layer in s.layers():
        for n in layer:
            assert set(s.nodes[n][2]) <= seen
        seen |= set(layer)


# --------------------------------------------------------------- cost accounting

def test_cost_counts_failures_and_every_list():
    """No cost number existed before; the danger in adding one is that it counts
    only successes and flatters the method."""
    verify_rows = [{"cpu": 1.5, "wall": 1.6, "proved": True},
                   {"cpu": 60.0, "wall": 60.1, "proved": False}]
    attempts = [{"cpu": 0.5, "wall": 0.6, "proved": True}]
    c = cost(verify_rows, attempts)
    assert c["cpu"] == 62.0 and c["n_runs"] == 3 and c["n_failed"] == 1


def test_cost_tolerates_missing_fields():
    assert cost([{"proved": True}])["cpu"] == 0.0


# --------------------------------------------------------------- sibling diagnosis

def test_sibling_diff_flags_parents_copied_from_a_mirror():
    """left_moufang_a was given right_moufang_a's parent list verbatim and timed
    out at 300s; the mirrored parent proves it in 1.0s. The diff against the
    working sibling is empty in that situation, so the emptiness itself must be
    reported."""
    m, a = "multiply", "associator"
    nodes = {
        "right_mf": (f"{m}({m}({m}(X,Y),Z),Y)".replace("X", "X"), "rhs1", []),
        "left_mf": ("lhs2", "rhs2", []),
        "right_a": (f"{a}(X,{m}(X,Y),Z)", f"{m}({a}(X,Y,Z),X)", ["right_mf"]),
        "left_a": (f"{a}(X,{m}(Y,X),Z)", f"{m}(X,{a}(X,Y,Z))", ["right_mf"]),
    }
    results = [{"node": "right_a", "proved": True},
               {"node": "left_a", "proved": False}]
    out = sibling_diff(Sketch(nodes), results, "left_a")
    assert out and out[0]["node"] == "right_a"
    assert "note" in out[0], "identical parents on a same-shape sibling must be called out"


def test_sibling_diff_reports_a_real_difference():
    nodes = {
        "p": ("a", "b", []), "q": ("c", "d", []),
        "x": ("f(X,Y)", "g(X,Y)", ["p"]),
        "y": ("f(Y,X)", "g(Y,X)", ["p", "q"]),
    }
    out = sibling_diff(Sketch(nodes), [{"node": "y", "proved": True}], "x")
    assert out[0]["node"] == "y" and out[0]["they_have_you_lack"] == ["q"]


# --------------------------------------------------------------- stale artifacts

def test_verify_carries_prior_results_forward(tmp_path):
    """A resumed run wrote a dag.json containing only the nodes it re-ran, so
    every reader -- the blueprint included -- reported the other 28 as never
    attempted. An empty sketch exercises the merge without invoking the prover."""
    from overtone.agent.dag import verify
    prior = [{"node": "a", "direction": "--flatten-goal", "proved": True,
              "cpu": 1.0, "wall": 1.1, "result": "Unsatisfiable"}]
    out = verify("RNG029-5", Sketch({}), outdir=tmp_path,
                 known=("a",), prior_results=prior)
    assert out["results"] == prior
    assert json.loads((tmp_path / "dag.json").read_text())["results"] == prior


def test_blueprint_never_truncates_away_a_caveat():
    """`right_moufang` carries three TPTP labels, one of them warning that the
    matched problem has a different axiom set. Showing only the first two hid it."""
    from overtone.agent import blueprint
    s = Sketch({"n": ("f(X)", "g(X)", [])})
    annot = {"n": {"tptp": ["A-1", "A-2", "A-10 (different axioms)"]}}
    rows = [{"node": "n", "direction": "--flatten-goal", "proved": True,
             "cpu": 0.1, "result": "Unsatisfiable"}]
    dot = blueprint.to_dot(s, rows, annot=annot)
    assert "different axioms" in dot


def test_blueprint_counts_anything_it_does_drop():
    from overtone.agent import blueprint
    s = Sketch({"n": ("f(X)", "g(X)", [])})
    annot = {"n": {"tptp": ["A-1", "A-2", "A-3", "A-4", "A-5"]}}
    rows = [{"node": "n", "direction": "--flatten-goal", "proved": True,
             "cpu": 0.1, "result": "Unsatisfiable"}]
    dot = blueprint.to_dot(s, rows, annot=annot)
    assert "more)" in dot, "silently dropping labels is what the rule forbids"


# --------------------------------------------------------------- sketch diff

def test_diff_reports_each_kind_of_edit():
    from overtone.agent.dag import diff
    a = Sketch({"p": ("a", "b", []), "gone": ("c", "d", []),
                "x": ("f(X)", "g(X)", ["p"])})
    b = Sketch({"p": ("a", "b", []), "new": ("e", "h", []),
                "x": ("f(X)", "k(X)", ["p", "new"])})
    d = diff(a, b)
    assert d["added"] == ["new"] and d["removed"] == ["gone"]
    assert d["restated"][0]["node"] == "x"
    assert d["reparented"][0] == {"node": "x", "gained": ["new"], "lost": []}
    assert d["n_edits"] == 4


def test_diff_ignores_alpha_renaming_but_not_restatement():
    """An alpha-rename is not an edit. A genuine restatement is -- our
    left_moufang drifted from RNG028-7's conjecture by exactly one rewrite."""
    from overtone.agent.dag import diff
    a = Sketch({"n": ("f(X,Y)", "g(X)", [])})
    same = Sketch({"n": ("f(A,B)", "g(A)", [])})
    other = Sketch({"n": ("f(X,X)", "g(X)", [])})
    assert diff(a, same)["restated"] == []
    assert diff(a, other)["restated"] != []


def test_to_html_timeline_embeds_every_step():
    from overtone.agent import blueprint
    a = Sketch({"p": ("a", "b", [])})
    b = Sketch({"p": ("a", "b", []), "q": ("c", "d", ["p"])})
    html = blueprint.to_html(b, [], timeline=[
        {"label": "one", "sketch": a, "results": (), "note": "start"},
        {"label": "two", "sketch": b, "results": (), "note": "added q"}])
    assert html.count('<div class="step"') == 2
    assert 'class="stepchip"' in html and "renderDiff" in html


# --------------------------------------------------------------- self-proof guard

def test_conjecture_normalises_skolem_constants():
    """TPTP states goals with lowercase constants where a sketch uses variables.
    Comparing them raw finds nothing -- silently -- which is how the TPTP matcher
    first returned 0 of 29 hits."""
    lhs, rhs = problems.conjecture(problems.problem_path("RNG025-5"))
    assert "VX" in lhs or "VY" in lhs or "VZ" in lhs, "goal constants must become variables"
    raw = problems.conjecture(problems.problem_path("RNG025-5"), as_variables=False)
    assert eq_key(lhs, rhs) != eq_key(*raw)


def test_library_never_supplies_a_target_its_own_conjecture():
    """The sketch contains nodes that ARE target conjectures -- middle_moufang is
    RNG029-5. Handing a problem its own statement proves it in 0.0s and says
    nothing; the work belongs to the library phase."""
    import importlib.util
    from overtone.agent.pipeline import _states
    spec = importlib.util.spec_from_file_location("_rd", "scripts/rng_dag.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    s = mod.SKETCH
    assert [n for n in s.nodes if _states(s, n, "RNG029-5")] == ["middle_moufang"]
    assert [n for n in s.nodes if _states(s, n, "RNG027-8")] == ["right_moufang_a"]
    # A target the library does not state keeps everything.
    assert [n for n in s.nodes if _states(s, n, "RNG029-6")] == []
