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


# --------------------------------------------------------------- the loop

def test_apply_is_pure_and_rejects_unknown_ops():
    from overtone.agent.loop import apply
    s = Sketch({"a": ("f(X)", "g(X)", []), "b": ("h(X)", "k(X)", ["a"])})
    s2 = apply(s, {"op": "add_node", "name": "c", "lhs": "p", "rhs": "q",
                   "parents": ["a"]})
    assert sorted(s.nodes) == ["a", "b"], "the input sketch must not mutate"
    assert sorted(s2.nodes) == ["a", "b", "c"]
    with pytest.raises(ValueError, match="unknown op"):
        apply(s, {"op": "delete_everything"})


def test_remove_node_also_drops_the_edges_into_it():
    from overtone.agent.loop import apply
    s = Sketch({"a": ("f", "g", []), "b": ("h", "k", ["a"])})
    s2 = apply(s, {"op": "remove_node", "name": "a"})
    assert s2.nodes["b"][2] == [], "a dangling parent would fail validation"


def test_restate_refuses_to_author_a_tptp_node_statement():
    """Our left_moufang states ((xy)x)z where RNG028-7 states (x(yx))z. Under
    this guard that drift cannot be expressed, only copied."""
    from overtone.agent.loop import apply
    s = Sketch({"n": ("f(X)", "g(X)", [])})
    annot = {"n": {"tptp": ["RNG028-7"]}}
    with pytest.raises(ValueError, match="from_problem"):
        apply(s, {"op": "restate", "name": "n", "lhs": "a", "rhs": "b"},
              annot=annot)
    out = apply(s, {"op": "restate", "name": "n", "from_problem": "RNG028-7"},
                annot=annot)
    assert out.nodes["n"][0] != "f(X)", "the statement must come from the problem"


def test_scripted_replay_reaches_the_committed_sketch():
    """If the loop cannot reproduce a trajectory a human already walked, it will
    not find a new one. Four edits, 25 nodes to 29."""
    import importlib.util
    from overtone.agent.loop import apply
    spec = importlib.util.spec_from_file_location("_loop", "scripts/loop.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    target = mod.load_sketch(Path("scripts/rng_dag.py"))
    s = mod.rewind(target)
    assert len(s.nodes) == 25
    for step in mod.SESSION_EDITS:
        for act in step:
            s = apply(s, act)
    assert s.nodes == target.nodes


# --------------------------------------------------------------- llm adapters

def test_both_providers_expose_the_same_action_set():
    from overtone.agent.llm import tool_schemas
    from overtone.agent.loop import ACTIONS
    a = {t["name"] for t in tool_schemas("anthropic")}
    o = {t["function"]["name"] for t in tool_schemas("openai")}
    assert a == o, "a model must see the same actions whichever provider it is"
    assert a <= set(ACTIONS), "the schema must not offer an op apply() rejects"


def test_parses_tool_calls_from_either_wire_format():
    """The parse path is where a provider difference silently drops actions."""
    from overtone.agent.llm import LLMAgent
    an = LLMAgent.__new__(LLMAgent)
    an.provider = "anthropic"
    got = an._parse({"content": [
        {"type": "text", "text": "ignore me"},
        {"type": "tool_use", "name": "set_parents",
         "input": {"name": "n", "parents": ["p"]}}]})
    assert got == [{"op": "set_parents", "name": "n", "parents": ["p"]}]

    oa = LLMAgent.__new__(LLMAgent)
    oa.provider = "openai"
    got = oa._parse({"choices": [{"message": {"tool_calls": [
        {"function": {"name": "set_parents",
                      "arguments": '{"name": "n", "parents": ["p"]}'}}]}}]})
    assert got == [{"op": "set_parents", "name": "n", "parents": ["p"]}]


def test_unknown_and_malformed_tool_calls_do_not_crash_the_loop():
    from overtone.agent.llm import LLMAgent
    a = LLMAgent.__new__(LLMAgent)
    a.provider = "openai"
    assert a._parse({"choices": [{"message": {"tool_calls": [
        {"function": {"name": "drop_database", "arguments": "{}"}},
        {"function": {"name": "add_node", "arguments": "not json"}}]}}]}) == []


def test_system_prompt_carries_the_measured_rules():
    """A model's priors here are wrong in specific, paid-for ways: it would add
    lemmas when a node is slow and raise budgets instead of subdividing."""
    from overtone.agent.llm import SYSTEM
    for phrase in ("DIAGNOSTIC", "never ask for more time", "WRONG PARENTS",
                   "restate(from_problem", "SIBLING"):
        assert phrase in SYSTEM


# --------------------------------------------------------------- donor ranking

def test_goal_similarity_is_exact_for_the_same_theorem():
    """LAT141-1 states LAT138-1's conjecture verbatim over different axioms.
    Axiom ranking picks LAT139-1, a different theorem whose lemmas all
    transferred and none of which helped."""
    from overtone.agent.donors import goal_similarity
    assert goal_similarity("LAT138-1", "LAT141-1") == 1.0
    assert goal_similarity("LAT138-1", "LAT139-1") < 1.0


def test_ranking_modes_are_distinct_and_validated():
    from overtone.agent.donors import RANKINGS, rank_donors
    with pytest.raises(ValueError, match="rank_by"):
        rank_donors("RNG029-5", "RNG", rank_by="vibes")
    assert set(RANKINGS) == {"axioms", "goal", "both"}


def test_goal_ranking_alone_can_pick_an_unsound_donor():
    """Goal relatedness says nothing about soundness. For RNG029-5 it puts
    RNG027-10 first -- a withdrawn problem whose axiom set is weaker -- so
    containment still has to gate the transfer."""
    from overtone.agent.donors import goal_similarity
    assert goal_similarity("RNG029-5", "RNG027-10") > 0
    ok, missing = problems.contains_axioms("RNG029-5", "RNG027-10")
    assert not ok and missing, "the sound-looking goal match is not sound"


# --------------------------------------------------------------- CLI hygiene

def test_every_script_has_a_safe_help():
    """`open_rng_baseline.py --help` started a 16-job, 4000-second sweep, because
    the script had no argument parsing at all. A CLI whose only mode is to burn
    CPU-hours must be able to say so without doing it."""
    import subprocess
    import sys
    for script in sorted(Path("scripts").glob("*.py")):
        r = subprocess.run([sys.executable, str(script), "--help"],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"{script.name} --help failed: {r.stderr[:200]}"
        assert "usage:" in r.stdout.lower(), f"{script.name} has no argument parser"


# --------------------------------------------------------------- run artifacts

def test_write_for_run_never_raises(tmp_path):
    """A run that cost CPU-hours must not lose its result to a rendering error.
    A sketch whose node names are hostile to the renderer still returns cleanly."""
    from overtone.agent import blueprint
    s = Sketch({'weird "name"': ("f(X)", "g(X)", [])})
    out = blueprint.write_for_run(s, [], tmp_path, title="t", quiet=True)
    assert isinstance(out, list)          # empty or not, it returns


def test_write_index_lists_runs_and_names_them_by_kind(tmp_path):
    """A theory run's `host` is the problem its library came from, not what the
    run is about; showing it made a family run look like a single-problem run."""
    from overtone.agent import blueprint
    (tmp_path / "theory" / "rng_dag").mkdir(parents=True)
    (tmp_path / "theory" / "rng_dag" / "blueprint.html").write_text("x")
    (tmp_path / "theory" / "rng_dag" / "theory.json").write_text(json.dumps(
        {"host": "RNG029-5", "n_proved": 12, "n_targets": 14,
         "library": {"n_proved": 29, "n_nodes": 29, "cost": {"cpu": 2197.0}}}))
    (tmp_path / "prove" / "RNG029-5").mkdir(parents=True)
    (tmp_path / "prove" / "RNG029-5" / "blueprint.html").write_text("x")
    (tmp_path / "prove" / "RNG029-5" / "problem.json").write_text(json.dumps(
        {"problem": "RNG029-5", "proved": True, "n_proved": 29, "n_nodes": 29,
         "cost": {"cpu": 2146.4, "n_runs": 60}}))

    dest = blueprint.write_index(
        [tmp_path / "theory", tmp_path / "prove"], tmp_path / "index.html")
    html = dest.read_text()
    assert "rng_dag" in html and "RNG029-5" in html
    assert "12/14 targets" in html and "proved" in html


def test_write_index_is_fine_with_no_runs(tmp_path):
    from overtone.agent import blueprint
    dest = blueprint.write_index([tmp_path / "nope"], tmp_path / "i.html")
    assert "No runs" in dest.read_text()


# --------------------------------------------------------------- the ledger

def _write(tmp, text):
    p = tmp / "in.p"
    p.write_text(text)
    return p


def test_ledger_key_is_over_bytes_flags_and_build(tmp_path, monkeypatch):
    """Identity must be the exact question asked, not its meaning."""
    from overtone.agent import ledger
    monkeypatch.setattr("overtone.config.tptp_root", lambda: Path("/tptp"))
    a = _write(tmp_path, "cnf(x,axiom,f(A)=g(A)).\n")
    k = ledger.key_for(a, ["--flatten-goal"], "/bin/twee")
    assert k == ledger.key_for(a, ["--flatten-goal"], "/bin/twee")
    assert k != ledger.key_for(a, ["--no-flatten-goal"], "/bin/twee")
    assert k != ledger.key_for(a, ["--flatten-goal"], "/other/twee")
    monkeypatch.setenv("TWEE_STEPS_PER_SECOND", "999")
    assert k != ledger.key_for(a, ["--flatten-goal"], "/bin/twee")


def test_ledger_treats_reordered_axioms_as_a_different_run(tmp_path, monkeypatch):
    """twee's search depends on the order rules enter the system, so a reordered
    axiom list is a different search and may have a different outcome. Any
    semantic key would collapse these and skip a run that could have succeeded."""
    from overtone.agent import ledger
    monkeypatch.setattr("overtone.config.tptp_root", lambda: Path("/tptp"))
    one = tmp_path / "a.p"
    two = tmp_path / "b.p"
    one.write_text("cnf(p,axiom,f(A)=g(A)).\ncnf(q,axiom,h(A)=k(A)).\n")
    two.write_text("cnf(q,axiom,h(A)=k(A)).\ncnf(p,axiom,f(A)=g(A)).\n")
    assert (ledger.key_for(one, ["-d"], "/t")
            != ledger.key_for(two, ["-d"], "/t")), "reordering must not be reused"


def test_ledger_reuse_is_monotone_in_budget(tmp_path):
    """A proof carries to any larger budget; a timeout only answers questions at
    or below the budget that produced it."""
    from overtone.agent import ledger
    led = tmp_path / "l.jsonl"
    ledger.record("K", {"result": "Timeout", "proved": False, "cpu": 300.0}, 300,
                  ledger=led)
    assert ledger.lookup("K", 300, ledger=led) is not None   # same budget: answered
    assert ledger.lookup("K", 200, ledger=led) is not None   # less: answered
    assert ledger.lookup("K", 900, ledger=led) is None       # more: unanswered
    ledger.record("K", {"result": "Unsatisfiable", "proved": True, "cpu": 12.0},
                  300, ledger=led)
    assert ledger.lookup("K", 9999, ledger=led)["proved"]    # a proof always carries


def test_ledger_survives_a_torn_line(tmp_path):
    from overtone.agent import ledger
    led = tmp_path / "l.jsonl"
    ledger.record("K", {"result": "Unsatisfiable", "proved": True}, 60, ledger=led)
    with open(led, "a") as fh:
        fh.write('{"key": "trunc"')          # a killed writer
    assert ledger.load(led)["K"]["proved"]


def test_verify_runs_a_node_end_to_end_with_a_stubbed_prover(tmp_path, monkeypatch):
    """A stale job tuple reached a live run because every job went through a
    process pool, where no stub can follow it. At workers=1 the work is inline,
    so this exercises the real _job signature."""
    from overtone import runner
    from overtone.agent import dag

    calls = []

    class FakeResult:
        status, proved, cpu, wall, output = "Unsatisfiable", True, 1.5, 1.6, "ok"

    def fake_run(path, flags, budget, **kw):
        calls.append((Path(path).name, tuple(flags), budget))
        return FakeResult()

    monkeypatch.setattr(runner, "run", fake_run)
    s = Sketch({"a": ("f(X)", "g(X)", []), "b": ("h(X)", "k(X)", ["a"])})
    out = dag.verify("RNG029-5", s, outdir=tmp_path, budget=7, workers=1,
                     ledger=tmp_path / "l.jsonl")
    assert out["n_proved"] == 2, out["missing"]
    assert {r["node"] for r in out["results"]} == {"a", "b"}
    assert all(r["cpu"] == 1.5 and r["wall"] == 1.6 for r in out["results"])
    # Two nodes, ONE direction each: a node needs one direction to prove, and
    # running the other costs its whole budget while the layer waits on it.
    assert len(calls) == 2, calls


def test_verify_reuses_a_recorded_run_instead_of_repeating_it(tmp_path, monkeypatch):
    """rng033_goal was verified standalone at 300s, failed, and the next
    iteration re-ran the identical configuration at 900s."""
    from overtone import runner
    from overtone.agent import dag

    n = [0]

    class FakeResult:
        status, proved, cpu, wall, output = "Unsatisfiable", True, 2.0, 2.1, "ok"

    def fake_run(path, flags, budget, **kw):
        n[0] += 1
        return FakeResult()

    monkeypatch.setattr(runner, "run", fake_run)
    led = tmp_path / "l.jsonl"
    s = Sketch({"a": ("f(X)", "g(X)", [])})
    dag.verify("RNG029-5", s, outdir=tmp_path, budget=7, workers=1, ledger=led)
    first = n[0]
    out = dag.verify("RNG029-5", s, outdir=tmp_path, budget=7, workers=1, ledger=led)
    assert n[0] == first, "an identical question must not reach the prover twice"
    assert all(r.get("reused") for r in out["results"])
    dag.verify("RNG029-5", s, outdir=tmp_path, budget=7, workers=1, ledger=led,
               reuse=False)
    assert n[0] > first, "--rerun must force the prover"


def test_standalone_retry_does_not_overwrite_the_parented_run(tmp_path, monkeypatch):
    """The retry wrote the same {node}.{direction} tag, so it destroyed the
    parented run's input and output -- the artifact a diagnosis needs. Both
    RNG033-8 iterations lost it, and a comparison of the two searches silently
    compared two copies of the standalone run instead."""
    from overtone import runner
    from overtone.agent import dag

    class R:
        def __init__(self, ok):
            self.proved = ok
            self.status = "Unsatisfiable" if ok else "Timeout"
            self.cpu = self.wall = 1.0
            self.output = "x"

    # the parent must succeed, or the child is blocked and never runs at all
    monkeypatch.setattr(runner, "run",
                        lambda path, *a, **k: R(Path(path).name.startswith("p.")))
    s = Sketch({"p": ("a", "b", []), "n": ("f(X)", "g(X)", ["p"])})
    dag.verify("RNG029-5", s, outdir=tmp_path, budget=1, workers=1,
               ledger=tmp_path / "l.jsonl")
    inputs = sorted(tmp_path.glob("n.*.p"))
    # The parented run (one supplied lemma) and the standalone retry (none) are
    # different questions, so they must be different files and both must survive.
    assert len(inputs) == 4, [f.name for f in inputs]   # 2 directions x 2 scopes
    with_parent = [f for f in inputs if "parent" in f.read_text()]
    without = [f for f in inputs if "parent" not in f.read_text()]
    assert len(with_parent) == 2 and len(without) == 2, \
        "the retry must not overwrite the parented run it is retrying"


# --------------------------------------------------------------- loop memory

def test_sketch_digest_ignores_node_order_but_not_parent_order():
    """Node order does not reach twee -- layers() sorts -- but parent order sets
    the order equations enter the prover, and so the search."""
    a = Sketch({"x": ("f", "g", ["p", "q"]), "p": ("a", "b", []), "q": ("c", "d", [])})
    b = Sketch({"p": ("a", "b", []), "q": ("c", "d", []), "x": ("f", "g", ["p", "q"])})
    c = Sketch({"p": ("a", "b", []), "q": ("c", "d", []), "x": ("f", "g", ["q", "p"])})
    assert a.digest() == b.digest()
    assert a.digest() != c.digest()


def test_loop_stops_when_an_agent_goes_in_a_circle(tmp_path, monkeypatch):
    """An agent that adds a node one iteration and removes it the next makes two
    states alternate forever. Each is 'new' to the node ledger, which remembers
    invocations rather than sketches, so the loop needs its own memory."""
    from overtone import runner
    from overtone.agent.loop import ScriptedAgent, run_loop
    from overtone.agent.pipeline import Budget

    class Fail:
        status, proved, cpu, wall, output = "Timeout", False, 0.1, 0.1, "x"

    monkeypatch.setattr(runner, "run", lambda *a, **k: Fail())
    s = Sketch({"p": ("a", "b", [])})
    # add q, remove q, add q ... -> iteration 2 revisits iteration 0's sketch
    script = [[{"op": "add_node", "name": "q", "lhs": "c", "rhs": "d"}],
              [{"op": "remove_node", "name": "q"}],
              [{"op": "add_node", "name": "q", "lhs": "c", "rhs": "d"}]]
    out = run_loop("RNG029-5", s, ScriptedAgent(script), outdir=tmp_path,
                   budget=Budget(node=1, final=1, workers=1), max_iterations=6)
    assert "cycle" in out["stop_reason"], out["stop_reason"]
    assert out["iterations"] == 2, "it should stop on revisiting, not run on"


def test_loop_stops_when_edits_change_nothing(tmp_path, monkeypatch):
    from overtone import runner
    from overtone.agent.loop import ScriptedAgent, run_loop
    from overtone.agent.pipeline import Budget

    class Fail:
        status, proved, cpu, wall, output = "Timeout", False, 0.1, 0.1, "x"

    monkeypatch.setattr(runner, "run", lambda *a, **k: Fail())
    s = Sketch({"p": ("a", "b", [])})
    out = run_loop("RNG029-5", s,
                   ScriptedAgent([[{"op": "set_parents", "name": "p", "parents": []}]]),
                   outdir=tmp_path, budget=Budget(node=1, final=1, workers=1))
    assert "unchanged" in out["stop_reason"]


def test_state_carries_prior_iterations(tmp_path, monkeypatch):
    """An agent cannot avoid repeating an edit it cannot see."""
    from overtone import runner
    from overtone.agent.loop import State, run_loop
    from overtone.agent.pipeline import Budget

    class Fail:
        status, proved, cpu, wall, output = "Timeout", False, 0.1, 0.1, "x"

    monkeypatch.setattr(runner, "run", lambda *a, **k: Fail())
    seen_histories = []

    class Watcher:
        def act(self, state: State):
            seen_histories.append(len(state.history))
            return [{"op": "add_node", "name": f"n{state.iteration}",
                     "lhs": "c", "rhs": "d"}]

    run_loop("RNG029-5", Sketch({"p": ("a", "b", [])}), Watcher(),
             outdir=tmp_path, budget=Budget(node=1, final=1, workers=1),
             max_iterations=3)
    assert seen_histories == [0, 1, 2], seen_histories


def test_a_proved_node_does_not_pay_for_the_other_direction(tmp_path, monkeypatch):
    """The losing arm sets a layer's wall time. right_moufang_a reported 0.5s
    while its layer waited 300.3s on the direction that could not prove it."""
    from overtone import runner
    from overtone.agent import dag

    seen = []

    class R:
        def __init__(s, ok):
            s.proved = ok
            s.status = "Unsatisfiable" if ok else "Timeout"
            s.cpu = s.wall = 0.1 if ok else 300.0
            s.output = "x"

    def fake(path, flags, budget, **kw):
        seen.append(flags[-1])
        return R(flags[-1] == "--flatten-goal")     # only one direction works

    monkeypatch.setattr(runner, "run", fake)
    s = Sketch({"n": ("f(X)", "g(X)", [])})
    out = dag.verify("RNG029-5", s, outdir=tmp_path, budget=300, workers=1,
                     ledger=tmp_path / "l.jsonl",
                     prefer={"n": "--flatten-goal"})
    assert seen == ["--flatten-goal"], seen
    assert out["n_proved"] == 1
    assert sum(r["cpu"] for r in out["results"]) == 0.1, "no losing-arm cost"


def test_a_failing_node_still_tries_both_directions(tmp_path, monkeypatch):
    """Short-circuiting must not hide a direction that would have worked."""
    from overtone import runner
    from overtone.agent import dag

    seen = []

    class Fail:
        status, proved, cpu, wall, output = "Timeout", False, 1.0, 1.0, "x"

    def fake(path, flags, budget, **kw):
        seen.append(flags[-1])
        return Fail()

    monkeypatch.setattr(runner, "run", fake)
    dag.verify("RNG029-5", Sketch({"n": ("f(X)", "g(X)", [])}), outdir=tmp_path,
               budget=1, workers=1, ledger=tmp_path / "l.jsonl")
    assert set(seen) == {"--flatten-goal", "--no-flatten-goal"}, seen


def test_racing_directions_cancels_the_loser(tmp_path, monkeypatch):
    """Both directions start together and the loser is stopped the moment the
    winner proves, so a layer waits on the winner rather than on the arm that
    could never succeed. Asserted on returned rows, which survive the fork that
    a shared counter would not."""
    import time as _time
    from overtone import runner
    from overtone.agent import dag

    class R:
        def __init__(s, ok, cpu):
            s.proved, s.cpu, s.wall, s.output = ok, cpu, cpu, "x"
            s.status = "Unsatisfiable" if ok else "Timeout"

    def fake(path, flags, budget, cancel=None, **kw):
        if flags[-1] == "--flatten-goal":
            return R(True, 0.1)                       # the winner, immediately
        for _ in range(200):                          # the loser, watching cancel
            if cancel is not None and cancel.is_set():
                r = R(False, 0.5)
                r.status = "Cancelled"
                return r
            _time.sleep(0.01)
        return R(False, float(budget))

    monkeypatch.setattr(runner, "run", fake)
    j = {"problem": "RNG029-5", "node": "n", "lhs": "f(X)", "rhs": "g(X)",
         "eqs": [], "channel": "axioms",
         "directions": ["--no-flatten-goal", "--flatten-goal"],
         "budget": 300, "outdir": str(tmp_path), "binary": "/bin/true",
         "reuse": False, "ledger": str(tmp_path / "l.jsonl")}
    started = _time.monotonic()
    rows = dag._node_job(j)
    elapsed = _time.monotonic() - started

    assert any(r["proved"] for r in rows), rows
    assert not any(r.get("result") == "Cancelled" for r in rows), \
        "a cancelled run answered nothing and is not a result"
    assert elapsed < 2.0, f"the layer waited on the loser ({elapsed:.1f}s)"


def test_a_cancelled_run_is_never_recorded(tmp_path, monkeypatch):
    """Recording one would let reuse skip a question that was never resolved."""
    from overtone import runner
    from overtone.agent import dag, ledger

    class Cancelled:
        status, proved, cpu, wall, output = "Cancelled", False, 0.4, 0.4, "x"

    monkeypatch.setattr(runner, "run", lambda *a, **k: Cancelled())
    led = tmp_path / "l.jsonl"
    dag._job({"problem": "RNG029-5", "node": "n", "lhs": "f(X)", "rhs": "g(X)",
              "eqs": [], "channel": "axioms", "direction": "--flatten-goal",
              "budget": 60, "outdir": str(tmp_path), "binary": "/bin/true",
              "reuse": False, "ledger": str(led)})
    assert ledger.load(led) == {}, "a cancelled run must leave no record"
