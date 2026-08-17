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
        Sketch({"x": ("additive_identity", "add(X,X)", ["nope"])})
    with pytest.raises(ValueError, match="cycle"):
        Sketch({"x": ("additive_identity", "add(X,X)", ["y"]), "y": ("multiply(X,X)", "add(Y,Y)", ["x"])})


def test_sketch_json_round_trip():
    """The runner persists a sketch between iterations; a lossy round trip would
    silently drop edges, which are the thing worth ~3000x."""
    s = Sketch({"a": ("multiply(X,X)", "add(X,X)", []), "b": ("commutator(X,X)", "additive_identity", ["a"])})
    assert Sketch.from_json(json.loads(json.dumps(s.to_json()))).nodes == s.nodes


def test_layers_and_topological_order_both_follow_the_edges():
    """`layers()` is blueprint layout now and `topological()` is the schedule,
    but a parent must precede its child in either or both are wrong."""
    s = Sketch({"a": ("associator(X,X,X)", "multiply(Y,Y)", []), "b": ("multiply(X,Y)", "multiply(Y,X)", ["a"]), "c": ("add(X,Y)", "add(Y,X)", ["a", "b"])})
    seen = set()
    for layer in s.layers():
        for n in layer:
            assert set(s.nodes[n][2]) <= seen
        seen |= set(layer)

    seen = set()
    for n in s.topological():
        assert set(s.nodes[n][2]) <= seen
        seen.add(n)
    assert sorted(s.topological()) == sorted(s.nodes)


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
        "p": ("additive_identity", "add(X,X)", []), "q": ("multiply(X,X)", "add(Y,Y)", []),
        "x": ("multiply(X,Y)", "add(X,Y)", ["p"]),
        "y": ("multiply(Y,X)", "add(Y,X)", ["p", "q"]),
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
    s = Sketch({"n": ("multiply(X,X)", "add(X,X)", [])})
    annot = {"n": {"tptp": ["A-1", "A-2", "A-10 (different axioms)"]}}
    rows = [{"node": "n", "direction": "--flatten-goal", "proved": True,
             "cpu": 0.1, "result": "Unsatisfiable"}]
    dot = blueprint.to_dot(s, rows, annot=annot)
    assert "different axioms" in dot


def test_blueprint_counts_anything_it_does_drop():
    from overtone.agent import blueprint
    s = Sketch({"n": ("multiply(X,X)", "add(X,X)", [])})
    annot = {"n": {"tptp": ["A-1", "A-2", "A-3", "A-4", "A-5"]}}
    rows = [{"node": "n", "direction": "--flatten-goal", "proved": True,
             "cpu": 0.1, "result": "Unsatisfiable"}]
    dot = blueprint.to_dot(s, rows, annot=annot)
    assert "more)" in dot, "silently dropping labels is what the rule forbids"


# --------------------------------------------------------------- sketch diff

def test_diff_reports_each_kind_of_edit():
    from overtone.agent.dag import diff
    a = Sketch({"p": ("additive_identity", "add(X,X)", []), "gone": ("multiply(X,X)", "add(Y,Y)", []),
                "x": ("multiply(X,X)", "add(X,X)", ["p"])})
    b = Sketch({"p": ("additive_identity", "add(X,X)", []), "new": ("commutator(X,Y)", "commutator(Y,X)", []),
                "x": ("multiply(X,X)", "additive_identity", ["p", "new"])})
    d = diff(a, b)
    assert d["added"] == ["new"] and d["removed"] == ["gone"]
    assert d["restated"][0]["node"] == "x"
    assert d["reparented"][0] == {"node": "x", "gained": ["new"], "lost": []}
    assert d["n_edits"] == 4


def test_diff_ignores_alpha_renaming_but_not_restatement():
    """An alpha-rename is not an edit. A genuine restatement is -- our
    left_moufang drifted from RNG028-7's conjecture by exactly one rewrite."""
    from overtone.agent.dag import diff
    a = Sketch({"n": ("multiply(X,Y)", "add(X,X)", [])})
    same = Sketch({"n": ("multiply(A,B)", "add(A,A)", [])})
    other = Sketch({"n": ("multiply(X,X)", "add(X,X)", [])})
    assert diff(a, same)["restated"] == []
    assert diff(a, other)["restated"] != []


def test_to_html_timeline_embeds_every_step():
    from overtone.agent import blueprint
    a = Sketch({"p": ("additive_identity", "add(X,X)", [])})
    b = Sketch({"p": ("additive_identity", "add(X,X)", []), "q": ("multiply(X,X)", "add(Y,Y)", ["p"])})
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
    s = Sketch({"a": ("multiply(X,X)", "add(X,X)", []), "b": ("commutator(X,X)", "additive_identity", ["a"])})
    s2 = apply(s, {"op": "add_node", "name": "c", "lhs": "associator(X,X,X)", "rhs": "multiply(Y,Y)",
                   "parents": ["a"]})
    assert sorted(s.nodes) == ["a", "b"], "the input sketch must not mutate"
    assert sorted(s2.nodes) == ["a", "b", "c"]
    with pytest.raises(ValueError, match="unknown op"):
        apply(s, {"op": "delete_everything"})


def test_remove_node_also_drops_the_edges_into_it():
    from overtone.agent.loop import apply
    s = Sketch({"a": ("f", "g", []), "b": ("commutator(Y,X)", "k", ["a"])})
    s2 = apply(s, {"op": "remove_node", "name": "a"})
    assert s2.nodes["b"][2] == [], "a dangling parent would fail validation"


def test_restate_refuses_to_author_a_tptp_node_statement():
    """Our left_moufang states ((xy)x)z where RNG028-7 states (x(yx))z. Under
    this guard that drift cannot be expressed, only copied."""
    from overtone.agent.loop import apply
    s = Sketch({"n": ("multiply(X,X)", "add(X,X)", [])})
    annot = {"n": {"tptp": ["RNG028-7"]}}
    with pytest.raises(ValueError, match="from_problem"):
        apply(s, {"op": "restate", "name": "n", "lhs": "additive_identity", "rhs": "add(X,X)"},
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
    s = Sketch({'weird "name"': ("multiply(X,X)", "add(X,X)", [])})
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
    s = Sketch({"a": ("multiply(X,X)", "add(X,X)", []), "b": ("commutator(X,X)", "additive_identity", ["a"])})
    out = dag.verify("RNG029-5", s, outdir=tmp_path, budget=7, workers=1,
                     ledger=tmp_path / "l.jsonl")
    assert out["n_proved"] == 2, out["missing"]
    assert {r["node"] for r in out["results"]} == {"a", "b"}
    assert all(r["cpu"] == 1.5 and r["wall"] == 1.6 for r in out["results"])
    # Two nodes, ONE direction each: a node needs one direction to prove, and
    # running the other costs its whole budget for an answer already in hand.
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
    s = Sketch({"a": ("multiply(X,X)", "add(X,X)", [])})
    dag.verify("RNG029-5", s, outdir=tmp_path, budget=7, workers=1, ledger=led)
    first = n[0]
    out = dag.verify("RNG029-5", s, outdir=tmp_path, budget=7, workers=1, ledger=led)
    assert n[0] == first, "an identical question must not reach the prover twice"
    assert all(r.get("reused") for r in out["results"])
    dag.verify("RNG029-5", s, outdir=tmp_path, budget=7, workers=1, ledger=led,
               reuse=False)
    assert n[0] > first, "--rerun must force the prover"


def test_a_failed_node_is_not_re_attempted_without_its_parents(tmp_path, monkeypatch):
    """`verify` used to re-run every failure with all parents removed, at the
    same budget that had just failed. Across the 84 archived dag.json files that
    was 81 fresh searches for 8620.8s, of which 8532.8s (99.0%) proved nothing
    -- and dropping every parent cannot say WHICH edge is wrong. Both directions
    of the parented run, once each, and nothing else."""
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
    s = Sketch({"p": ("additive_identity", "add(X,X)", []),
                "n": ("multiply(X,X)", "add(X,X)", ["p"])})
    out = dag.verify("RNG029-5", s, outdir=tmp_path, budget=1, workers=1,
                     ledger=tmp_path / "l.jsonl")
    inputs = sorted(tmp_path.glob("n.*.p"))
    assert len(inputs) == 2, [f.name for f in inputs]     # the two directions
    assert all("parent" in f.read_text() for f in inputs), \
        "no run of `n` may be scheduled with its parent withheld"
    rows = [r for r in out["results"] if r["node"] == "n"]
    assert len(rows) == 2 and all(r["n_support"] == 1 for r in rows)
    assert all(r.get("unused_support") is None for r in rows), \
        "a failed run prints no certificate, so nothing can be attributed"


def test_artifacts_of_differently_supported_runs_do_not_collide(tmp_path, monkeypatch):
    """Artifacts are addressed by the run's own identity. Naming them by node
    and direction alone let one run overwrite another that differed only in what
    was supplied, and a later comparison of two searches silently compared two
    copies of one. The retry that first exposed this is gone; the property it
    guarded is not, because the same node is verified across iterations as its
    parents change."""
    from overtone import runner
    from overtone.agent import dag

    class R:
        status, proved, cpu, wall, output = "Unsatisfiable", True, 1.0, 1.1, "x"

    monkeypatch.setattr(runner, "run", lambda path, *a, **k: R())
    led = tmp_path / "l.jsonl"
    base = {"p": ("additive_identity", "add(X,X)", []),
            "q": ("add(X,Y)", "add(Y,X)", [])}
    for parents in (["p"], ["p", "q"]):
        dag.verify("RNG029-5", Sketch({**base, "n": ("multiply(X,X)",
                                                     "add(X,X)", parents)}),
                   outdir=tmp_path, budget=1, workers=1, ledger=led)
    # One file per support set: each proves on the first direction tried, so the
    # second is never run. Two supports, two surviving artifacts, two questions.
    inputs = sorted(tmp_path.glob("n.*.p"))
    assert len(inputs) == 2, [f.name for f in inputs]
    assert len({f.read_text() for f in inputs}) == 2, \
        "two different questions must leave two different input files"
    assert all("parent_1" in f.read_text() for f in inputs)
    assert sum("parent_2" in f.read_text() for f in inputs) == 1


def test_used_supports_reads_the_certificate_not_the_preamble():
    """twee lists every axiom of the problem before the proof, so scanning the
    whole output reports every parent as used. This artifact supplied four
    parents and its proof cites exactly parent_1 and parent_2."""
    from overtone import proofs

    text = (Path(__file__).parent / "fixtures"
            / "assoc_comm_1.proved.4parents.out").read_text()
    assert proofs.used_supports(text, count=4) == {1, 2}
    # An index past what was supplied names a lemma the caller cannot resolve.
    assert proofs.used_supports(text, count=1) == {1}
    # None, not the empty set: "nothing to attribute" is not "used nothing".
    assert proofs.used_supports("RESULT: Timeout\n") is None
    assert proofs.used_supports(text) == {1, 2}


def test_support_attribution_indexes_the_supplied_list_not_the_parents(tmp_path,
                                                                       monkeypatch):
    """`Sketch.equations` drops `given` axioms, so `parent_N` counts only the
    ordinary parents. Resolving it against a node's declared parents credits the
    wrong lemma the moment an axiom is cited as a parent -- silently, since both
    are names and neither read raises."""
    from overtone import runner
    from overtone.agent import dag

    # parent_1 is `mid` -- the SECOND declared parent, because `ax` is given and
    # is never supplied. A naive mapping would report `ax` as the used one.
    proof = ("Here is a proof.\n"
             "Axiom 1 (parent_1): add(X, Y) = add(Y, X).\n"
             "Lemma 2: x = y.\n= { by axiom 1 (parent_1) }\n"
             "RESULT: Unsatisfiable\n")

    class R:
        status, proved, cpu, wall = "Unsatisfiable", True, 1.0, 1.1
        output = proof

    monkeypatch.setattr(runner, "run", lambda path, *a, **k: R())
    s = Sketch({"ax": ("add(X,Y)", "add(Y,X)", []),
                "mid": ("multiply(X,X)", "add(X,X)", []),
                "tail": ("multiply(X,Y)", "multiply(Y,X)", []),
                "n": ("associator(X,X,X)", "additive_identity",
                      ["ax", "mid", "tail"])},
               given=["ax"])
    out = dag.verify("RNG029-5", s, outdir=tmp_path, budget=1, workers=1,
                     ledger=tmp_path / "l.jsonl")
    row = next(r for r in out["results"] if r["node"] == "n" and r["proved"])
    assert row["support"] == ["mid", "tail"], "a given axiom is never supplied"
    assert row["used_support"] == ["mid"]
    assert row["unused_support"] == ["tail"], \
        "parent_1 is the first SUPPLIED lemma, not the first declared parent"


def test_support_attribution_is_absent_where_it_would_be_a_guess(tmp_path,
                                                                 monkeypatch):
    """None means "not attributed" and must never read as "used nothing". A
    hint-channel run names no parents in its proof at all, and a reused row can
    point at an artifact that is gone."""
    from overtone import runner
    from overtone.agent import dag

    class R:
        status, proved, cpu, wall = "Unsatisfiable", True, 1.0, 1.1
        output = "Here is a proof.\nLemma 1: x = y.\nRESULT: Unsatisfiable\n"

    monkeypatch.setattr(runner, "run", lambda path, *a, **k: R())
    usage = dag._support_usage(["a", "b"], "hints", True, None)
    assert usage["used_support"] is None and usage["unused_support"] is None
    assert usage["support"] == ["a", "b"]
    # A missing artifact is the same answer, not an empty one.
    gone = dag._support_usage(["a"], "axioms", True, tmp_path / "nope.out")
    assert gone["used_support"] is None
    # And a proof that cites none of them IS the empty set -- the case worth
    # acting on, and the one that must not be confused with the above.
    art = tmp_path / "p.out"
    art.write_text(R.output)
    none_used = dag._support_usage(["a"], "axioms", True, art)
    assert none_used["used_support"] == [] and none_used["unused_support"] == ["a"]


def test_reused_rows_keep_their_support_attribution(tmp_path, monkeypatch):
    """The ledger answers every repeat after the first, so attribution computed
    only on a fresh run would vanish from iteration two onward -- exactly when
    the agent has enough history to act on it."""
    from overtone import runner
    from overtone.agent import dag

    class R:
        status, proved, cpu, wall = "Unsatisfiable", True, 1.0, 1.1
        output = ("Here is a proof.\nAxiom 1 (parent_1): add(X, Y) = add(Y, X).\n"
                  "RESULT: Unsatisfiable\n")

    monkeypatch.setattr(runner, "run", lambda path, *a, **k: R())
    led = tmp_path / "l.jsonl"
    s = Sketch({"p": ("add(X,Y)", "add(Y,X)", []),
                "q": ("multiply(X,X)", "add(X,X)", []),
                "n": ("associator(X,X,X)", "additive_identity", ["p", "q"])})
    kw = dict(outdir=tmp_path, budget=1, workers=1, ledger=led)
    first = dag.verify("RNG029-5", s, **kw)
    again = dag.verify("RNG029-5", s, **kw)
    row = next(r for r in again["results"] if r["node"] == "n" and r["proved"])
    assert row.get("reused"), "the second run must come from the ledger"
    assert row["unused_support"] == ["q"] == next(
        r for r in first["results"]
        if r["node"] == "n" and r["proved"])["unused_support"]


# --------------------------------------------------------------- loop memory

def test_sketch_digest_ignores_node_order_but_not_parent_order():
    """Node order does not reach twee -- the schedule sorts -- but parent order sets
    the order equations enter the prover, and so the search."""
    a = Sketch({"x": ("f", "g", ["p", "q"]), "p": ("additive_identity", "add(X,X)", []), "q": ("multiply(X,X)", "add(Y,Y)", [])})
    b = Sketch({"p": ("additive_identity", "add(X,X)", []), "q": ("multiply(X,X)", "add(Y,Y)", []), "x": ("f", "g", ["p", "q"])})
    c = Sketch({"p": ("additive_identity", "add(X,X)", []), "q": ("multiply(X,X)", "add(Y,Y)", []), "x": ("f", "g", ["q", "p"])})
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
    s = Sketch({"p": ("additive_identity", "add(X,X)", [])})
    # add q, remove q, add q ... -> iteration 2 revisits iteration 0's sketch
    script = [[{"op": "add_node", "name": "q", "lhs": "multiply(X,X)", "rhs": "add(Y,Y)"}],
              [{"op": "remove_node", "name": "q"}],
              [{"op": "add_node", "name": "q", "lhs": "multiply(X,X)", "rhs": "add(Y,Y)"}]]
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
    s = Sketch({"p": ("additive_identity", "add(X,X)", [])})
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
            # A distinct equation each turn: proposing `c = d` every time is a
            # duplicate, which review now withholds -- correctly, but it would
            # end the loop early and this test is about history, not review.
            # Distinct STRUCTURE per turn: X0/X1 are both variables, so terms
            # differing only in them are alpha-variants -- which review rightly
            # withholds as duplicates.
            lhs = "X"
            for _ in range(state.iteration + 1):
                lhs = f"multiply({lhs},Y)"
            return [{"op": "add_node", "name": f"n{state.iteration}",
                     "lhs": lhs, "rhs": "add(X,X)"}]

    run_loop("RNG029-5", Sketch({"p": ("additive_identity", "add(X,X)", [])}), Watcher(),
             outdir=tmp_path, budget=Budget(node=1, final=1, workers=1),
             max_iterations=3)
    assert seen_histories == [0, 1, 2], seen_histories


def test_a_proved_node_does_not_pay_for_the_other_direction(tmp_path, monkeypatch):
    """The losing arm sets the node's wall time. right_moufang_a reported 0.5s
    while the run waited 300.3s on the direction that could not prove it."""
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
    s = Sketch({"n": ("multiply(X,X)", "add(X,X)", [])})
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
    dag.verify("RNG029-5", Sketch({"n": ("multiply(X,X)", "add(X,X)", [])}), outdir=tmp_path,
               budget=1, workers=1, ledger=tmp_path / "l.jsonl")
    assert set(seen) == {"--flatten-goal", "--no-flatten-goal"}, seen


def test_racing_directions_cancels_the_loser(tmp_path, monkeypatch):
    """Both directions start together and the loser is stopped the moment the
    winner proves, so the node waits on the winner rather than on the arm that
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
    j = {"problem": "RNG029-5", "node": "n", "lhs": "multiply(X,X)", "rhs": "add(X,X)",
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
    assert elapsed < 2.0, f"the node waited on the loser ({elapsed:.1f}s)"


def test_a_cancelled_run_is_never_recorded(tmp_path, monkeypatch):
    """Recording one would let reuse skip a question that was never resolved."""
    from overtone import runner
    from overtone.agent import dag, ledger

    class Cancelled:
        status, proved, cpu, wall, output = "Cancelled", False, 0.4, 0.4, "x"

    monkeypatch.setattr(runner, "run", lambda *a, **k: Cancelled())
    led = tmp_path / "l.jsonl"
    dag._job({"problem": "RNG029-5", "node": "n", "lhs": "multiply(X,X)", "rhs": "add(X,X)",
              "eqs": [], "channel": "axioms", "direction": "--flatten-goal",
              "budget": 60, "outdir": str(tmp_path), "binary": "/bin/true",
              "reuse": False, "ledger": str(led)})
    assert ledger.load(led) == {}, "a cancelled run must leave no record"


def test_reuse_never_hands_on_a_stale_artifact_path(tmp_path, monkeypatch):
    """A reused verdict is sound -- the key is over input bytes -- but a path
    recorded before artifacts were identity-addressed can name a file a later
    run overwrote. 6 of 42 rows in the real ledger point at files that are gone."""
    from overtone import runner
    from overtone.agent import dag, ledger

    class R:
        status, proved, cpu, wall, output = "Unsatisfiable", True, 1.0, 1.0, "x"

    monkeypatch.setattr(runner, "run", lambda *a, **k: R())
    led = tmp_path / "l.jsonl"
    job = {"problem": "RNG029-5", "node": "n", "lhs": "multiply(X,X)", "rhs": "add(X,X)",
           "eqs": [], "channel": "axioms", "direction": "--flatten-goal",
           "budget": 60, "outdir": str(tmp_path), "binary": "/bin/true",
           "reuse": True, "ledger": str(led)}
    first = dag._job(job)
    assert Path(first["output"]).exists()

    Path(first["output"]).unlink()               # the artifact goes away
    again = dag._job(job)
    assert again["reused"] and again["proved"], again
    assert again["output"] is None and again["artifact_missing"], again


def test_node_flags_rerun_only_their_own_node(tmp_path, monkeypatch):
    """A search option belongs to the node that needs it.

    RNG033-8's goal needs a term ordering the rest of the sketch does not, and
    setting one globally would change every node's ledger key and re-verify a
    library that costs ~1100s -- for no reason, since a lemma proved under one
    ordering is still a theorem and reaches a downstream run as axiom text.
    """
    from overtone import runner
    from overtone.agent import dag

    seen = []

    class FakeResult:
        status, proved, cpu, wall, output = "Unsatisfiable", True, 2.0, 2.1, "ok"

    def fake_run(path, flags, budget, **kw):
        seen.append(list(flags))
        return FakeResult()

    monkeypatch.setattr(runner, "run", fake_run)
    led = tmp_path / "l.jsonl"
    s = Sketch({"a": ("multiply(X,X)", "add(X,X)", []), "b": ("commutator(X,X)", "additive_identity", ["a"])})
    kw = dict(outdir=tmp_path, budget=7, workers=1, ledger=led,
              directions=["--flatten-goal"])
    dag.verify("RNG029-5", s, **kw)
    n_before = len(seen)

    out = dag.verify("RNG029-5", s, node_flags={"b": ["--precedence", "g,f"]}, **kw)
    ran = seen[n_before:]
    assert len(ran) == 1, "only the flagged node may reach the prover again"
    assert ran[0][-2:] == ["--precedence", "g,f"], "extra flags go last, so a node can override a default"
    by_node = {r["node"]: r for r in out["results"]}
    assert by_node["a"].get("reused"), "an unflagged node keeps its recorded proof"
    assert not by_node["b"].get("reused"), "the flagged node is a different question"


def test_goal_contact_resolves_names_instead_of_grepping_shapes():
    """Grepping the output for a goal term's shape measures nothing.

    `--flatten-goal` names each goal subterm and rewrites matching terms to the
    name, so the shape stops appearing literally. Counting shapes said RNG033-8's
    search never built the goal's right-hand side; resolving the names first said
    it was the dominant side. A full iteration was drafted on the wrong reading.
    """
    from overtone import proofs

    text = "\n".join([
        "  Goal 1 (goal): add(f(a), g(b)) = add(h(c), k(d)).",
        "  Axiom 1 (flattening): t1 = h(c).",
        "(1.0) 1. f(a) -> u1",
        "(1.0) 2. u1 -> t1",
        "(1.0) 3. p(X) -> q(X)",
    ])
    c = proofs.goal_contact(text)
    assert c["rules"] == 3
    assert c["lhs"] == 2, "a rule naming f(a), or its alias u1, touches the LHS"
    assert c["rhs"] == 1, "t1 is an alias for h(c) and the shape never appears"
    assert c["both"] == 1, "only rule 2 touches both sides, so only it can close"
    assert c["goal_directed"]


def test_goal_contact_flags_a_search_that_never_sees_the_goal():
    """--no-flatten-goal keeps the goal out of the rewrite system entirely, so
    every count is 0 by construction. Read as a measurement that would say the
    search is not reaching its goal -- indistinguishable from the numbers alone.
    """
    from overtone import proofs

    text = "\n".join([
        "  Goal 1 (goal): add(f(a), g(b)) = add(h(c), k(d)).",
        "(1.0) 1. p(X) -> q(X)",
    ])
    c = proofs.goal_contact(text)
    assert (c["lhs"], c["rhs"], c["both"]) == (0, 0, 0)
    assert not c["goal_directed"], "0 here means not measurable, not not-reaching"


def test_usage_totals_and_costs_a_run():
    """A loop iteration costs prover CPU and model tokens; only one was reported.

    Also pins the two wire formats: Anthropic reports input_tokens/output_tokens
    plus cache fields, OpenAI prompt_tokens/completion_tokens. Reading only one
    would silently report zero for the other provider.
    """
    from overtone.agent import pricing

    u = pricing.Usage()
    u.add("claude-opus-5", "draft",
          {"input_tokens": 1000, "output_tokens": 200,
           "cache_read_input_tokens": 4000, "cache_creation_input_tokens": 0})
    u.add("claude-opus-5", "iter00", {"prompt_tokens": 500, "completion_tokens": 100})
    assert (u.input, u.output, u.cache_read) == (1500, 300, 4000)
    # 1500*5 + 4000*5*0.1 + 300*25 = 7500 + 2000 + 7500 = 17000 per 1e6
    assert abs(u.cost() - 0.017) < 1e-9
    assert u.calls == 2 and u.total() == 5800


def test_openai_cached_tokens_are_not_double_counted():
    """OpenAI's `prompt_tokens` INCLUDES cached tokens; Anthropic's does not.

    Billing the full `prompt_tokens` at the input rate and the cached span again
    at the cached rate overcharges, and the error is invisible in the totals --
    every count still looks plausible. It also matters that OpenAI's cached rate
    is not a fixed multiple of input: 0.1x on gpt-5, 0.5x on gpt-4o.
    """
    from overtone.agent import pricing

    u = pricing.Usage()
    u.add("gpt-5", "iter00", {"prompt_tokens": 10000, "completion_tokens": 500,
                              "prompt_tokens_details": {"cached_tokens": 8000}})
    assert u.input == 2000, "cached tokens must be subtracted from prompt_tokens"
    assert u.cache_read == 8000
    # 2000*1.25 + 8000*0.125 + 500*10 = 2500 + 1000 + 5000 = 8500 per 1e6
    assert abs(u.cost() - 0.0085) < 1e-12

    # gpt-4o caches at 0.5x, not 0.1x -- a uniform multiplier would misprice it.
    assert pricing.PRICES["gpt-4o"].cache_read == 1.25
    assert pricing.PRICES["gpt-5"].cache_read == 0.125


def test_unknown_model_reports_tokens_without_inventing_a_cost():
    """A confidently wrong cost is worse than an absent one -- this file has no
    authority on non-Anthropic pricing, so it must not guess."""
    from overtone.agent import pricing

    u = pricing.Usage()
    u.add("some-unreleased-model", "iter00",
          {"prompt_tokens": 1000, "completion_tokens": 100})
    assert u.total() == 1100
    assert u.cost() is None
    assert "cost unknown" in pricing.render(u)


def test_loop_drafts_a_sketch_before_verifying_a_bare_goal(tmp_path, monkeypatch):
    """Running the loop against a goal-only seed did no drafting at all: it
    verified the seed (one guaranteed-failing run) and only then consulted the
    agent. Drafting is the first half of draft -> verify -> diagnose -> revise.
    """
    from overtone import runner
    from overtone.agent import dag, loop as looplib

    class FakeResult:
        status, proved, cpu, wall, output = "Timeout", False, 1.0, 1.0, ""

    monkeypatch.setattr(runner, "run", lambda *a, **k: FakeResult())

    class DraftingAgent:
        seen = {}

        def draft(self, problem, axioms, conjecture, goal_name="goal"):
            assert axioms and "=" in axioms[0], "axioms must be real statements"
            assert not any("V" + c in conjecture[0] for c in "XYZW"), \
                "the goal must be shown in the same variable style nodes use"
            DraftingAgent.seen = {"goal_name": goal_name}
            return [
                {"op": "add_node", "name": "wp1", "lhs": "multiply(X,X)", "rhs": "add(X,X)",
                 # `commutator` is an AXIOM name, not a node -- a real draft lost
                 # its only node this way. The bad name is dropped, not the node.
                 "parents": ["commutator"]},
                {"op": "add_node", "name": "wp2", "lhs": "associator(X,X,Y)", "rhs": "additive_identity",
                 "parents": ["wp1"]},
                {"op": "set_parents", "name": goal_name, "parents": ["wp2"]},
            ]

        def act(self, state):
            return []

    seed = Sketch({"goal": ("commutator(X,X)", "additive_identity", [])})
    out = looplib.run_loop("RNG033-8", seed, DraftingAgent(), outdir=tmp_path,
                           binary=None, max_iterations=1,
                           directions=["--flatten-goal"])
    assert DraftingAgent.seen["goal_name"] == "goal", \
        "the agent must be told which node is the goal, not guess it"
    final = out["final_sketch"]
    assert {"wp1", "wp2"} <= set(final), "every drafted node must reach the sketch"
    assert final["wp1"]["parents"] == [], "an axiom name is dropped, not fatal"
    assert final["goal"]["parents"] == ["wp2"], "the goal is rewired onto the draft"


def test_draft_tool_takes_the_whole_dag_in_one_call():
    """A per-node action schema yields one node per response: a real run drafted
    a single node in 55 output tokens and stopped. Drafting is one artifact."""
    from overtone.agent import llm

    for provider, key in (("anthropic", "input_schema"), ("openai", "parameters")):
        tools = llm.draft_schema(provider)
        assert len(tools) == 1, "drafting must be a single tool"
        spec = tools[0] if provider == "anthropic" else tools[0]["function"]
        assert spec["name"] == "draft_sketch"
        props = spec[key]["properties"]
        assert props["nodes"]["type"] == "array", "the whole node list in one call"
        assert "goal_parents" in props, "the goal is wired, never restated"


def test_review_withholds_axiom_restatements_and_duplicates(tmp_path):
    """An agent draft spent four of eleven nodes restating the problem's axioms.

    They prove in 0.0s and read as successes, so nothing else in the loop
    notices. Review is the only stage that can see it, because it is the only
    one that compares a proposal against the problem rather than against a run.
    """
    from overtone.agent import review

    seed = Sketch({"goal": ("commutator(X,X)", "additive_identity", []),
                   "keep": ("associator(X,X,Y)", "additive_identity", [])})
    ctx = review.context_for("RNG033-8", seed, "goal")
    acts = [
        # verbatim the commutator definition axiom of RNG003-0.ax
        {"op": "add_node", "name": "comm_expand", "lhs": "commutator(X,Y)",
         "rhs": "add(multiply(Y,X),additive_inverse(multiply(X,Y)))"},
        {"op": "add_node", "name": "dup", "lhs": "associator(X,X,Y)", "rhs": "additive_identity"},
        {"op": "add_node", "name": "regoal", "lhs": "commutator(X,X)",
         "rhs": "additive_identity"},
        {"op": "add_node", "name": "fine", "lhs": "multiply(X,X)", "rhs": "add(X,X)"},
        {"op": "set_parents", "name": "goal", "parents": ["fine"]},
    ]
    kept, findings = review.review(acts, ctx)
    assert [a["name"] for a in kept] == ["fine", "goal"]
    by = {f.node: f for f in findings if f.verdict == review.REJECT}
    assert set(by) == {"comm_expand", "dup", "regoal"}
    assert "axiom" in by["comm_expand"].reason
    # Every rejection is reported, never silently dropped: an agent that cannot
    # see the filter keeps tripping over it.
    assert all(f.reason for f in findings)


def test_free_ring_review_never_rejects_a_theory_specific_lemma():
    """"Not universal" is not "false".

    Most useful lemmas need the problem's own axioms; rejecting them would
    remove exactly the nodes worth having. The reviewer reports and never
    withholds -- what the failing agent lacked was the information, not a veto.
    """
    from overtone import freering
    from overtone.agent import review

    A, M, I = "associator", "multiply", "additive_inverse"
    universal = {"op": "add_node", "name": "teich",
                 "lhs": f"add({A}({M}(X,Y),Z,W),{A}(X,Y,{M}(Z,W)))",
                 "rhs": f"add(add({A}(X,{M}(Y,Z),W),{M}(X,{A}(Y,Z,W))),"
                        f"{M}({A}(X,Y,Z),W))"}
    theory_only = {"op": "add_node", "name": "flexible",
                   "lhs": f"{M}({M}(X,Y),X)", "rhs": f"{M}(X,{M}(Y,X))"}

    a, = freering.reviewer(universal, None)
    b, = freering.reviewer(theory_only, None)
    assert a.data["universal"] and a.verdict == review.NOTE
    assert not b.data["universal"] and b.verdict == review.NOTE, \
        "a lemma needing the theory's axioms must never be withheld"
    # Outside the signature it must have no opinion rather than guess.
    assert freering.reviewer({"lhs": "foo(X)", "rhs": "bar(X)"}, None) == []


def test_axiom_nodes_are_assumed_never_proved(tmp_path, monkeypatch):
    """The problem's own axioms enter the DAG so it has one canonical shape.

    They are true by assumption and twee already has them from the problem file,
    so proving them is a tautology at 60s a go. Ratios count claims only -- an
    axiom is not an achievement.
    """
    from overtone import runner
    from overtone.agent import dag

    ran = []

    class R:
        status, proved, cpu, wall, output = "Unsatisfiable", True, 1.0, 1.0, "ok"

    monkeypatch.setattr(runner, "run",
                        lambda path, *a, **k: (ran.append(str(path)), R())[1])

    s = dag.Sketch.from_problem("RNG033-8", goal="g")
    assert len(s.given) >= 10 and "g" not in s.given
    assert "commutator" in s.given, "axiom nodes keep their TPTP names"

    # Its own ledger: the shared one may already hold this exact invocation,
    # and a reused row would make "no axiom ran" vacuously true.
    out = dag.verify("RNG033-8", s, outdir=tmp_path, budget=1, workers=1,
                     directions=["--flatten-goal"], ledger=tmp_path / "l.jsonl")
    assert len(ran) == 1, "only the goal is a claim; no axiom may reach the prover"
    assert out["n_nodes"] == 1 and out["n_given"] == len(s.given)


def test_citing_an_axiom_parent_does_not_re_supply_it():
    """An axiom cited as a parent is documentation of a derivation, not a request
    to state it twice. Re-supplying would change the input bytes -- and so the
    ledger key -- for a run that is semantically identical.
    """
    from overtone.agent.dag import Sketch

    s = Sketch({"commutator": ("commutator(X,Y)", "add(Y,X)", []),
                "lemma": ("multiply(X,X)", "add(X,X)", []),
                "top": ("p(X)", "q(X)", ["commutator", "lemma"])},
               given=["commutator"])
    assert s.equations(["commutator", "lemma"]) == [("multiply(X,X)", "add(X,X)")]
    assert s.equations(["commutator", "lemma"], skip_given=False) == [
        ("commutator(X,Y)", "add(Y,X)"), ("multiply(X,X)", "add(X,X)")]
    # An axiom is an assumption, so it cannot rest on anything.
    with pytest.raises(ValueError, match="cannot have parents"):
        Sketch({"a": ("multiply(X,X)", "add(X,X)", []), "b": ("p(X)", "q(X)", ["a"])},
               given=["b"])
    # Two sketches differing only in what is assumed are different sketches.
    plain = Sketch({"a": ("multiply(X,X)", "add(X,X)", [])})
    assumed = Sketch({"a": ("multiply(X,X)", "add(X,X)", [])}, given=["a"])
    assert plain.digest() != assumed.digest()
    assert Sketch.from_json(assumed.to_json()).given == {"a"}


def test_a_sketch_may_use_a_subset_of_the_axioms_but_never_a_new_one():
    """Every node must follow from the problem's own axioms.

    Two ways a sketch quietly stops being about the problem, both of which
    produce results that look perfectly good: marking a non-axiom `given`, which
    turns everything downstream into a theorem of a stronger theory (exactly how
    RNG027-10 and RNG029-10 were claimed then withdrawn); and naming a symbol
    the problem does not have, which is a definition rather than a consequence.
    """
    from overtone.agent.dag import Sketch, grounding_errors

    canonical = Sketch.from_problem("RNG033-8", goal="g")
    assert grounding_errors(canonical, "RNG033-8") == []

    # A subset of the axioms is fine -- that is the normal case.
    keep = sorted(canonical.given)[:3]
    subset = Sketch({n: canonical.nodes[n] for n in keep + ["g"]}, given=keep)
    assert grounding_errors(subset, "RNG033-8") == []

    # An assumption that is not an axiom of this problem.
    smuggled = dict(canonical.nodes)
    smuggled["extra"] = ("multiply(X,Y)", "multiply(Y,X)", [])
    bad = Sketch(smuggled, given=sorted(canonical.given) + ["extra"])
    errs = grounding_errors(bad, "RNG033-8")
    assert any("not an axiom" in e for e in errs), errs

    # A symbol outside the signature.
    alien = dict(canonical.nodes)
    alien["alien"] = ("frobnicate(X)", "X", [])
    errs = grounding_errors(Sketch(alien, given=canonical.given), "RNG033-8")
    assert any("frobnicate" in e for e in errs), errs


def test_axioms_form_their_own_layer():
    """An axiom and a parentless claim look identical structurally and differ
    completely: one is assumed, the other is what we are trying to prove."""
    from overtone.agent.dag import Sketch

    s = Sketch.from_problem("RNG033-8", goal="g")
    with_ax = s.layers()
    assert with_ax[0] == sorted(s.given), "axioms are layer 0, alone"
    assert "g" not in with_ax[0]
    assert s.layers(with_axioms=False) == with_ax[1:]
    # The separation that matters is not the layer -- that is layout -- but that
    # an axiom is never a claim and is never scheduled. `verify` builds its jobs
    # from `topological()` minus `given`, and grounds every axiom by assumption.
    assert set(s.claims()) == set(s.topological()) - s.given
    assert "g" in s.claims() and not (s.given & set(s.claims()))


def test_review_withholds_an_out_of_signature_node_instead_of_aborting():
    """`verify` refuses a sketch that names a symbol the problem lacks, which
    would end a whole run. Review catches it a step earlier: the one node is
    withheld, the agent is told, and the run continues.

    Both must agree on what a symbol is -- they share `terms.symbols_in`. If
    review passed a node that verification then rejected, the run would abort on
    an edit review had already blessed.
    """
    from overtone.agent import review
    from overtone.agent.dag import Sketch, grounding_errors

    seed = Sketch.from_problem("RNG033-8", goal="g")
    ctx = review.context_for("RNG033-8", seed, "g")
    alien = {"op": "add_node", "name": "alien",
             "lhs": "frobnicate(X)", "rhs": "X", "parents": []}
    native = {"op": "add_node", "name": "native",
              "lhs": "multiply(X,Y)", "rhs": "multiply(Y,X)", "parents": []}

    kept, findings = review.review([alien, native], ctx)
    assert [a["name"] for a in kept] == ["native"], "only the alien node is withheld"
    bad, = [f for f in findings if f.verdict == review.REJECT]
    assert bad.node == "alien" and "frobnicate" in bad.reason

    # The two gates must not disagree: what review passes, verification accepts.
    ok = Sketch({**seed.nodes, "native": ("multiply(X,Y)", "multiply(Y,X)", [])},
                given=seed.given)
    assert grounding_errors(ok, "RNG033-8") == []


def test_one_bad_edit_does_not_end_the_run(tmp_path, monkeypatch):
    """A model passed the PROBLEM NAME as a parent. `apply` raised, and a run
    that had already spent 4,800 prover-seconds died on the traceback.

    Two independent guards: review drops the bad reference and keeps the node,
    and the loop skips any edit that still fails to apply rather than crashing.
    """
    from overtone import runner
    from overtone.agent import loop as looplib

    class Fail:
        status, proved, cpu, wall, output = "Timeout", False, 0.1, 0.1, ""

    monkeypatch.setattr(runner, "run", lambda *a, **k: Fail())
    turns = []

    class BadParents:
        def act(self, state):
            turns.append(state.iteration)
            if state.iteration == 0:
                return [{"op": "add_node", "name": "n1",
                         "lhs": "multiply(X,Y)", "rhs": "multiply(Y,X)",
                         # the problem name, not a node
                         "parents": ["RNG033-8"]}]
            return []

    s = Sketch({"g": ("commutator(X,X)", "additive_identity", [])})
    out = looplib.run_loop("RNG033-8", s, BadParents(), outdir=tmp_path,
                           max_iterations=3, directions=["--flatten-goal"],
                           draft=False)
    assert turns == [0, 1], "the run must survive the bad parent and continue"
    assert out["final_sketch"]["n1"]["parents"] == [], "bad reference dropped"
    assert any(f["verdict"] == "warn" and "RNG033-8" in f["reason"]
               for r in out["history"] for f in r["findings"]), \
        "the agent must be told what was dropped, or it repeats it"


def test_the_loop_drops_uncited_parents_and_tells_the_agent(tmp_path, monkeypatch):
    """End to end: the controller edits the sketch the agent did not, so the
    edit has to reach `final_sketch` as a real `set_parents` and reach the agent
    as a finding -- an unexplained reparenting is how a model comes to re-add
    what the loop just removed."""
    from overtone import runner
    from overtone.agent import loop as looplib

    proof = ("Here is a proof.\n"
             "Axiom 1 (parent_1): add(X, Y) = add(Y, X).\n"
             "RESULT: Unsatisfiable\n")

    class R:
        def __init__(self, ok):
            self.proved, self.wall, self.cpu = ok, 1.0, 1.0
            self.status = "Unsatisfiable" if ok else "Timeout"
            self.output = proof if ok else ""

    # Nodes prove, the target attempt does not -- `sk_dag_` is the goal prefix
    # `verify` skolemises with and `attempt` never uses, since it runs the
    # problem's own conjecture. Without the split the first iteration proves the
    # conjecture and the loop ends before the agent has a turn.
    monkeypatch.setattr(runner, "run",
                        lambda path, *a, **k: R("sk_dag_" in Path(path).read_text()))
    seen = []

    told = []

    class Agent:
        def act(self, state):
            seen.append({n.name: (n.status, tuple(n.unused_support))
                         for n in state.nodes})
            told.append([(f.verdict, f.node, f.reason) for f in state.findings])
            if state.iteration == 0:
                # Keeps `g` the unique sink, so the target is still identified
                # and the run is judged on the same footing both iterations.
                return [{"op": "add_node", "name": "extra",
                         "lhs": "multiply(X,X)", "rhs": "multiply(X,X)",
                         "parents": []},
                        {"op": "set_parents", "name": "g",
                         "parents": ["mid", "q", "extra"]}]
            return []

    # `mid`, not the sink: the target node is deliberately exempt from the drop.
    # `q` also feeds `g`, so dropping mid's edge to it does not orphan it.
    s = Sketch({"p": ("add(X,Y)", "add(Y,X)", []),
                "q": ("multiply(X,X)", "add(X,X)", []),
                "mid": ("associator(X,X,X)", "additive_identity", ["p", "q"]),
                "g": ("commutator(X,X)", "additive_identity", ["mid", "q"])})
    out = looplib.run_loop("RNG033-8", s, Agent(), outdir=tmp_path,
                           max_iterations=3, directions=["--flatten-goal"],
                           draft=False, ledger=tmp_path / "l.jsonl")
    # `q` was supplied and never cited, so it goes; `p` carried the proof.
    assert seen[0]["mid"] == ("proved_scoped", ("q",)), seen[0]
    assert out["final_sketch"]["mid"]["parents"] == ["p"], \
        out["final_sketch"]["mid"]
    assert seen[1]["mid"][1] == (), "with `q` gone there is nothing left uncited"
    # The agent is told, on the turn after the edit, that the controller moved
    # its sketch. Unexplained reparenting is how a model comes to re-add what
    # the loop just removed.
    assert any(verdict == "note" and node == "mid" and "never cited" in why
               for verdict, node, why in told[1]), told[1]


def test_edits_preserve_the_axiom_set():
    """`apply` returned a Sketch without `given`, so the first edit turned every
    axiom back into a claim -- scheduling them for proof and inflating every
    ratio the run reports by the axiom count."""
    from overtone.agent.loop import apply

    s = Sketch.from_problem("RNG033-8", goal="g")
    n = len(s.given)
    s2 = apply(s, {"op": "add_node", "name": "lemma",
                   "lhs": "multiply(X,Y)", "rhs": "multiply(Y,X)", "parents": []})
    assert s2.given == s.given and len(s2.given) == n
    # removing an axiom node drops it from `given` too, not just from `nodes`
    s3 = apply(s2, {"op": "remove_node", "name": "commutator"})
    assert "commutator" not in s3.given and len(s3.given) == n - 1


def test_stalling_counts_proofs_not_nodes(tmp_path, monkeypatch):
    """A run sat at 15 proved nodes for four iterations while adding five more.

    Nothing noticed, so it kept making local edits. Progress is a node newly
    PROVED; a sketch that only grows has not moved.
    """
    from overtone import runner
    from overtone.agent import loop as looplib

    class Fail:
        status, proved, cpu, wall, output = "Timeout", False, 0.1, 0.1, ""

    monkeypatch.setattr(runner, "run", lambda *a, **k: Fail())
    seen = []

    class Adder:
        def act(self, state):
            seen.append(state.stalled)
            lhs = "X"
            for _ in range(state.iteration + 2):
                lhs = f"multiply({lhs},Y)"
            return [{"op": "add_node", "name": f"n{state.iteration}",
                     "lhs": lhs, "rhs": "add(X,X)", "parents": []}]

    s = Sketch({"g": ("commutator(X,X)", "additive_identity", [])})
    looplib.run_loop("RNG033-8", s, Adder(), outdir=tmp_path, max_iterations=4,
                     directions=["--flatten-goal"], draft=False)
    assert seen == [0, 1, 2, 3], f"stall must grow while nothing proves: {seen}"


def test_redraft_replaces_the_decomposition_but_keeps_what_is_earned():
    """The one result this project produced is a 29-node library designed as a
    whole. `add_node`/`set_parents`/`subdivide` can only nudge, so a loop
    restricted to them cannot reach that shape at any iteration count.
    """
    from overtone.agent.loop import apply

    s = Sketch.from_problem("RNG033-8", goal="rng033_goal")
    s = apply(s, {"op": "add_node", "name": "earned",
                  "lhs": "multiply(X,Y)", "rhs": "multiply(Y,X)", "parents": []})
    s = apply(s, {"op": "add_node", "name": "junk",
                  "lhs": "add(X,Y)", "rhs": "add(Y,X)", "parents": []})

    out = apply(s, {"op": "redraft", "approach": "via the Kleinfeld function",
                    "keep": ["earned"],
                    "nodes": [{"name": "k1", "lhs": "associator(X,Y,Z)",
                               "rhs": "associator(Y,Z,X)", "parents": ["earned"]}],
                    "goal_parents": ["k1"]})
    assert "junk" not in out.nodes, "the old decomposition is replaced"
    assert "earned" in out.nodes and "k1" in out.nodes
    assert out.given == s.given, "axioms always survive a redraft"
    assert "rng033_goal" in out.nodes, "so does the goal"
    assert out.nodes["rng033_goal"][2] == ["k1"]
    with pytest.raises(ValueError, match="unknown node"):
        apply(s, {"op": "redraft", "approach": "x", "nodes": [], "keep": ["nope"]})


def test_no_tool_property_is_an_untyped_array():
    """A structured field described only in prose is one the model guesses at.

    That is what produced a one-node draft from a tool asking for 5-15: the
    schema said `array` and the shape lived in the description. `redraft` and
    `subdivide` both carry node objects, so both must declare their items.
    """
    from overtone.agent import llm

    for provider in ("openai", "anthropic"):
        for t in llm.tool_schemas(provider):
            spec = t["function"] if provider == "openai" else t
            params = spec["parameters" if provider == "openai" else "input_schema"]
            for k, v in params["properties"].items():
                if v.get("type") == "array":
                    assert "items" in v, f"{provider} {spec['name']}.{k}"
        for t in llm.draft_schema(provider):
            spec = t["function"] if provider == "openai" else t
            params = spec["parameters" if provider == "openai" else "input_schema"]
            assert "items" in params["properties"]["nodes"]

    # the two node-carrying actions agree on what a node is
    from overtone.agent.llm import _DRAFT_NODE, _SCHEMA
    assert _SCHEMA["redraft"][0]["nodes"]["items"] is _DRAFT_NODE
    assert _SCHEMA["subdivide"][0]["intermediates"]["items"] is _DRAFT_NODE


def test_approach_bookkeeping_survives_drafting_and_failed_redrafts(tmp_path,
                                                                    monkeypatch):
    """The record a later run reads to avoid repeating a route must be true.

    Four ways it was not: the drafted approach was overwritten by an
    initialiser that ran after it; a redraft that raised still rotated the
    approach; a redraft that reproduced the same sketch counted as a new route;
    and the approach still running at the end never reached the record.
    """
    from overtone import runner
    from overtone.agent import loop as looplib

    class Fail:
        status, proved, cpu, wall, output = "Timeout", False, 0.1, 0.1, ""

    monkeypatch.setattr(runner, "run", lambda *a, **k: Fail())

    class Agent:
        def draft(self, problem, axioms, conjecture, goal_name="goal"):
            return [{"op": "redraft", "approach": "first route", "keep": [],
                     "goal": goal_name,
                     "nodes": [{"name": "d1", "lhs": "commutator(X,X)",
                                "rhs": "additive_identity", "parents": []}],
                     "goal_parents": ["d1"]}]

        def act(self, state):
            if state.iteration == 0:      # a redraft that cannot apply
                return [{"op": "redraft", "approach": "never happened",
                         "keep": ["no_such_node"], "nodes": []}]
            if state.iteration == 1:      # a real change of route
                return [{"op": "redraft", "approach": "second route", "keep": [],
                         "nodes": [{"name": "k1", "lhs": "associator(X,X,Y)",
                                    "rhs": "additive_identity", "parents": []}],
                         "goal_parents": ["k1"]}]
            return []

    seed = Sketch.from_problem("RNG033-8", goal="rng033_goal")
    out = looplib.run_loop("RNG033-8", seed, Agent(), outdir=tmp_path,
                           max_iterations=4, directions=["--flatten-goal"])
    names = [t["approach"] for t in out["approaches_tried"]]
    assert names == ["first route", "second route"], names
    assert "never happened" not in names, \
        "a redraft that failed to apply must not rotate the approach"
    assert out["approaches_tried"][0]["iterations"] >= 1, \
        "the drafted approach must not be overwritten before it is recorded"


def test_review_sees_nodes_carried_by_subdivide_and_redraft():
    """An agent used `subdivide` exclusively -- 23 of them, 32 nodes, zero
    `add_node` -- and review inspected only `add_node` and `restate`. Every
    check was inert for that whole run: four axiom restatements and seven false
    lemmas walked straight through to the prover.
    """
    from overtone.agent import review

    seed = Sketch.from_problem("RNG033-8", goal="g")
    ctx = review.context_for("RNG033-8", seed, "g")
    axiom = ("commutator(X,Y)",
             "add(multiply(Y,X),additive_inverse(multiply(X,Y)))")

    sub = {"op": "subdivide", "name": "g", "intermediates": [
        {"name": "copy", "lhs": axiom[0], "rhs": axiom[1]},        # an axiom
        {"name": "alien", "lhs": "frobnicate(X)", "rhs": "X"},     # off-signature
        {"name": "ok", "lhs": "multiply(X,Y)", "rhs": "multiply(Y,X)"}]}
    kept, findings = review.review([sub], ctx)
    assert len(kept) == 1
    assert [n["name"] for n in kept[0]["intermediates"]] == ["ok"], \
        "bad intermediates are dropped; the rest of the subdivide survives"
    rejected = {f.node for f in findings if f.verdict == review.REJECT}
    assert rejected == {"copy", "alien"}

    # redraft carries nodes in a different field; both must be inspected
    red = {"op": "redraft", "approach": "x", "keep": [], "nodes": [
        {"name": "copy2", "lhs": axiom[0], "rhs": axiom[1]}]}
    kept, findings = review.review([red], ctx)
    assert kept == [], "a carrier whose every node is rejected is not an edit"
    assert any("every node in this redraft was rejected" in f.reason
               for f in findings)


def test_theory_reviewers_are_loaded_without_being_wired_by_a_caller():
    """`register` was never called outside tests, so the free-ring check ran in
    no real loop -- written, tested, and inert. A reviewer no production path
    loads is not a reviewer.
    """
    from overtone.agent import review

    assert any(f.__module__ == "overtone.freering" for f in review.REVIEWERS)

    seed = Sketch.from_problem("RNG033-8", goal="g")
    ctx = review.context_for("RNG033-8", seed, "g")
    # the exact shape the agent got wrong three times: it wanted Teichmuller
    _, findings = review.review([{
        "op": "add_node", "name": "wrong_teichmuller",
        "lhs": "associator(X,Y,multiply(Z,W))",
        "rhs": "add(multiply(associator(X,Y,Z),W),associator(multiply(X,Y),Z,W))",
    }], ctx)
    ring = [f for f in findings if f.reviewer == "free_ring"]
    assert ring and not ring[0].data["universal"], \
        "the note that would have flagged the false lemma must actually fire"


def test_an_approach_is_budgeted_against_the_goal_not_node_count(tmp_path,
                                                                 monkeypatch):
    """One run proved 27 nodes over ten iterations, so it never stalled -- and
    never changed approach either, spending 11,647 prover-seconds on one route.
    Proving nodes is not the objective; closing the goal is.

    Both halves of that are now enforced rather than advertised. A node proving
    that no probe asked for scores `inconclusive`, so the stall counter grows
    even while lemma after lemma verifies; and at `APPROACH_BUDGET` the
    controller withholds every edit that is not a redraft instead of printing a
    suggestion. This test used to assert `stalled == 0` throughout -- the very
    blind spot its own docstring describes.
    """
    from overtone import runner
    from overtone.agent import loop as looplib

    class R:
        cpu, wall, output = 0.1, 0.1, "ok"

        def __init__(self, path):
            # every lemma proves; the goal node and the final attempt never do.
            # `stalled` therefore stays 0 while the run gets no closer -- exactly
            # the case that hid for ten iterations and 11,647 prover-seconds.
            name = Path(str(path)).name
            self.proved = not name.startswith(("g.", "final."))
            self.status = "Unsatisfiable" if self.proved else "Timeout"

    monkeypatch.setattr(runner, "run", lambda path, *a, **k: R(path))
    seen = []

    class Agent:
        def act(self, state):
            seen.append((state.stalled, state.iterations_on_approach))
            lhs = "X"
            for _ in range(state.iteration + 2):
                lhs = f"multiply({lhs},Y)"
            return [{"op": "add_node", "name": f"n{state.iteration}",
                     "lhs": lhs, "rhs": "add(X,X)", "parents": []}]

    s = Sketch({"g": ("commutator(X,X)", "additive_identity", [])})
    # its own ledger: the shared one holds rows from earlier tests, and a
    # reused timeout would make "everything proves" quietly false
    out = looplib.run_loop("RNG033-8", s, Agent(), outdir=tmp_path,
                           max_iterations=6, directions=["--flatten-goal"],
                           draft=False, ledger=tmp_path / "l.jsonl")
    # Iteration 0 has no preceding edit to judge, so it is the baseline; from
    # there every turn proves a node the probe never asked for, and the stall
    # counter must reflect that the goal is no nearer.
    assert [st for st, _ in seen] == [0, 1, 2, 3, 4], \
        f"proving unrelated nodes must not read as progress: {seen}"
    assert [it for _, it in seen] == [0, 1, 2, 3, 4], \
        "the approach budget must still count up and force a change of route"
    assert out["stop_reason"] == "approach exhausted and the agent did not " \
                                 "redraft", out["stop_reason"]
    # The run stops at the budget rather than burning its last iterations on a
    # route the controller has already ruled out.
    assert out["iterations"] == 5, out["iterations"]


def test_the_free_ring_knows_additive_identity_is_zero():
    """The parser rejected any term naming the additive identity, so the
    reviewer returned no opinion on it. Seven nodes of one run went unchecked
    for that reason -- several of them members of the false-lemma family the
    reviewer exists to flag.
    """
    from overtone import freering

    A, M, I = "associator", "multiply", "additive_inverse"
    # true in every ring: an associator with a zero argument vanishes
    f, = freering.reviewer({"name": "z", "lhs": f"{A}(X,Y,additive_identity)",
                            "rhs": "additive_identity"}, None)
    assert f.data["universal"], "0 is the empty normal form, not an opaque symbol"

    # and a false statement naming it is now caught rather than skipped
    g, = freering.reviewer({"name": "bad", "lhs": f"{M}(X,additive_identity)",
                            "rhs": "X"}, None)
    assert not g.data["universal"]

    # a symbol that really is outside the language still gets no opinion
    assert freering.reviewer({"name": "n", "lhs": "frobnicate(X)",
                              "rhs": "X"}, None) == []


# ------------------------------------------------- what the RNG029-5 run needed

def test_a_statement_that_is_not_a_term_never_reaches_the_prover():
    """The exact node that ended the RNG029-5 agent run.

    Its two sides were `associator(X,Y,Z) = additive_identity` and
    `multiply(multiply(X,Y),Z) = multiply(X,multiply(Y,Z))` -- an implication
    written as an equation between two equations. Nothing caught it: `=` is not
    a token of the term grammar, so `safe_term` returned None, `alpha_key` fell
    back to a stripped string, and every eq_key-based reviewer compared that
    string and found no match. Twee rejected the input in 0.003s and the loop
    recorded `failed`, which is what a hard lemma reports too -- so the agent
    subdivided it, then removed it, and the run ended on the cycle detector
    having done no mathematics.
    """
    from overtone.agent import review

    seed = Sketch.from_problem("RNG029-5", goal="g")
    ctx = review.context_for("RNG029-5", seed, "g")
    bad = {"op": "add_node", "name": "assoc_zero_implies_right_assoc",
           "lhs": "associator(X,Y,Z) = additive_identity",
           "rhs": "multiply(multiply(X,Y),Z) = multiply(X,multiply(Y,Z))"}

    kept, findings = review.review([bad], ctx)
    assert kept == [], "the node must be withheld, not merely flagged"
    rejects = [f for f in findings if f.verdict == review.REJECT]
    assert {f.reviewer for f in rejects} == {"well_formed"}
    assert all("`=`" in f.reason for f in rejects), \
        "the reason must name what to fix, not just that it did not parse"


@pytest.mark.parametrize("lhs,why", [
    ("associator(X,Y)", "argument"),          # right symbol, wrong arity
    ("multiply(X,Y) junk", "trailing"),
    ("multiply(X,Y", "parenthes"),
])
def test_malformed_statements_are_withheld(lhs, why):
    """Arity is the subtler half: `associator(X,Y)` parses perfectly and is
    still not a term of this signature, so the name-only signature check passes
    it. It also used to crash `freering.reviewer`, which caught parse errors but
    not a known head applied to the wrong number of arguments -- a reviewer that
    raises ends a run mid-flight."""
    from overtone.agent import review

    seed = Sketch.from_problem("RNG029-5", goal="g")
    ctx = review.context_for("RNG029-5", seed, "g")
    kept, findings = review.review(
        [{"op": "add_node", "name": "n", "lhs": lhs,
          "rhs": "additive_identity"}], ctx)
    assert kept == []
    assert any(f.verdict == review.REJECT and why in f.reason
               for f in findings), [f.reason for f in findings]


def test_a_good_node_still_passes():
    """The reviewer must reject malformed statements without rejecting the
    lemmas worth having. The flexible law is not universal -- it needs
    alternativity -- and that is the normal case, not a defect."""
    from overtone.agent import review

    seed = Sketch.from_problem("RNG029-5", goal="g")
    ctx = review.context_for("RNG029-5", seed, "g")
    kept, findings = review.review(
        [{"op": "add_node", "name": "flexible",
          "lhs": "multiply(multiply(X,Y),X)",
          "rhs": "multiply(X,multiply(Y,X))"}], ctx)
    assert len(kept) == 1
    assert not [f for f in findings if f.verdict == review.REJECT]


def test_free_ring_rejects_only_a_contradicted_claim():
    """Refutation, never certification. "Needs the theory's own axioms" is the
    normal case for a useful lemma and must never be a rejection -- but a node
    that DECLARES itself universal and leaves a residue has failed a check its
    own stated grounds are exactly strong enough to settle."""
    from overtone.agent import review

    seed = Sketch.from_problem("RNG029-5", goal="g")
    ctx = review.context_for("RNG029-5", seed, "g")
    flexible = {"op": "add_node", "name": "flexible",
                "lhs": "multiply(multiply(X,Y),X)",
                "rhs": "multiply(X,multiply(Y,X))"}

    assert len(review.review([flexible], ctx)[0]) == 1, "unclaimed: kept"
    assert len(review.review(
        [{**flexible, "justification": "theory_specific"}], ctx)[0]) == 1
    kept, findings = review.review(
        [{**flexible, "justification": "universal"}], ctx)
    assert kept == [], "the claim is contradicted, so the node is withheld"
    bad, = [f for f in findings
            if f.verdict == review.REJECT and f.reviewer == "free_ring"]
    assert "theory_specific" in bad.reason, \
        "the fix must be named: it is a claim error, not a false lemma"

    # a node that really is universal, claiming so, must pass
    teich = {"op": "add_node", "name": "t", "justification": "universal",
             "lhs": "associator(X,Y,Z)",
             "rhs": "add(multiply(multiply(X,Y),Z),"
                    "additive_inverse(multiply(X,multiply(Y,Z))))"}
    assert not [f for f in review.review([teich], ctx)[1]
                if f.verdict == review.REJECT and f.reviewer == "free_ring"]


# ------------------------------------------------------------- cost and identity

def test_cost_separates_what_was_spent_from_what_is_charged():
    """`cpu_spent` counted ledger-reused rows at full price. One agent
    iteration reported 601.7s of node time that was 100% reuse, and another
    run's total rose 600.7s across an iteration whose two final attempts were
    both served from the ledger -- so the agent was told it had burned a budget
    the machine never touched."""
    rows = [{"cpu": 100.0, "proved": True},
            {"cpu": 300.0, "proved": False, "reused": True}]
    c = cost(rows)
    assert c["cpu"] == 400.0, "cold cost: what this sketch costs anyone"
    assert c["cpu_new"] == 100.0, "what this run actually spent"
    assert (c["n_reused"], c["n_new"]) == (1, 1)


def test_a_rename_is_not_a_new_sketch():
    """The digest hashed node NAMES. One run's two failing nodes came back
    renamed `..._zeroed`, failed again, then reverted -- nine iterations in a
    circle that the cycle detector read as nine fresh sketches."""
    a = Sketch({"n": ("multiply(X,Y)", "multiply(Y,X)", []),
                "g": ("associator(X,Y,Z)", "additive_identity", ["n"])})
    renamed = Sketch({"n_zeroed": ("multiply(X,Y)", "multiply(Y,X)", []),
                      "g": ("associator(X,Y,Z)", "additive_identity",
                            ["n_zeroed"])})
    assert a.digest() == renamed.digest()
    # ... and the identity is the equation, so variable names and orientation
    # do not make a new sketch either
    assert a.digest() == Sketch(
        {"n": ("multiply(Q,P)", "multiply(P,Q)", []),
         "g": ("associator(X,Y,Z)", "additive_identity", ["n"])}).digest()
    # a real change still registers
    assert a.digest() != Sketch(
        {"n": ("multiply(X,Y)", "multiply(Y,X)", []),
         "g": ("associator(X,Y,Z)", "additive_identity", [])}).digest()


# ----------------------------------------------------------- the target attempt


# NOTE: `dag.attempt` runs its two goal directions in a ProcessPoolExecutor, so
# a side-effect list appended to inside the fake runner lives in the child and
# never reaches the test. Assert on the identity-addressed `.p` inputs the run
# leaves on disk instead -- which is what those filenames are for.

def _final_inputs(outdir):
    return sorted(Path(outdir).glob("iter*/final.*.p"))


def test_the_target_gets_the_goals_declared_parents_not_everything_proved(
        tmp_path, monkeypatch):
    """The final attempt sent EVERY proved node as axioms, with the channel
    hardcoded, while `verify` chose per node through `channel_for`. That is the
    loose-bag-as-axioms configuration measured as a timeout on MVA005-1 and as
    worse-than-nothing on `teichmuller`, and it consumed 6,003.7s of one agent
    run's 10,423.9s and 1,201.4s of another's 1,441.9s.
    """
    from overtone import runner
    from overtone.agent import loop as looplib

    class R:
        cpu, wall, output = 0.1, 0.1, "ok"

        def __init__(self, path):
            name = Path(str(path)).name
            self.proved = not name.startswith(("rng029-5_goal.", "final."))
            self.status = "Unsatisfiable" if self.proved else "Timeout"

    monkeypatch.setattr(runner, "run", lambda path, *a, **k: R(path))
    # `off_route` proves but is NOT a parent of the goal, so it must not be
    # supplied; `on_route` is.
    # The goal node carries the problem's real conjecture, as a real sketch
    # does, so the goal is found by its statement rather than by its name.
    conj = problems.conjecture(problems.problem_path("RNG029-5"))
    s = Sketch({
        "on_route": ("multiply(multiply(X,Y),X)", "multiply(X,multiply(Y,X))", []),
        "off_route": ("commutator(X,X)", "additive_identity", []),
        "rng029-5_goal": (conj[0], conj[1], ["on_route"])})

    class Quiet:
        def act(self, state):
            return []

    out = looplib.run_loop("RNG029-5", s, Quiet(), outdir=tmp_path,
                           max_iterations=1, directions=["--flatten-goal"],
                           draft=False, ledger=tmp_path / "l.jsonl")
    inputs = _final_inputs(tmp_path)
    assert inputs, "the target was attempted"
    text = inputs[0].read_text()
    flat = text.replace(" ", "").replace("\n", "")
    assert "cnf(lemma" in text, f"the declared parent must be supplied: {text}"
    assert "multiply(multiply(X,Y),X)=multiply(X,multiply(Y,X))" in flat
    # the theory's axioms arrive by `include`, so `commutator` can appear here
    # only if `off_route` was supplied
    assert "commutator" not in text, \
        ("a node that proved but is not on the goal's declared route must not "
         "be supplied -- an irrelevant axiom is pure cost")
    assert out["history"][0]["target"]["support"] == ["on_route"]
    assert out["history"][0]["target"]["channel"] == "axioms", \
        "one declared parent is exactly the goal's parent set, so: axioms"


def test_an_unchanged_support_set_does_not_re_attempt_the_target(
        tmp_path, monkeypatch):
    """Identical support means identical input, so the ledger returns the
    recorded answer and `cost` charges the full budget for it again. Two agent
    runs spent 58% and 83% of their prover time on attempts, many of them exact
    repeats of one another."""
    from overtone import runner
    from overtone.agent import loop as looplib

    class R:
        cpu, wall, output = 5.0, 5.0, "ok"

        def __init__(self, path):
            name = Path(str(path)).name
            self.proved = not name.startswith(("g.", "final."))
            self.status = "Unsatisfiable" if self.proved else "Timeout"

    monkeypatch.setattr(runner, "run", lambda path, *a, **k: R(path))

    class AddsOffRoute:
        """Every edit adds a node the goal does not cite, so the target's
        declared support never changes."""
        def act(self, state):
            i = state.iteration
            lhs = "multiply(X,Y)"
            for _ in range(i):
                lhs = f"multiply({lhs},Y)"
            return [{"op": "add_node", "name": f"n{i}", "lhs": lhs,
                     "rhs": "add(X,X)", "parents": []}]

    # the goal needs a parent that PROVES, or there is no support and the
    # attempt is skipped as the bare baseline rather than carried
    conj = problems.conjecture(problems.problem_path("RNG029-5"))
    s = Sketch({"on_route": ("multiply(multiply(X,Y),X)",
                             "multiply(X,multiply(Y,X))", []),
                "rng029-5_goal": (conj[0], conj[1], ["on_route"])})
    out = looplib.run_loop("RNG029-5", s, AddsOffRoute(), outdir=tmp_path,
                           max_iterations=3, directions=["--flatten-goal"],
                           draft=False, ledger=tmp_path / "l.jsonl")
    assert len(_final_inputs(tmp_path)) == 1, \
        "the target must be asked once while its declared support is unchanged"
    assert out["iterations"] == 3, "the run itself continues normally"
    later = out["history"][-1]["target"]
    assert later["skipped_unchanged"] and later["cpu"] == 0.0, \
        "a carried answer must be charged nothing, not re-charged at full budget"


def test_contact_comes_from_the_attempt_and_not_from_a_directory_glob(tmp_path):
    """`_contact` globbed the iteration directory for the goal NODE's
    artifacts. The goal node was blocked for a whole agent run, so contact was
    None at every iteration -- while the target attempt in the same iteration
    left a failed search that scores perfectly well. And repeated runs share an
    `iterNN` directory: one such directory holds artifacts from five separate
    invocations, so the glob was also reading other runs' output.
    """
    from overtone.agent import loop as looplib

    out = tmp_path / "iter00"
    out.mkdir()
    real = out / "final.flatten-goal.abc.fail.out"
    real.write_text(
        "  Goal 1 (g): multiply(a, b) = multiply(b, a).\n"
        "  Axiom 9 (flattening): multiply3 = multiply(a, b).\n"
        "  Axiom 10 (flattening): multiply4 = multiply(b, a).\n"
        "(1.0) 1. add(multiply3, multiply4) -> zero1\n"
        "(2.0) 2. multiply3 -> other1\n")
    # a stale artifact from an earlier run of the loop: same directory, same
    # shape, no row pointing at it.
    (out / "final.flatten-goal.STALE.fail.out").write_text(
        "  Goal 1 (g): multiply(a, b) = multiply(b, a).\n"
        "(1.0) 1. multiply(a, b) -> junk1\n")

    rows = [{"node": "final", "direction": "--flatten-goal", "proved": False,
             "output": str(real)}]
    c = looplib._contact("final", rows)
    assert c == {"lhs": 2, "rhs": 1, "both": 1, "rules": 2}, c
    assert looplib._contact("final", []) is None, \
        "no row means no measurement; the stale file must never be found"
    # a row whose recorded artifact has since been removed is skipped, not
    # crashed on -- `_prior_artifact` can hand on a path from another run
    assert looplib._contact("final", [{"node": "final",
                                       "direction": "--flatten-goal",
                                       "proved": False,
                                       "output": str(out / "gone.out")}]) is None
    # a no-flatten run reports zeros that mean "not measurable", not "not
    # reaching the goal", and must not be averaged in
    assert looplib._contact("final", [{**rows[0],
                                       "direction": "--no-flatten-goal"}]) is None


def test_the_target_node_is_found_by_its_statement_not_its_name():
    """`_goal_of` matched `name.endswith("goal")` and nothing else. That was
    cosmetic while the target attempt took every proved node; once it takes the
    GOAL's declared parents, a sketch whose goal is named anything else supplies
    nothing at all -- a silent degradation, and worse than the behaviour being
    replaced."""
    from overtone.agent.loop import _target_node

    conj = problems.conjecture(problems.problem_path("RNG029-5"))
    lemma = ("multiply(multiply(X,Y),X)", "multiply(X,multiply(Y,X))", [])
    # by statement, under a name that says nothing
    s = Sketch({"lemma": lemma, "anything": (conj[0], conj[1], ["lemma"])})
    assert _target_node(s, "RNG029-5") == "anything"
    # by convention, when the statement does not match the problem
    s = Sketch({"lemma": lemma,
                "rng029-5_goal": ("commutator(X,X)", "additive_identity", [])})
    assert _target_node(s, "RNG029-5") == "rng029-5_goal"
    # by being the unique sink, when neither applies
    s = Sketch({"lemma": lemma,
                "sink": ("commutator(X,X)", "additive_identity", ["lemma"])})
    assert _target_node(s, "RNG029-5") == "sink"
    # ambiguous: two sinks, so no answer rather than an arbitrary one
    s = Sketch({"a": lemma, "b": ("commutator(X,X)", "additive_identity", [])})
    assert _target_node(s, "RNG029-5") is None


def test_a_failure_says_which_kind_it_was():
    """`failed_standalone`/`failed_with_parents` cost a full extra prover run
    per failure to separate two cases, and conflated these three -- which want
    opposite repairs. A saturated search is the one the retry could never turn
    around: parents are lemmas already entailed by the axioms, so removing them
    cannot make a closed search open."""
    from overtone.agent.loop import failure_kind

    assert failure_kind([{"result": "Timeout", "proved": False}]) == "timeout"
    assert failure_kind([{"result": "Satisfiable", "proved": False}]) == "saturated"
    assert failure_kind([{"result": "NoResult", "proved": False}]) == "error"
    assert failure_kind([{"result": "Error: boom", "proved": False}]) == "error"
    # A settled answer outranks a budget that merely ran out.
    assert failure_kind([{"result": "Timeout", "proved": False},
                         {"result": "CounterSatisfiable", "proved": False}]) \
        == "saturated"
    # A cancelled arm answered nothing, and a win is not a failure at all.
    assert failure_kind([{"result": "Cancelled", "proved": False}]) is None
    assert failure_kind([{"result": "Unsatisfiable", "proved": True}]) is None


# ---------------------------------------------- parents on probation

def _row(node, cpu, *, proved=True, unused=None, support=()):
    return {"node": node, "proved": proved, "cpu": cpu, "direction": "d",
            "channel": "axioms", "n_support": len(support),
            "result": "Unsatisfiable" if proved else "Timeout",
            "support": list(support), "unused_support": unused}


def test_uncited_parents_are_dropped_but_only_as_a_test():
    """164 of 307 parents supplied to proved runs here were never cited. That
    makes each a candidate, not a verdict -- twee's search depends on which
    rules enter the system, so removing one is a different search."""
    from overtone.agent.loop import probation_drops

    # `b` also feeds `other`, so dropping n's edge to it leaves it with a child.
    s = Sketch({"a": ("x", "y", []), "b": ("p", "q", []),
                "other": ("m", "k", ["b"]), "n": ("u", "v", ["a", "b"])})
    # The parents prove too. Only a GROUNDED parent may be dropped, so a fixture
    # that leaves them unproved is testing a case the controller must decline.
    rows = [_row("a", 1.0), _row("b", 1.0),
            _row("n", 40.0, unused=["b"], support=("a", "b"))]
    acts, probs = probation_drops(s, rows, target="goal", iteration=3)
    assert acts == [{"op": "set_parents", "name": "n", "parents": ["a"]}]
    assert len(probs) == 1
    assert probs[0].node == "n" and probs[0].dropped == ("b",)
    # The whole prior list, so a revert restores it verbatim rather than
    # reconstructing it from what happens to be declared later.
    assert probs[0].parents == ("a", "b") and probs[0].cpu == 40.0


def test_a_drop_that_would_orphan_its_parent_is_left_alone():
    """`_target_node` falls back to the unique sink, so orphaning a lemma can
    cost the run its target -- a far larger change than the one edge this is
    allowed to make. Removing the orphan too would be a structural edit the
    agent did not ask for."""
    from overtone.agent.loop import probation_drops

    s = Sketch({"a": ("x", "y", []), "only": ("p", "q", []),
                "n": ("u", "v", ["a", "only"])})
    rows = [_row("a", 1.0), _row("only", 1.0),
            _row("n", 40.0, unused=["only"], support=("a", "only"))]
    assert probation_drops(s, rows, target="goal") == ([], [])

    # Two nodes sharing one uncited parent must not orphan it between them:
    # the second drop sees the count the first already spent.
    s2 = Sketch({"a": ("x", "y", []), "sh": ("p", "q", []),
                 "n1": ("u", "v", ["a", "sh"]), "n2": ("s", "t", ["a", "sh"])})
    rows2 = [_row("a", 1.0), _row("sh", 1.0),
             _row("n1", 9.0, unused=["sh"], support=("a", "sh")),
             _row("n2", 9.0, unused=["sh"], support=("a", "sh"))]
    acts, probs = probation_drops(s2, rows2, target="goal")
    assert [p.node for p in probs] == ["n1"], "only the first may drop it"
    assert acts == [{"op": "set_parents", "name": "n1", "parents": ["a"]}]


def test_probation_leaves_the_target_and_the_probed_node_alone():
    """Stripping the target leaves nothing to supply the final attempt, which
    the loop already rejects. Editing the probed node in the same turn as the
    agent would make `score_outcome` credit the wrong edit."""
    from overtone.agent.loop import probation_drops

    s = Sketch({"a": ("x", "y", []), "goal": ("u", "v", ["a"]),
                "n": ("s", "t", ["a"]), "m": ("c", "d", ["a"])})
    rows = [_row("a", 1.0),
            _row("goal", 5.0, unused=["a"], support=("a",)),
            _row("n", 5.0, unused=["a"], support=("a",)),
            _row("m", 5.0, unused=["a"], support=("a",))]
    acts, probs = probation_drops(s, rows, target="goal", probe_node="n")
    assert [p.node for p in probs] == ["m"]
    assert [x["name"] for x in acts] == ["m"]
    # Nor a node already on probation, nor one whose drop was reverted before.
    _, again = probation_drops(s, rows, target="goal", probe_node="n",
                               active={"m"})
    assert again == []
    _, done = probation_drops(s, rows, target="goal", probe_node="n",
                              done={"m"})
    assert done == []


def test_a_drop_that_costs_time_is_put_back():
    """The asymmetry is deliberate: the drop was a guess, and keeping a guess
    that cost time is worse than paying one iteration to undo it."""
    from overtone.agent.loop import Probation, probation_verdicts

    p = Probation("n", ("b",), ("a", "b"), 10.0, 1)
    acts, kept, reverted = probation_verdicts([p], [_row("n", 25.0)])
    assert kept == [] and len(reverted) == 1
    assert acts == [{"op": "set_parents", "name": "n", "parents": ["a", "b"]}]
    assert "rose from 10.0s to 25.0s" in reverted[0][1]

    # Faster, so it stands and nothing is restored.
    acts, kept, reverted = probation_verdicts([p], [_row("n", 4.0)])
    assert acts == [] and reverted == [] and len(kept) == 1

    # Stopped proving: the certificate did not cite it, but the search needs it.
    acts, kept, reverted = probation_verdicts([p], [_row("n", 60.0, proved=False)])
    assert len(reverted) == 1 and "no longer proves" in reverted[0][1]
    assert acts[0]["parents"] == ["a", "b"]

    # Not re-run at all -- blocked behind a failed parent, most often. A verdict
    # on no evidence is the one thing worse than no verdict, so it stays pending.
    acts, kept, reverted = probation_verdicts([p], [_row("other", 1.0)])
    assert acts == [] and kept == [] and reverted == []


def test_probation_reverts_do_not_read_as_the_loop_going_in_a_circle():
    """Restoring parents reproduces the digest the sketch had before the drop.
    The cycle detector must not call that a circle -- it is the harness moving,
    the same case as a batch that review withheld in full."""
    from overtone.agent.loop import Probation, apply, probation_verdicts

    s = Sketch({"a": ("x", "y", []), "b": ("p", "q", []),
                "n": ("u", "v", ["a", "b"])})
    before = s.digest()
    dropped = apply(s, {"op": "set_parents", "name": "n", "parents": ["a"]})
    assert dropped.digest() != before
    p = Probation("n", ("b",), ("a", "b"), 10.0, 1)
    acts, _, reverted = probation_verdicts([p], [_row("n", 99.0)])
    assert reverted
    restored = dropped
    for act in acts:
        restored = apply(restored, act)
    assert restored.digest() == before, \
        "the revert must reproduce the earlier sketch exactly -- which is why "\
        "the cycle check has to be told to expect it"


# ------------------------------------------------------- scoring an edit

def _nodes(**kw):
    from overtone.agent.loop import NodeState
    return tuple(NodeState(n, "l", "r", (), st, cpu, None)
                 for n, (st, cpu) in kw.items())


def test_proving_a_node_nothing_asked_for_is_not_progress():
    """The loop's only notion of progress was a node newly proved. One run
    proved 27 nodes across ten iterations, never stalled, never changed
    approach, and spent 11,647 prover-seconds without a proof."""
    from overtone.agent.loop import score_outcome

    before = _nodes(a=("failed", None), b=("pending", None))
    after = _nodes(a=("failed", None), b=("proved", 0.1))

    asked = score_outcome({"node": "b", "expect": "prove"}, target={},
                          nodes=after, prev_nodes=before, applied=1)
    assert asked["outcome"] == "productive"

    unasked = score_outcome({"node": "a", "expect": "prove"}, target={},
                            nodes=after, prev_nodes=before, applied=1)
    assert unasked["outcome"] == "inconclusive", \
        "b proved, but the probe named a; that is not evidence about the route"

    undeclared = score_outcome({}, target={}, nodes=after, prev_nodes=before,
                               applied=1)
    assert undeclared["outcome"] == "inconclusive"


def test_a_fall_in_goal_contact_outranks_a_proved_node():
    """`both` is a veto: it fell 162 -> 102 across a refinement that made the
    problem harder while every other count rose. Nodes proving while the only
    rules that can close the goal disappear is exactly that shape."""
    from overtone.agent.loop import score_outcome

    before = _nodes(b=("pending", None))
    after = _nodes(b=("proved", 0.1))
    o = score_outcome({"node": "b", "expect": "prove"},
                      target={"contact_delta_both": -60}, nodes=after,
                      prev_nodes=before, applied=1)
    assert o["outcome"] == "regressed", \
        "the probe came true and the goal got further away; that is a regression"
    # a RISE endorses nothing: supplying no parents scores highest and does not
    # prove the goal
    o = score_outcome({"node": "b", "expect": "prove"},
                      target={"contact_delta_both": +200}, nodes=after,
                      prev_nodes=before, applied=1)
    assert o["outcome"] == "productive", "the probe, not the rise, is the reason"
    o = score_outcome({"node": "zzz", "expect": "prove"},
                      target={"contact_delta_both": +200}, nodes=after,
                      prev_nodes=before, applied=1)
    assert o["outcome"] == "inconclusive", "a rise on its own is never progress"


def test_a_slow_node_dropping_below_the_threshold_is_productive():
    """Budget is a diagnostic: a node at 32.9s was missing one node beneath it,
    and adding that node gave 18x."""
    from overtone.agent.loop import score_outcome

    before = _nodes(a=("slow", 32.9))
    after = _nodes(a=("proved", 2.1))
    o = score_outcome({"node": "a", "expect": "speed_up"}, target={},
                      nodes=after, prev_nodes=before, slow=30, applied=1)
    assert o["outcome"] == "productive"
    still = score_outcome({"node": "a", "expect": "speed_up"}, target={},
                          nodes=before, prev_nodes=before, slow=30, applied=1)
    assert still["outcome"] == "inconclusive"


def test_a_batch_that_was_entirely_withheld_is_invalid_not_stalled():
    """An agent whose every edit is rejected has not tried and failed -- it has
    not tried. Scoring that as a stall spends the approach budget on turns that
    never reached the prover."""
    from overtone.agent.loop import score_outcome

    o = score_outcome({}, target={}, nodes=(), prev_nodes=(), applied=0,
                      rejected=3)
    assert o["outcome"] == "invalid"


def test_a_regression_reverts_the_sketch_and_the_run_continues(
        tmp_path, monkeypatch):
    """RNG029-5 needed exactly this and did not have it: the agent undid its own
    bad edit by hand, which reproduced an earlier sketch, and the CYCLE DETECTOR
    ended the run -- 1,441.9s spent, no mathematics done. A regression must
    close the branch, not the run."""
    from overtone import runner
    from overtone.agent import loop as looplib

    contact = iter([{"lhs": 9, "rhs": 9, "both": 100, "rules": 9},
                    {"lhs": 9, "rhs": 9, "both": 40, "rules": 9},
                    {"lhs": 9, "rhs": 9, "both": 40, "rules": 9}])
    monkeypatch.setattr(looplib, "_contact",
                        lambda name, rows: next(contact, None)
                        if name == "final" else None)

    class R:
        cpu, wall, output = 0.1, 0.1, "ok"

        def __init__(self, path):
            name = Path(str(path)).name
            self.proved = not name.startswith(("rng029-5_goal.", "final."))
            self.status = "Unsatisfiable" if self.proved else "Timeout"

    monkeypatch.setattr(runner, "run", lambda path, *a, **k: R(path))
    seen = []

    class Agent:
        def act(self, state):
            seen.append((state.iteration, len(state.nodes),
                         state.outcome.get("outcome")))
            if state.iteration == 0:                    # the harmful edit
                return [{"op": "add_node", "name": "bad",
                         "lhs": "multiply(X,multiply(Y,Z))",
                         "rhs": "multiply(multiply(X,Y),Z)", "parents": [],
                         "probe": {"node": "bad", "expect": "prove"}}]
            if state.iteration == 1:
                return [{"op": "add_node", "name": "other",
                         "lhs": "commutator(X,Y)", "rhs": "commutator(Y,X)",
                         "parents": []}]
            return []

    conj = problems.conjecture(problems.problem_path("RNG029-5"))
    s = Sketch({"lemma": ("multiply(multiply(X,Y),X)",
                          "multiply(X,multiply(Y,X))", []),
                "rng029-5_goal": (conj[0], conj[1], ["lemma"])})
    out = looplib.run_loop("RNG029-5", s, Agent(), outdir=tmp_path,
                           max_iterations=3, directions=["--flatten-goal"],
                           draft=False, ledger=tmp_path / "l.jsonl")
    assert [o for _, _, o in seen][1] == "regressed", seen
    # the run kept going, and the harmful node was taken back out
    assert out["iterations"] >= 2, out["stop_reason"]
    assert "bad" not in out["final_sketch"], \
        "the node whose edit cut goal contact must not survive"
    assert "cycle" not in (out["stop_reason"] or ""), \
        "a revert must not read as the agent going in a circle"


# ------------------------------------------------- replaying the recorded runs

# `tests/fixtures/recorded_agent_edits.json` is the `history` of the two agent
# runs this generation of the loop was built to answer, promoted out of `logs/`
# (gitignored, and appended to across invocations) so the replay is tracked and
# reproducible. Their totals: RNG029-5 stopped after 2 iterations and 1,441.9s
# on a cycle; RNG033-8 after 10 iterations and 10,423.9s with no proof.
RECORDED = json.loads(
    (Path(__file__).parent / "fixtures" / "recorded_agent_edits.json").read_text())


def test_the_recorded_rng029_edit_is_now_withheld_before_any_prover_time():
    """The whole RNG029-5 run, replayed at the review gate.

    Its iteration-0 edit was a `subdivide` whose single intermediate had an
    equation on each side. It reached twee, which rejected it in 0.003s x 4
    runs and reported `failed` -- the same word a hard lemma gets. The agent
    then removed it, reproducing iteration 0's sketch, and the cycle detector
    ended the run.
    """
    from overtone.agent import review

    edits = RECORDED["RNG029-5"]["iterations"][0]["actions"]
    sub, = [a for a in edits if a["op"] == "subdivide"]
    assert sub["intermediates"][0]["lhs"].count("=") == 1, \
        "the fixture must still carry the real malformed statement"

    seed = Sketch.from_problem("RNG029-5", goal="rng029-5_goal")
    ctx = review.context_for("RNG029-5", seed, "rng029-5_goal")
    kept, findings = review.review(edits, ctx)
    assert kept == [], \
        "a subdivide whose every intermediate is rejected is not an edit"
    assert any(f.verdict == review.REJECT and f.reviewer == "well_formed"
               for f in findings)


def test_the_recorded_rng033_rename_loop_is_one_sketch_not_nine():
    """RNG033-8's two failing nodes were renamed `..._zeroed` and back across
    iterations 5-9. Under a name-based digest each rename was a fresh sketch, so
    the cycle detector saw nine new sketches and the run circled for 10
    iterations and 10,423.9s.

    Replaying the recorded edits, the digest must collapse the rename.
    """
    from overtone.agent.loop import apply

    names = set()
    for it in RECORDED["RNG033-8"]["iterations"]:
        for a in it["actions"]:
            for n in ([a] if a["op"] == "add_node" else
                      a.get("intermediates", []) + a.get("nodes", [])):
                if n.get("name"):
                    names.add(n["name"])
    assert {"commutator_product_right_expand",
            "commutator_product_right_expand_zeroed"} <= names, \
        "the fixture must still carry the rename"

    # the same statement under two names is one sketch
    body = ("add(commutator(multiply(X,Y),Z),W)", "multiply(X,Y)")
    a = Sketch({"n": (*body, []), "g": ("commutator(X,X)", "additive_identity",
                                        ["n"])})
    b = Sketch({"n_zeroed": (*body, []),
                "g": ("commutator(X,X)", "additive_identity", ["n_zeroed"])})
    assert a.digest() == b.digest()

    # and applying a rename to a real sketch does not change its identity
    renamed = apply(apply(a, {"op": "add_node", "name": "n2", "lhs": body[0],
                              "rhs": body[1], "parents": []}),
                    {"op": "remove_node", "name": "n2"})
    assert renamed.digest() == a.digest()


def test_target_contact_is_reported_as_a_delta(tmp_path):
    """The RNG033-8 refinement raised the rule count and both sides while
    cutting `both` from 162 to 102, and every number the agent could see
    endorsed it. A level invites maximising; only the change carries evidence,
    and only when it is negative."""
    from overtone.agent.loop import target_of

    def artifact(name, extra_rules):
        p = tmp_path / name
        p.write_text(
            "  Goal 1 (g): multiply(a, b) = multiply(b, a).\n"
            "  Axiom 9 (flattening): multiply3 = multiply(a, b).\n"
            "  Axiom 10 (flattening): multiply4 = multiply(b, a).\n"
            "(1.0) 1. add(multiply3, multiply4) -> zero1\n"
            + "".join(f"(2.0) {i + 2}. multiply3 -> other{i}\n"
                      for i in range(extra_rules)))
        return [{"node": "final", "direction": "--flatten-goal", "proved": False,
                 "result": "Timeout", "channel": "axioms", "support": ["a"],
                 "n_support": 1, "cpu": 300.0, "output": str(p)}]

    before = target_of(artifact("a.fail.out", 0))
    # more rules derived, more contact with the left side -- and `both` is
    # unchanged, so nothing here is progress
    after = target_of(artifact("b.fail.out", 5), before)
    assert before["contact"]["both"] == after["contact"]["both"] == 1
    assert after["contact"]["rules"] > before["contact"]["rules"]
    assert after["contact_delta_both"] == 0, \
        "deriving more rules is not getting closer"
    assert after["contact_previous"] == before["contact"]


def test_every_recorded_rng033_iteration_would_now_report_target_contact():
    """`State.contact` was None for the whole RNG029-5 run, and the target
    attempt -- the most expensive run of every iteration -- was recorded
    nowhere. `target_of` must produce a number from the attempt rows whenever a
    flatten-goal artifact exists, and say so plainly when one does not."""
    from overtone.agent.loop import target_of

    rows = [{"node": "final", "direction": "--flatten-goal", "proved": False,
             "result": "Timeout", "channel": "axioms", "support": ["a", "b"],
             "n_support": 2, "cpu": 300.0, "output": None},
            {"node": "final", "direction": "--no-flatten-goal", "proved": False,
             "result": "Timeout", "channel": "axioms", "support": ["a", "b"],
             "n_support": 2, "cpu": 300.0, "output": None}]
    t = target_of(rows)
    assert t["support"] == ["a", "b"] and t["channel"] == "axioms"
    assert t["cpu"] == 600.0 and t["proved"] is False
    assert "contact" not in t, "no artifact means no number, not a fake zero"
    assert target_of([]) == {}, "no attempt at all is not a measurement of zero"


def test_an_incomplete_exact_support_set_still_goes_to_the_axiom_channel():
    """`channel_for`'s equality test is right for a node being verified and
    wrong for the target. The target's support is the goal's declared parents
    intersected with what has PROVED, so while the sketch is incomplete it is a
    strict subset -- and the equality test then routes a handful of exact,
    on-route lemmas into the hint channel, where FINDINGS records they are worth
    nothing (alt12: five exact parents as axioms ~0.2s, as hints a timeout, and
    worse than supplying nothing).
    """
    from overtone.agent.dag import AXIOM_MAX, channel_for

    s = Sketch({"a": ("multiply(X,Y)", "multiply(Y,X)", []),
                "b": ("commutator(X,X)", "additive_identity", []),
                "g": ("associator(X,Y,Z)", "additive_identity", ["a", "b"])})
    assert channel_for(["a", "b"], s, "g") == "axioms", "the complete set"
    assert channel_for(["a"], s, "g") == "hints", \
        "a subset is not the node's parents, which is right when VERIFYING it"
    assert channel_for(["a"], s, "g", on_route=True) == "axioms", \
        "but for the target, an incomplete exact set is not a loose bag"
    # size still decides: a big bag is a big bag however on-route it is
    big = [f"n{i}" for i in range(AXIOM_MAX + 1)]
    assert channel_for(big, s, "g", on_route=True) == "hints"


def test_contact_is_not_compared_across_an_empty_support_run():
    """The empty-support attempt is the problem's own baseline, and FINDINGS
    records that supplying NOTHING scores the highest contact ever measured --
    371, against 171 for three parents and 162 for six -- while proving nothing.

    Using it as the reference would make the first edit that supplies a real
    lemma read as a large regression. This loop REVERTS regressions, so it would
    undo every genuine step and hold the sketch at the configuration already
    known to fail.
    """
    from overtone.agent.loop import target_of

    def rows(n_support, both, tmp):
        p = tmp
        p.write_text("  Goal 1 (g): multiply(a, b) = multiply(b, a).\n"
                     "  Axiom 9 (flattening): multiply3 = multiply(a, b).\n"
                     "  Axiom 10 (flattening): multiply4 = multiply(b, a).\n"
                     + "".join(f"(1.0) {i + 1}. add(multiply3, multiply4) -> z{i}\n"
                               for i in range(both)))
        return [{"node": "final", "direction": "--flatten-goal", "proved": False,
                 "result": "Timeout", "channel": "axioms",
                 "support": ["x"] * n_support, "n_support": n_support,
                 "cpu": 300.0, "output": str(p)}]

    import tempfile
    d = Path(tempfile.mkdtemp())
    baseline = target_of(rows(0, 9, d / "a.out"))          # nothing supplied
    real = target_of(rows(2, 3, d / "b.out"), baseline)    # two lemmas supplied
    assert baseline["contact"]["both"] > real["contact"]["both"], \
        "the fixture must reproduce the measured direction"
    assert "contact_delta_both" not in real, \
        "a fall against the supply-nothing run is not evidence of a regression"
    assert "contact_incomparable" in real

    # between two real support sets the delta is computed as usual
    later = target_of(rows(3, 1, d / "c.out"), real)
    assert later["contact_delta_both"] == -2


def test_the_target_is_not_attempted_with_no_support(tmp_path, monkeypatch):
    """With nothing supplied the attempt IS the problem's own baseline, and for
    any target worth a sketch that baseline is a recorded timeout -- RNG029-5
    resists 4000s in both directions.

    A gpt-5.4 run spent 600.5s of its 2045.3s of new prover time re-deriving
    that negative three iterations running, because the goal's two declared
    parents (`left_moufang_instance`, `target_bridge`) never proved: one of them
    rested on `shuffle_inner`, which states full associativity and is false in
    an alternative ring.
    """
    from overtone import runner
    from overtone.agent import loop as looplib

    class R:
        cpu, wall, output = 7.0, 7.0, ""
        proved, status = False, "Timeout"          # nothing proves

    monkeypatch.setattr(runner, "run", lambda path, *a, **k: R())

    class Quiet:
        def act(self, state):
            return []

    conj = problems.conjecture(problems.problem_path("RNG029-5"))
    s = Sketch({"never_proves": ("multiply(X,Y)", "multiply(Y,X)", []),
                "rng029-5_goal": (conj[0], conj[1], ["never_proves"])})
    out = looplib.run_loop("RNG029-5", s, Quiet(), outdir=tmp_path,
                           max_iterations=1, directions=["--flatten-goal"],
                           draft=False, ledger=tmp_path / "l.jsonl")
    assert not _final_inputs(tmp_path), \
        "no proved support means the attempt would be the bare baseline"
    # No attempt is not a measurement of zero: nothing here may claim a result,
    # a cost or a contact reading. `frontier_depth` is exempt and is the reason
    # this is not `== {}` -- it counts hops in the sketch, needs no run at all,
    # and is precisely the number worth having on an iteration this bare.
    target = out["history"][0]["target"]
    assert set(target) <= {"frontier_depth"}, target
    assert target.get("frontier_depth") == 1, \
        "one unproved obligation stands between the axioms and the goal"


def test_a_redraft_that_proposes_no_new_lemmas_is_not_a_new_approach():
    """A gpt-5.4 run redrafted with `nodes: []`, keeping the five nodes that had
    already proved and pointing the goal at one of them. Every one was an
    accelerant -- `associator(X,X,Y)=0`, `commutator(X,X)=0`, the flexible law --
    and FINDINGS records that an all-accelerant set cannot flip a problem.

    The loop counted it as a route change because deleting four nodes is a
    non-empty diff, so it reset the stall counter and bought four more
    iterations on a sketch strictly smaller than the one that had just failed.
    """
    from overtone.agent import review

    seed = Sketch.from_problem("RNG029-5", goal="rng029-5_goal")
    seed = Sketch({**seed.nodes,
                   "flexible_law": ("multiply(multiply(X,Y),X)",
                                    "multiply(X,multiply(Y,X))", [])},
                  given=seed.given)
    ctx = review.context_for("RNG029-5", seed, "rng029-5_goal")

    retreat = {"op": "redraft", "approach": "goal_via_flexibility_only",
               "keep": ["flexible_law"], "nodes": [],
               "goal_parents": ["flexible_law"]}
    kept, findings = review.review([retreat], ctx)
    assert kept == [], "a redraft that only deletes must be withheld"
    bad, = [f for f in findings if f.verdict == review.REJECT]
    assert "retreat" in bad.reason

    # a redraft carrying a real new lemma is untouched
    real = {**retreat, "nodes": [{"name": "waypoint",
                                  "lhs": "associator(X,Y,Z)",
                                  "rhs": "associator(Y,Z,X)"}]}
    kept, findings = review.review([real], ctx)
    assert len(kept) == 1 and kept[0]["nodes"][0]["name"] == "waypoint"


def test_a_wholly_withheld_batch_is_not_the_agent_giving_up(tmp_path,
                                                            monkeypatch):
    """`if not actions: stop_reason = "the agent proposed no further edits"` ran
    on the batch AFTER review, so one withheld proposal ended the run with a
    reason that was simply untrue -- the same class of false ending as the cycle
    detector firing on a revert. The agent must get its findings and a turn."""
    from overtone import runner
    from overtone.agent import loop as looplib

    class Fail:
        status, proved, cpu, wall, output = "Timeout", False, 0.1, 0.1, ""

    monkeypatch.setattr(runner, "run", lambda *a, **k: Fail())
    turns = []

    class Agent:
        def act(self, state):
            turns.append(state.iteration)
            if state.iteration == 0:
                # withheld: a verbatim copy of one of the problem's own axioms
                return [{"op": "add_node", "name": "dup",
                         "lhs": "add(X,Y)", "rhs": "add(Y,X)", "parents": []}]
            if state.iteration == 1:
                return [{"op": "add_node", "name": "real",
                         "lhs": "multiply(multiply(X,Y),X)",
                         "rhs": "multiply(X,multiply(Y,X))", "parents": []}]
            return []

    seed = Sketch.from_problem("RNG029-5", goal="rng029-5_goal")
    out = looplib.run_loop("RNG029-5", seed, Agent(), outdir=tmp_path,
                           max_iterations=4, directions=["--flatten-goal"],
                           draft=False, ledger=tmp_path / "l.jsonl")
    assert turns[:2] == [0, 1], \
        f"the agent must get a turn after its batch was withheld: {turns}"
    assert out["stop_reason"] != "the agent proposed no further edits" or \
        len(turns) > 2, out["stop_reason"]
    # and the finding that explains the withholding reached the next turn
    assert any(f["verdict"] == "reject"
               for h in out["history"] for f in h["findings"])


# ----------------------------------------- the two integration bugs of aug-13-02

def test_one_rejected_node_does_not_destroy_the_whole_draft():
    """The severest bug found so far. A draft proposed five nodes;
    `sandwich_shift` was correctly rejected for restating the goal; the other
    four survived review -- and `goal_parents` still named the rejected one, so
    `apply` raised on an unknown parent and the ENTIRE redraft was discarded.

    The run began with a bare goal and spent four of its first five iterations
    testing nothing. `repair` handled `parents` and had never handled
    `goal_parents` or `keep`.
    """
    from overtone.agent import review
    from overtone.agent.loop import apply

    seed = Sketch.from_problem("RNG029-5", goal="rng029-5_goal")
    ctx = review.context_for("RNG029-5", seed, "rng029-5_goal")
    conj = problems.conjecture(problems.problem_path("RNG029-5"))

    draft = {"op": "redraft", "approach": "flexible then reassociate",
             "keep": [], "goal_parents": ["sandwich_shift", "flexible_law"],
             "nodes": [
                 {"name": "flexible_law", "lhs": "multiply(multiply(X,Y),X)",
                  "rhs": "multiply(X,multiply(Y,X))"},
                 {"name": "assoc_cyclic", "lhs": "associator(X,Y,Z)",
                  "rhs": "associator(Y,Z,X)"},
                 # rejected: it restates the conjecture
                 {"name": "sandwich_shift", "lhs": conj[0], "rhs": conj[1]}]}

    kept, findings = review.review([draft], ctx)
    assert len(kept) == 1, "the good nodes must survive"
    survived = [n["name"] for n in kept[0]["nodes"]]
    assert survived == ["flexible_law", "assoc_cyclic"]
    assert kept[0]["goal_parents"] == ["flexible_law"], \
        "the reference to the rejected node must be dropped, not left to raise"
    assert any(f.reviewer == "repair" and "goal_parents" in f.reason
               for f in findings)

    # and the repaired action applies cleanly, which is the whole point
    out = apply(seed, kept[0])
    assert {"flexible_law", "assoc_cyclic"} <= set(out.nodes)
    assert out.nodes["rng029-5_goal"][2] == ["flexible_law"]


def test_a_draft_that_cannot_apply_tells_the_model_so(tmp_path, monkeypatch):
    """`_draft` caught the exception and only printed it, so the model's first
    turn began with a one-node sketch and no idea why."""
    from overtone import runner
    from overtone.agent import loop as looplib

    class Fail:
        status, proved, cpu, wall, output = "Timeout", False, 0.1, 0.1, ""

    monkeypatch.setattr(runner, "run", lambda *a, **k: Fail())
    seen = {}

    class Agent:
        def draft(self, problem, axioms, conjecture, goal_name="goal"):
            # A node with no `rhs` at all: review has no opinion on a side that
            # is absent, and `apply` then raises KeyError building the tuple.
            return [{"op": "redraft", "approach": "doomed", "keep": [],
                     "goal": goal_name,
                     "nodes": [{"name": "d1", "lhs": "commutator(X,X)",
                                "parents": []}],
                     "goal_parents": ["d1"]}]

        def act(self, state):
            seen.setdefault(state.iteration, list(state.findings))
            return []

    seed = Sketch.from_problem("RNG029-5", goal="rng029-5_goal")
    looplib.run_loop("RNG029-5", seed, Agent(), outdir=tmp_path,
                     max_iterations=1, directions=["--flatten-goal"],
                     ledger=tmp_path / "l.jsonl")
    first = seen.get(0, [])
    assert any("DISCARDED" in f.reason or "could not be applied" in f.reason
               for f in first), \
        f"the model must be told its draft was thrown away: {first}"


def test_a_rollback_hands_the_agent_the_sketch_that_now_exists(tmp_path,
                                                               monkeypatch):
    """After restoring `prev_sketch` the loop called the agent with the OLD
    state, describing the sketch it had just thrown away, while review ran
    against the restored one. A model proposed a node because its state said it
    was absent, and review rejected it as a duplicate because it had in fact
    just been restored."""
    from overtone import runner
    from overtone.agent import loop as looplib

    contact = iter([{"lhs": 9, "rhs": 9, "both": 100, "rules": 9},
                    {"lhs": 9, "rhs": 9, "both": 40, "rules": 9},
                    {"lhs": 9, "rhs": 9, "both": 40, "rules": 9}])
    monkeypatch.setattr(looplib, "_contact",
                        lambda name, rows: next(contact, None)
                        if name == "final" else None)

    class R:
        cpu, wall, output = 0.1, 0.1, "ok"

        def __init__(self, path):
            name = Path(str(path)).name
            self.proved = not name.startswith(("rng029-5_goal.", "final."))
            self.status = "Unsatisfiable" if self.proved else "Timeout"

    monkeypatch.setattr(runner, "run", lambda path, *a, **k: R(path))
    saw = []

    class Agent:
        def act(self, state):
            saw.append({n.name for n in state.nodes})
            if state.iteration == 0:
                return [{"op": "remove_node", "name": "keeper"}]
            return []

    conj = problems.conjecture(problems.problem_path("RNG029-5"))
    s = Sketch({"keeper": ("multiply(multiply(X,Y),X)",
                           "multiply(X,multiply(Y,X))", []),
                "rng029-5_goal": (conj[0], conj[1], ["keeper"])})
    looplib.run_loop("RNG029-5", s, Agent(), outdir=tmp_path,
                     max_iterations=2, directions=["--flatten-goal"],
                     draft=False, ledger=tmp_path / "l.jsonl")
    assert len(saw) >= 2, saw
    assert "keeper" in saw[1], (
        "after the removal was reverted the agent must see `keeper` present -- "
        f"it was handed the discarded sketch instead: {saw[1]}")


def test_candidates_drop_what_can_never_become_a_lemma():
    """Ranking by raw twee score surfaces plumbing the sketch already has
    (PLAN.md). A model was shown additive-identity rules already present as
    axioms and run-local `sk_dag_* -> multiply2` aliases, which cannot be
    reusable lemmas because the names die with the run."""
    from overtone.agent.loop import _useful

    s = Sketch({"known": ("multiply(X,Y)", "multiply(Y,X)", [])})
    bodies = [
        "sk_dag_2 -> multiply2",                       # run-local
        "multiply(sk_dag_3, associator2) -> multiply3",  # run-local
        "multiply(X, Y) -> multiply(Y, X)",            # already a node
        "multiply(Y, X) -> multiply(X, Y)",            # the same node, flipped
        "associator(X, Y, Z) -> additive_identity",    # genuinely new
        "no arrow here",
    ]
    out = _useful(bodies, s, limit=12)
    assert out == ["associator(X, Y, Z) = additive_identity"], out


def test_lhs_holding_a_whole_equation_is_split_not_lost():
    """A model wrote the equation into `lhs` and omitted `rhs` seven times
    across two iterations of one run, losing the node every time.
    `well_formed` caught it correctly but reported the case it was written for
    -- an implication between two equations -- so the reason described something
    the model had not done, and it repeated the mistake.

    One `=` and a missing `rhs` is unambiguous. Two are not.
    """
    from overtone.agent import review

    seed = Sketch.from_problem("RNG029-5", goal="rng029-5_goal")
    ctx = review.context_for("RNG029-5", seed, "rng029-5_goal")

    # verbatim from the run
    kept, findings = review.review(
        [{"op": "add_node", "name": "assoc_x_y_zx_zero",
          "lhs": "associator(X,Y,multiply(Z,X)) = additive_identity"}], ctx)
    assert len(kept) == 1
    assert kept[0]["lhs"] == "associator(X,Y,multiply(Z,X))"
    assert kept[0]["rhs"] == "additive_identity"
    assert any(f.reviewer == "repair" and "whole equation" in f.reason
               for f in findings)

    # two equations is the ambiguous implication case and stays rejected
    kept, _ = review.review(
        [{"op": "add_node", "name": "x",
          "lhs": "associator(X,Y,Z) = additive_identity",
          "rhs": "multiply(multiply(X,Y),Z) = multiply(X,multiply(Y,Z))"}], ctx)
    assert kept == []
    # an explicit rhs is never overridden
    kept, _ = review.review(
        [{"op": "add_node", "name": "y", "lhs": "multiply(X,Y)",
          "rhs": "multiply(Y,X)"}], ctx)
    assert kept[0]["lhs"] == "multiply(X,Y)"


def test_orphaning_the_goal_warns_loudly_but_keeps_the_work():
    """Two failures, and the fix for the first caused the second.

    Repair drops goal parents naming rejected nodes; dropping them ALL leaves
    the goal connected to nothing, so the target is never attempted -- one run
    went four iterations that way with 24 proved lemmas unused. Withholding the
    whole redraft over it was then tried and is worse: the next run lost two
    nodes out of a good draft, one of them the only named goal parent, and the
    ENTIRE decomposition was discarded back to a bare goal. `peak_proved` fell
    from 20-24 to 1.

    So the edit stands, the warning is explicit, and the loop repeats the
    complaint every turn (see `run_loop`) until the goal is wired up.
    """
    from overtone.agent import review

    seed = Sketch.from_problem("RNG029-5", goal="rng029-5_goal")
    ctx = review.context_for("RNG029-5", seed, "rng029-5_goal")
    conj = problems.conjecture(problems.problem_path("RNG029-5"))

    doomed = {"op": "redraft", "approach": "BK waypoint", "keep": [],
              # both NAMED GOAL PARENTS are rejected below; a third node
              # survives, so this is not the all-nodes-rejected case
              "goal_parents": ["lhs_reduce_via_bk", "rhs_reduce_via_bk"],
              "nodes": [{"name": "lhs_reduce_via_bk",
                         "lhs": conj[0], "rhs": conj[1]},      # restates goal
                        {"name": "rhs_reduce_via_bk",
                         "lhs": "add(X,Y)", "rhs": "add(Y,X)"},  # an axiom
                        {"name": "unrelated_but_fine",
                         "lhs": "multiply(multiply(X,Y),X)",
                         "rhs": "multiply(X,multiply(Y,X))"}]}
    kept, findings = review.review([doomed], ctx)
    assert len(kept) == 1, "the good nodes must survive; discarding them is worse"
    assert [n["name"] for n in kept[0]["nodes"]] == ["unrelated_but_fine"]
    assert kept[0]["goal_parents"] == []
    orphan, = [f for f in findings if f.data.get("orphaned")]
    assert orphan.verdict == review.WARN and "NO parents" in orphan.reason

    # dropping SOME goal parents is still a repair, not a rejection
    ok = {**doomed, "goal_parents": ["lhs_reduce_via_bk", "survivor"],
          "nodes": [{"name": "survivor", "lhs": "multiply(multiply(X,Y),X)",
                     "rhs": "multiply(X,multiply(Y,X))"},
                    {"name": "lhs_reduce_via_bk",
                     "lhs": conj[0], "rhs": conj[1]}]}
    kept, findings = review.review([ok], ctx)
    assert len(kept) == 1 and kept[0]["goal_parents"] == ["survivor"]


def test_a_disconnected_goal_is_reported_every_turn(tmp_path, monkeypatch):
    """Nothing complained about a goal with no parents: the target is skipped as
    a bare baseline, so the run looks cheap and busy while testing nothing. One
    run sat that way for four iterations with 24 lemmas proved and never
    supplied to anything. The complaint now repeats every turn and names the
    proved nodes available to fix it."""
    from overtone import runner
    from overtone.agent import loop as looplib

    class R:
        cpu, wall, output = 0.1, 0.1, "ok"

        def __init__(self, path):
            name = Path(str(path)).name
            self.proved = not name.startswith(("rng029-5_goal.", "final."))
            self.status = "Unsatisfiable" if self.proved else "Timeout"

    monkeypatch.setattr(runner, "run", lambda path, *a, **k: R(path))
    saw = []

    class Agent:
        def act(self, state):
            saw.append([f for f in state.findings
                        if f.reviewer == "controller"])
            return []

    conj = problems.conjecture(problems.problem_path("RNG029-5"))
    # a proved lemma the goal does not cite -- exactly the wasted-work shape
    s = Sketch({"orphaned_lemma": ("multiply(multiply(X,Y),X)",
                                   "multiply(X,multiply(Y,X))", []),
                "rng029-5_goal": (conj[0], conj[1], [])})
    looplib.run_loop("RNG029-5", s, Agent(), outdir=tmp_path,
                     max_iterations=1, directions=["--flatten-goal"],
                     draft=False, ledger=tmp_path / "l.jsonl")
    assert saw and saw[0], "the disconnected goal must reach the agent"
    f = saw[0][0]
    assert f.verdict == "reject" and "NO parents" in f.reason
    assert f.data["proved_available"] == ["orphaned_lemma"], \
        "the fix must be named, not just the fault"


def test_a_duplicate_is_a_renamed_lemma_not_a_lost_one():
    """Rejecting a duplicate deleted every edge pointing at it.

    A model proposed a lemma the sketch already had under another name; review
    rejected it; then `repair` dropped that name from every parent list that
    cited it -- injecting the wrong edges FINDINGS calls more costly than
    missing ones, while the lemma sat in the sketch the whole time. One run did
    this across three redrafts.
    """
    from overtone.agent import review

    s = Sketch({
        "flexible_law": ("multiply(multiply(X,Y),X)",
                         "multiply(X,multiply(Y,X))", []),
        "rng029-5_goal": problems.conjecture(
            problems.problem_path("RNG029-5")) + ([],)})
    ctx = review.context_for("RNG029-5", s, "rng029-5_goal")

    batch = [
        # the same equation as `flexible_law`, under a new name
        {"op": "add_node", "name": "flex_restated",
         "lhs": "multiply(multiply(A,B),A)", "rhs": "multiply(A,multiply(B,A))"},
        # ... and a node that depends on it
        {"op": "add_node", "name": "downstream",
         "lhs": "associator(X,Y,X)", "rhs": "additive_identity",
         "parents": ["flex_restated"]},
    ]
    kept, findings = review.review(batch, ctx)
    assert [a["name"] for a in kept] == ["downstream"]
    assert kept[0]["parents"] == ["flexible_law"], \
        "the edge must be rewired to the node that states it, not deleted"
    assert any(f.reviewer == "duplicates_a_node"
               and f.data.get("existing") == "flexible_law" for f in findings)
    assert any(f.data.get("rewired") == ["flex_restated"] for f in findings)


def test_a_node_restating_the_goal_is_never_aliased_to_the_goal():
    """The alias must not make the goal its own parent -- a cycle produced by a
    repair. A goal restatement is rejected outright, as before."""
    from overtone.agent import review

    conj = problems.conjecture(problems.problem_path("RNG029-5"))
    s = Sketch({"lemma": ("multiply(X,Y)", "multiply(Y,X)", []),
                "rng029-5_goal": (conj[0], conj[1], [])})
    ctx = review.context_for("RNG029-5", s, "rng029-5_goal")
    kept, _ = review.review(
        [{"op": "add_node", "name": "sandwich_shift",
          "lhs": conj[0], "rhs": conj[1]},
         {"op": "add_node", "name": "downstream", "lhs": "associator(X,Y,X)",
          "rhs": "additive_identity", "parents": ["sandwich_shift"]}], ctx)
    assert [a["name"] for a in kept] == ["downstream"]
    assert kept[0]["parents"] == [], \
        "the reference is dropped, not rewired to the goal"


def test_a_redraft_keeps_the_existing_nodes_its_new_lemmas_depend_on():
    """Review and `apply` disagreed about what a redraft's parents may name, and
    it deadlocked a whole run.

    Review checks parents against the CURRENT sketch, so any existing name
    passes. `apply` then rebuilds from `keep` plus the proposed nodes and deletes
    everything else -- so a parent naming a real node the model did not list in
    `keep` becomes an unknown parent and the redraft raises. Six consecutive
    iterations proposed a waypoint citing `assoc_prod_flexible_rewrite`, which
    existed and was unkept; every redraft raised; the sketch never changed; the
    approach never rotated, because rotation requires an APPLIED redraft; and the
    loop span on `retry_after_rejection` with zero new prover work.

    The closure must be transitive: a node pulled into `keep` brings its own
    parents, or it dangles one level down.
    """
    from overtone.agent import review
    from overtone.agent.loop import apply

    conj = problems.conjecture(problems.problem_path("RNG029-5"))
    s = Sketch({
        "granddad": ("commutator(X,X)", "additive_identity", []),
        "parent": ("associator(X,X,Y)", "additive_identity", ["granddad"]),
        "rng029-5_goal": (conj[0], conj[1], []),
    })
    ctx = review.context_for("RNG029-5", s, "rng029-5_goal")

    redraft = {"op": "redraft", "approach": "waypoint", "keep": [],
               "goal_parents": ["waypoint"],
               "nodes": [{"name": "waypoint",
                          "lhs": "multiply(multiply(X,Y),X)",
                          "rhs": "multiply(X,multiply(Y,X))",
                          # exists, but is not in `keep`
                          "parents": ["parent"]}]}
    kept, findings = review.review([redraft], ctx)
    assert len(kept) == 1
    # `parent` AND its own parent `granddad` must both be carried
    assert set(kept[0]["keep"]) >= {"parent", "granddad"}, kept[0]["keep"]
    pulled, = [f for f in findings if f.data.get("kept")]
    assert set(pulled.data["kept"]) == {"parent", "granddad"}

    # and the whole point: it applies, instead of raising
    out = apply(s, kept[0])
    assert out.nodes["waypoint"][2] == ["parent"]
    assert "granddad" in out.nodes


def test_a_loop_spinning_without_prover_work_stops_and_says_so(tmp_path,
                                                               monkeypatch):
    """One run burned six model calls and six iterations at a constant
    `cpu_new`, because every redraft raised in `apply` and nothing ever ran. It
    reported no error and stopped only on `max_iterations`.

    Every real iteration verifies at least one node or attempts the target, so
    no new CPU across three consecutive turns means the loop is broken, not that
    the problem is hard.
    """
    from overtone import runner
    from overtone.agent import loop as looplib

    class Fail:
        status, proved, cpu, wall, output = "Timeout", False, 0.1, 0.1, ""

    monkeypatch.setattr(runner, "run", lambda *a, **k: Fail())
    turns = []

    class Spinner:
        """Every edit names a node that does not exist, so `apply` raises and
        the sketch never changes -- the shape that deadlocked the real run."""
        def act(self, state):
            turns.append(state.iteration)
            return [{"op": "set_parents", "name": "no_such_node",
                     "parents": []}]

    conj = problems.conjecture(problems.problem_path("RNG029-5"))
    s = Sketch({"lemma": ("multiply(multiply(X,Y),X)",
                          "multiply(X,multiply(Y,X))", []),
                "rng029-5_goal": (conj[0], conj[1], ["lemma"])})
    out = looplib.run_loop("RNG029-5", s, Spinner(), outdir=tmp_path,
                           max_iterations=12, directions=["--flatten-goal"],
                           draft=False, ledger=tmp_path / "l.jsonl")
    assert "spinning" in out["stop_reason"], out["stop_reason"]
    assert out["iterations"] < 12, \
        f"it must stop early, not run out the budget: {out['iterations']}"


def test_permutative_rules_are_parsed_not_mangled():
    """twee writes an oriented rule `l -> r` and a permutative one `l <-> r`.
    Splitting on `->` alone lands INSIDE the second arrow, leaving a left side
    ending in `<` -- the model was shown the literal string
    `multiply(a,b) < = multiply(b,a)`. One iteration's artifacts carried 34 such
    rules across three files."""
    from overtone.agent.loop import _useful

    s = Sketch({"n": ("multiply(X,Y)", "multiply(Y,X)", [])})
    out = _useful(["associator(X,Y,Z) -> additive_identity",
                   "commutator(a,b) <-> commutator(b,a)",
                   "no arrow here"], s, limit=12)
    assert out == ["associator(X,Y,Z) = additive_identity",
                   "commutator(a,b) = commutator(b,a)"], out
    assert not any("<" in c for c in out)


def test_no_candidate_from_a_real_artifact_is_malformed():
    """The check that matters: run the filter over a recorded search and assert
    nothing containing an arrow fragment reaches the model."""
    from overtone import proofs
    from overtone.agent.loop import _useful

    art = (Path(__file__).parent / "fixtures" / "permutative_rules.out")
    rules = proofs.derived_rules(art.read_text())
    bodies = [r["body"] for r in sorted(rules.values(), key=lambda r: r["score"])]
    assert any("<->" in b for b in bodies), "the fixture must carry the case"
    out = _useful(bodies, Sketch({"n": ("multiply(X,Y)", "multiply(Y,X)", [])}),
                  limit=12)
    assert out and not any("<" in c or "->" in c for c in out), out


# ----------------------------------------------------- deriving a waypoint

def test_polarization_derives_the_alternating_laws():
    """The move that turns an axiom into a new identity. `associator(X,X,Y)=0`
    polarized in X is `associator(X,W,Y) + associator(W,X,Y) = 0` --
    `alt12_additive`, a node of the successful sketch that agent runs
    repeatedly failed to prove."""
    from overtone import freering as F

    left = F.parse("associator(X,X,Y)")
    got = F.polarize(left, "X", "W")
    want = F.add(F.assoc(F.V("X"), F.V("W"), F.V("Y")),
                 F.assoc(F.V("W"), F.V("X"), F.V("Y")))
    assert got == want

    right = F.parse("associator(X,Y,Y)")
    got = F.polarize(right, "Y", "W")
    want = F.add(F.assoc(F.V("X"), F.V("Y"), F.V("W")),
                 F.assoc(F.V("X"), F.V("W"), F.V("Y")))
    assert got == want


def test_a_certificate_must_be_integral():
    """`express` solves over the rationals and will return 1/2. Dividing by 2
    is valid only in a ring without 2-torsion, which the alternative-ring axioms
    do not give -- and on the real RNG029-5 system the rational solver does
    return halves, so this is not hypothetical."""
    from fractions import Fraction
    from overtone import freering as F

    a, b, c = F.V("a"), F.V("b"), F.V("c")
    doubled = F.add(F.assoc(a, b, c), F.assoc(a, b, c))
    # over Q the answer is 1/2; over Z there is none
    assert F.express(F.assoc(a, b, c), [("d", doubled)]) == \
        [("d", Fraction(1, 2))]
    cert = F.certificate(F.assoc(a, b, c), [("d", doubled)])
    assert cert["coefficients"] is None
    assert "divid" in cert["reason"], cert["reason"]
    # and the honest case still solves
    cert = F.certificate(doubled, [("d", F.assoc(a, b, c))])
    assert cert["coefficients"] == {"d": 2} and cert["integral"]


def test_the_goal_decomposes_into_associator_obligations():
    """The result the generation path exists for. RNG029-5's residual is two
    universal associator terms, so the conjecture is equivalent to one
    obligation -- and supplying that obligation takes the target from a 4000s
    timeout in both directions to 6.7s.

    Derived from the goal's syntax alone: no theory content, no donor, no
    retrieval, nothing from `scripts/rng_dag.py`.
    """
    from overtone import freering as F

    conj = problems.conjecture(problems.problem_path("RNG029-5"))
    d = F.decompose(conj[0], conj[1])
    assert len(d["terms"]) == 2, d["terms"]

    # the decomposition is exact: the bridge's residual IS the goal's
    x, y, z = F.V("VCX"), F.V("VCY"), F.V("VCZ")
    bridge = F.expand(F.assoc(x, y, F.mul(z, x)), F.mul(x, F.assoc(y, z, x)))
    assert bridge == F.expand(F.parse(conj[0]), F.parse(conj[1]))


def test_the_certificate_reconstructs_the_target_exactly():
    """A solver bug here would manufacture unsound waypoints, so the
    combination is rebuilt by INDEX -- not by label, which a collision could
    hide -- and compared to the residual."""
    from overtone import freering as F

    conj = problems.conjecture(problems.problem_path("RNG029-5"))
    target = F.expand(F.parse(conj[0]), F.parse(conj[1]))
    ids = F.theory_identities("RNG029-5")
    assert {n for n, _ in ids} == {"left_alternative", "right_alternative"}, \
        "only the axioms the normal form does NOT encode should survive"

    cons = F.consequences(ids, sorted(F.variables(target)), F.degree(target),
                          limit=20000)
    labels = [l for l, _ in cons]
    assert len(labels) == len(set(labels)), "labels must identify elements"
    cert = F.certificate(target, cons)
    assert cert["integral"] and cert["coefficients"]

    idx = {l: i for i, l in enumerate(labels)}
    acc = {}
    for label, k in cert["coefficients"].items():
        for m, v in cons[idx[label]][1].items():
            acc[m] = acc.get(m, 0) + k * v
    assert {m: v for m, v in acc.items() if v} == dict(target)


def test_the_alternating_laws_reach_twice_the_moufang_residual():
    """Why RNG029-5's last step is hard, stated exactly.

    Closing the PROVED alternating laws under bounded consequence spans
    `2 * bridge` over the integers but not `bridge` itself -- it sits in the
    rational span with a factor of 1/2. Recovering the residual needs a ring
    without 2-torsion, which RNG003-0 does not assume, so the cheap linear route
    provably cannot finish.

    This is also the test that would fail if the integrality check were dropped:
    over the rationals the same system "solves" and yields an unsound waypoint.
    """
    from overtone import freering as F

    A = "associator"
    proved = [
        ("alt12", F.expand(F.parse(f"add({A}(X,Y,Z),{A}(Y,X,Z))"),
                           F.parse("additive_identity"))),
        ("alt23", F.expand(F.parse(f"add({A}(X,Y,Z),{A}(X,Z,Y))"),
                           F.parse("additive_identity"))),
        ("cyclic", F.expand(F.parse(f"{A}(X,Y,Z)"), F.parse(f"{A}(Y,Z,X)"))),
    ]
    conj = problems.conjecture(problems.problem_path("RNG029-5"))
    target = F.expand(F.parse(conj[0]), F.parse(conj[1]))
    cons = F.consequences(proved, sorted(F.variables(target)),
                          F.degree(target), limit=20000)

    once = F.certificate(target, cons)
    assert once["coefficients"] is None, "the residual itself must NOT be reachable"
    assert once["rational"], "but it is in the rational span"
    assert "divid" in once["reason"]

    twice = F.certificate(F.add(target, target), cons)
    assert twice["coefficients"] and twice["integral"], \
        "twice the residual IS an integer combination"


# ------------------------------------------------- deriving the whole sketch

def test_the_derived_sketch_names_the_parents_each_derivation_uses():
    """The point of deriving rather than drafting.

    `alt12` is unproven at 60s standalone and proves in 0.02s given the three
    lemmas its polarization actually uses -- the linearised axiom instance and
    additivity in the two argument positions the repeated variable occupies.
    Eight agent runs never found that parent set. The derivation knows it
    because it used it.
    """
    from overtone.agent.derive import derive_sketch

    s, notes = derive_sketch("RNG029-5")
    left = s.nodes["left_alternative_polar"]
    assert left[0] == "add(associator(X,Z,Y),associator(Z,X,Y))"
    assert set(left[2]) == {"lin_left_alternative",
                            "associator_add_1", "associator_add_2"}
    # right-alternativity repeats its variable in arguments 2 and 3, so it
    # keys on the other two additivity lemmas
    right = s.nodes["right_alternative_polar"]
    assert set(right[2]) == {"lin_right_alternative",
                             "associator_add_2", "associator_add_3"}
    assert notes, "provenance must travel with the sketch"


def test_the_derived_sketch_reduces_the_goal_to_one_obligation():
    """The goal's only parent is the bridge, and the bridge is the goal's own
    residual over universal associator terms. Supplying it takes RNG029-5 from a
    4000s timeout in both directions to 6.7s."""
    from overtone import freering as F
    from overtone.agent.derive import derive_sketch

    s, _ = derive_sketch("RNG029-5")
    goal = "rng029-5_goal"
    assert s.nodes[goal][2] == ["bridge"]

    # the bridge is exactly equivalent to the conjecture, checked by expansion
    bl, br, _ = s.nodes["bridge"]
    gl, gr, _ = s.nodes[goal]
    assert F.expand(F.parse(bl), F.parse(br)) == \
        F.expand(F.parse(gl), F.parse(gr))


def test_the_bridge_is_not_given_every_derived_lemma():
    """Handing it all eleven claims is the loose-bag-as-axioms configuration
    measured here as ruinous. Two mechanical filters: the `lin_*` instances are
    scaffolding for the polarizations, and a lemma about an operator the bridge
    never mentions cannot be on its derivation."""
    from overtone.agent.dag import channel_for
    from overtone.agent.derive import derive_sketch

    s, _ = derive_sketch("RNG029-5")
    parents = s.nodes["bridge"][2]
    assert not any(p.startswith("lin_") for p in parents), parents
    assert not any("commutator" in p for p in parents), \
        "the bridge has no commutator in it"
    assert len(parents) < len(s.claims()) - 1
    assert channel_for(parents, s, "bridge") == "axioms", \
        "a small exact parent set goes through the axiom channel"


def test_derivation_reads_only_the_problem_file():
    """No donor, no stored sketch, no `scripts/rng_dag.py`. The axioms are
    stated in `multiply` form, so the polarizations are read off the associator
    rendering rather than the axiom as written."""
    from overtone.agent.derive import derive_sketch

    named = problems.named_axioms(problems.problem_path("RNG029-5"))
    assert named["left_alternative"] == (
        "multiply(multiply(X,X),Y)", "multiply(X,multiply(X,Y))"), \
        "the fixture must keep the multiply-form statement"

    s, _ = derive_sketch("RNG029-5")
    # and it still finds the repetition, via the associator form
    assert "left_alternative_polar" in s.nodes
    assert s.nodes["lin_left_alternative"][0].startswith("associator(add(")


def test_derived_symmetries_carry_the_lemmas_that_certify_them():
    """`associator_perm_120` is cyclicity, and it is derived: a two-term integer
    certificate over the polarizations, not a fact recalled from the successful
    sketch."""
    from overtone.agent.derive import derive_sketch

    s, _ = derive_sketch("RNG029-5")
    perm = s.nodes["associator_perm_120"]
    assert perm[0] == "associator(X,Y,Z)" and perm[1] == "associator(Y,Z,X)"
    assert set(perm[2]) == {"left_alternative_polar", "right_alternative_polar"}


def test_rewind_only_applies_to_the_committed_sketch():
    """`--derive` and `--seed` build a different sketch, and the recorded edits
    name the committed one's nodes. Rewinding either raised
    `KeyError: 'teichmuller'` before a single node was verified."""
    import importlib.util
    from overtone import config
    from overtone.agent.derive import derive_sketch

    spec = importlib.util.spec_from_file_location(
        "loopcli", config.ROOT / "scripts" / "loop.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)

    derived, _ = derive_sketch("RNG029-5")
    with pytest.raises(KeyError):
        cli.rewind(derived)          # the shape the guard exists to prevent


def test_lhs_holding_the_equation_is_recovered_when_rhs_is_also_given():
    """The commonest way a good node is lost, and the earlier repair refused it.

    A model writes `lhs: "associator(X,Y,Y) = additive_identity"` AND supplies
    the correct `rhs` separately. The first version of this repair bailed
    whenever `rhs` was set, so `well_formed` rejected all of them -- seven nodes
    in one run, six of which were confirmable because the right half and the
    supplied `rhs` agree exactly.
    """
    from overtone.agent import review

    seed = Sketch.from_problem("RNG029-5", goal="rng029-5_goal")
    ctx = review.context_for("RNG029-5", seed, "rng029-5_goal")

    def one(lhs, rhs=None):
        a = {"op": "add_node", "name": "n", "lhs": lhs}
        if rhs is not None:
            a["rhs"] = rhs
        kept, _ = review.review([a], ctx)
        return (kept[0]["lhs"], kept[0]["rhs"]) if kept else None

    # confirmed: rhs repeats the right half (verbatim from the run)
    assert one("associator(X,Y,Y) = additive_identity", "additive_identity") \
        == ("associator(X,Y,Y)", "additive_identity")
    assert one("associator(Y,multiply(Z,X),X) = associator(multiply(Z,X),X,Y)",
               "associator(multiply(Z,X),X,Y)") \
        == ("associator(Y,multiply(Z,X),X)", "associator(multiply(Z,X),X,Y)")
    # a truncation: the text after `=` is not a term, so `rhs` is authoritative
    assert one("associator(VCY,VCZ,multiply(VCZ,VCX)) =?", "additive_identity") \
        == ("associator(VCY,VCZ,multiply(VCZ,VCX))", "additive_identity")
    # rhs missing
    assert one("multiply(X,Y) = multiply(Y,X)") == \
        ("multiply(X,Y)", "multiply(Y,X)")
    # two different claims about the same side: not recoverable
    assert one("multiply(X,Y) = multiply(Y,X)", "associator(X,Y,Z)") is None


def test_an_open_route_to_the_goal_names_the_whole_dead_chain():
    """A failed ancestor used to remove the goal from the run entirely -- no
    attempt, no artifact, no contact, so no regression verdict and no revert.
    One run subdivided its single obligation at iteration 0, replacing seven
    proved parents with three that failed, and spent nine iterations blind.

    The goal is attempted regardless now, so what this reports is not "cannot
    run" but "cannot be SUPPLIED": every name here is a lemma the target attempt
    will not receive. `given` axioms are never in it -- they are in the problem
    file already -- and neither is a node that proved.
    """
    from overtone.agent.dag import unproved_ancestors
    from overtone.agent.loop import _blocking

    s = Sketch({
        "ok": ("multiply(multiply(X,Y),X)", "multiply(X,multiply(Y,X))", []),
        "bad": ("associator(X,Y,Z)", "additive_identity", []),
        "mid": ("commutator(X,Y)", "commutator(Y,X)", ["bad"]),
        "rng029-5_goal": ("multiply(X,Y)", "multiply(Y,X)", ["mid", "ok"]),
    })
    v = {"proved": {"ok"}}
    # nearest first, and the whole dead chain is named
    assert _blocking(s, "rng029-5_goal", v) == ["mid", "bad"]
    assert unproved_ancestors(s, "rng029-5_goal", {"ok"}) == ["mid", "bad"]
    # once the chain proves, nothing is reported
    assert _blocking(s, "rng029-5_goal", {"proved": {"ok", "mid", "bad"}}) == []
    # The walk prunes at an established node rather than continuing past it,
    # and that is sound only because `v["proved"]` is GROUNDED-only: grounding
    # is a least fixed point, so nothing can be in it whose own ancestors are
    # not. `{ok, mid}` without `bad` is a state grounding cannot produce -- if
    # it could, pruning at `mid` would hide `bad` and the chain would lie.
    from overtone.agent.dag import grounding
    rows = [{"node": "bad", "proved": False, "cpu": 9.0, "result": "Timeout"},
            {"node": "mid", "proved": True, "cpu": 1.0, "channel": "axioms",
             "support": ["bad"], "used_support": ["bad"]},
            {"node": "ok", "proved": True, "cpu": 1.0, "channel": "axioms",
             "support": [], "used_support": None}]
    ground, conditional = grounding(s, rows)
    assert ground == {"ok"} and conditional["mid"] == ("bad",)
    assert _blocking(s, "rng029-5_goal", {"proved": ground}) == ["mid", "bad"]


# ------------------------------------------------------- proxy goal contact

def _contact_row(tmp, both, node="final", direction="--flatten-goal"):
    p = tmp / f"{node}.{both}.fail.out"
    p.write_text("  Goal 1 (g): multiply(a, b) = multiply(b, a).\n"
                 "  Axiom 9 (flattening): multiply3 = multiply(a, b).\n"
                 "  Axiom 10 (flattening): multiply4 = multiply(b, a).\n"
                 + "".join(f"(1.0) {i + 1}. add(multiply3, multiply4) -> z{i}\n"
                           for i in range(both)))
    return {"node": node, "direction": direction, "proved": False,
            "result": "Timeout", "channel": "axioms", "support": ["x"],
            "n_support": 1, "cpu": 60.0, "output": str(p)}


def test_contact_falls_back_to_the_deepest_node_that_actually_ran(tmp_path):
    """A derived sketch makes an unattempted target the normal case: the goal's
    only parent is the bridge, so until the bridge proves there is no support,
    no attempt, no contact and therefore no veto. One run went ten iterations
    that way.

    The bridge is an exact restatement of the conjecture, so its own
    verification artifact measures the same content -- and it costs nothing,
    because that run already happened.
    """
    from overtone.agent.loop import proxy_contact, target_of

    s = Sketch({"deep": ("commutator(X,Y)", "commutator(Y,X)", []),
                "bridge": ("associator(X,Y,Z)", "additive_identity", ["deep"]),
                "rng029-5_goal": ("multiply(X,Y)", "multiply(Y,X)", ["bridge"])})
    rows = [_contact_row(tmp_path, 7, node="bridge")]
    v = {"proved": set()}                      # nothing proved: goal is blocked

    got = proxy_contact(s, "rng029-5_goal", rows, v)
    assert got and got[0] == "bridge" and got[1]["both"] == 7
    assert got[2] == 1, "the bridge is one step from the goal"

    t = target_of([], None, got)               # no attempt at all
    assert t["contact"]["both"] == 7
    assert t["contact_source"] == "bridge"
    assert "proxy" in t["contact_is_proxy"] or "closest" in t["contact_is_proxy"]


def test_a_proxy_reading_is_never_differenced_against_another_source(tmp_path):
    """The bridge scored `both: 0` at 60s where real target attempts on the same
    problem scored 152 and 21. Differencing across that boundary would invent
    regressions, and this loop reverts them."""
    from overtone.agent.loop import target_of

    first = target_of([], None, ("bridge", {"lhs": 1, "rhs": 1, "both": 9,
                                            "rules": 10}, 1))
    # same source: a delta is meaningful
    same = target_of([], first, ("bridge", {"lhs": 1, "rhs": 1, "both": 4,
                                            "rules": 10}, 1))
    assert same["contact_delta_both"] == -5

    # different proxy node: no delta, and it says why
    other = target_of([], first, ("deeper", {"lhs": 1, "rhs": 1, "both": 4,
                                             "rules": 10}, 2))
    assert "contact_delta_both" not in other
    assert "bridge" in other["contact_incomparable"]

    # a real attempt after a proxy is also not comparable
    real = target_of([_contact_row(tmp_path, 3)], first, None)
    assert real["contact_source"] == "final"
    assert "contact_delta_both" not in real


def test_the_proxy_prefers_the_goal_itself_when_the_goal_ran(tmp_path):
    """Nearest to the conjecture wins: the proxy exists because the goal was
    blocked, not to replace it when it runs."""
    from overtone.agent.loop import proxy_contact

    s = Sketch({"bridge": ("associator(X,Y,Z)", "additive_identity", []),
                "rng029-5_goal": ("multiply(X,Y)", "multiply(Y,X)", ["bridge"])})
    rows = [_contact_row(tmp_path, 2, node="rng029-5_goal"),
            _contact_row(tmp_path, 9, node="bridge")]
    got = proxy_contact(s, "rng029-5_goal", rows, {"proved": {"bridge"}})
    assert got[0] == "rng029-5_goal" and got[1]["both"] == 2 and got[2] == 0


def test_pushing_the_frontier_away_from_the_goal_is_a_regression():
    """The signal two derived-sketch runs needed and neither had.

    Both started at depth 1 -- the single obligation itself running and leaving
    a search -- subdivided it at iteration 0 into intermediates that did not
    prove, dropped to depth 2, and never recovered. Contact barely moved and its
    sources churned, so no delta was ever comparable; the depth says plainly, at
    the iteration it happens, that nothing is aimed at the goal any more.
    """
    from overtone.agent.loop import frontier_retreat, score_outcome

    def at(d):
        # `frontier_depth`, not `contact_depth`: the scheduler attempts every
        # claim now, so the goal almost always leaves an artifact and the
        # distance-to-a-reading would sit at 0 through exactly the edit this
        # catches. `dag.frontier_depth` counts hops to the furthest ungrounded
        # node instead and reproduces the same 1 -> 2 on both runs.
        return {"frontier_depth": d, "contact": {"both": 0}}

    assert frontier_retreat(at(2), at(1)) == (1, 2)
    o = score_outcome({}, target=at(2), nodes=(), prev_nodes=(), applied=1,
                      retreat=(1, 2))
    assert o["outcome"] == "regressed" and "1 step(s) away to 2" in o["why"]


def test_the_frontier_guard_does_not_punish_repair_or_reward_severing():
    """Two guards, both learned from the runs.

    A decrease is never a retreat, so repairing the chain is free. And depth 0
    is not a baseline to fall from: one run reached it by DISCONNECTING the
    goal, which makes it verify standalone and score the best contact of the
    run -- so treating that as the mark to hold would reward severing the goal
    and punish reattaching it.
    """
    from overtone.agent.loop import frontier_retreat

    def at(d):
        # `frontier_depth`, not `contact_depth`: the scheduler attempts every
        # claim now, so the goal almost always leaves an artifact and the
        # distance-to-a-reading would sit at 0 through exactly the edit this
        # catches. `dag.frontier_depth` counts hops to the furthest ungrounded
        # node instead and reproduces the same 1 -> 2 on both runs.
        return {"frontier_depth": d, "contact": {"both": 0}}

    assert frontier_retreat(at(1), at(2)) is None, "repair is free"
    assert frontier_retreat(at(2), at(2)) is None, "standing still is not a fall"
    assert frontier_retreat(at(1), at(0)) is None, \
        "0 came from a disconnected goal; reattaching must not be punished"
    assert frontier_retreat(at(4), at(None)) is None, "nothing to compare"
    assert frontier_retreat(at(None), at(1)) is None
    assert frontier_retreat({}, at(1)) is None and frontier_retreat(at(2), None) is None


# ------------------------------------------------- scheduling without layers

def test_a_node_whose_parent_failed_is_still_attempted(tmp_path, monkeypatch):
    """The barrier removal, stated as behaviour.

    `verify` used to walk topological layers and run a node only once every
    parent had proved, so one failed ancestor removed an entire subtree from the
    run -- and when that subtree held the goal there was no attempt, no
    artifact, and no goal contact, so the loop's only veto went quiet. One run
    spent nine iterations that way.

    The rule was buying less than it looked: `scope` supplies a node's declared
    parents whether or not they proved, so the input bytes and the verdict are
    identical either way. All it decided was WHEN the question got asked.
    """
    from overtone import runner
    from overtone.agent import dag

    class R:
        def __init__(self, ok):
            self.proved = ok
            self.status = "Unsatisfiable" if ok else "Timeout"
            self.cpu = self.wall = 1.0
            self.output = "x"

    # `a` never proves; `b` and `c` hang off it.
    monkeypatch.setattr(runner, "run",
                        lambda path, *a, **k: R(not Path(path).name.startswith("a.")))
    s = Sketch({"a": ("multiply(X,X)", "add(X,X)", []),
                "b": ("commutator(X,Y)", "commutator(Y,X)", ["a"]),
                "c": ("associator(X,X,Y)", "additive_identity", ["b"])})
    out = dag.verify("RNG029-5", s, outdir=tmp_path, budget=1, workers=1,
                     ledger=tmp_path / "l.jsonl")

    assert {r["node"] for r in out["results"]} == {"a", "b", "c"}, \
        "every claim is attempted, not just the reachable ones"
    for n in ("b", "c"):
        inputs = sorted(tmp_path.glob(f"{n}.*.p"))
        assert inputs and all("parent" in f.read_text() for f in inputs), \
            f"{n} must still be run WITH its declared parent supplied"


def test_a_proof_resting_on_an_unproved_lemma_is_conditional_not_proved(
        tmp_path, monkeypatch):
    """It verified, so it is a real implication -- and it is not a theorem of
    this problem until what it assumes is proved. Counting it would flatter a
    run whose assumptions never discharge, and supplying it to the target would
    prove the conjecture from an assumption."""
    from overtone import runner
    from overtone.agent import dag

    class R:
        def __init__(self, ok):
            self.proved = ok
            self.status = "Unsatisfiable" if ok else "Timeout"
            self.cpu = self.wall = 1.0
            self.output = "x"

    monkeypatch.setattr(runner, "run",
                        lambda path, *a, **k: R(not Path(path).name.startswith("a.")))
    s = Sketch({"a": ("multiply(X,X)", "add(X,X)", []),
                "b": ("commutator(X,Y)", "commutator(Y,X)", ["a"])})
    out = dag.verify("RNG029-5", s, outdir=tmp_path, budget=1, workers=1,
                     ledger=tmp_path / "l.jsonl")

    assert out["conditional"] == {"b": ["a"]}
    assert out["n_conditional"] == 1
    assert "b" in out["all_proved"], "it did prove, and the record says so"
    assert "b" not in out["grounded"] and "b" not in out["proved"]
    assert out["n_proved"] == 0, "grounded only -- the headline must not inflate"
    assert "b" in out["missing"], "not established is not the same as proved"


def test_grounding_reads_the_run_not_the_declared_parents():
    """Three ways the two differ, each of which would ground the wrong node."""
    from overtone.agent.dag import Sketch, grounding

    s = Sketch({"a": ("x", "y", []), "b": ("p", "q", ["a"])})
    fail_a = {"node": "a", "proved": False, "cpu": 60.0, "result": "Timeout"}

    def b(**kw):
        return {"node": "b", "proved": True, "cpu": 1.0, "channel": "axioms",
                "support": ["a"], "used_support": None, **kw}

    # 1. The hints channel adds nothing to the axiom set, so it assumes nothing.
    assert grounding(s, [fail_a, b(channel="hints")])[0] == {"b"}

    # 2. A certificate that never cites the assumption is a proof without it.
    assert grounding(s, [fail_a, b(used_support=[])])[0] == {"b"}

    # 3. ...but only when attribution is actually available. `None` means NOT
    # ATTRIBUTED -- a failed run, the hint channel, a missing artifact -- and
    # reading it as "used nothing" would ground a node on no evidence at all.
    ground, conditional = grounding(s, [fail_a, b(used_support=None)])
    assert ground == set() and conditional == {"b": ("a",)}


def test_a_conditional_chain_names_everything_it_rests_on():
    """Nearest first, and through a node that never proved: stopping at the
    first dead assumption would report a shorter dependency than the sketch
    actually claims."""
    from overtone.agent.dag import Sketch, grounding

    s = Sketch({"a": ("x", "y", []), "b": ("p", "q", ["a"]),
                "c": ("u", "v", ["b"])})
    rows = [{"node": "a", "proved": False, "cpu": 60.0, "result": "Timeout"},
            {"node": "c", "proved": True, "cpu": 1.0, "channel": "axioms",
             "support": ["b"], "used_support": ["b"]}]
    ground, conditional = grounding(s, rows)
    assert ground == set()
    # `b` was never even run, so the chain continues through what it is
    # DECLARED to rest on.
    assert conditional["c"] == ("b", "a")


def test_grounding_promotes_a_whole_subtree_at_once():
    """Least fixed point: a promotion grounds everything downstream of it, and
    a node grounded late is not re-run -- both searches were handed the same
    equations, so the verdict was always about the same question."""
    from overtone.agent.dag import Sketch, grounding

    s = Sketch({"a": ("x", "y", []), "b": ("p", "q", ["a"]),
                "c": ("u", "v", ["b"])})
    rows = [{"node": "a", "proved": True, "cpu": 1.0, "channel": "axioms",
             "support": [], "used_support": None},
            {"node": "b", "proved": True, "cpu": 1.0, "channel": "axioms",
             "support": ["a"], "used_support": ["a"]},
            {"node": "c", "proved": True, "cpu": 1.0, "channel": "axioms",
             "support": ["b"], "used_support": ["b"]}]
    assert grounding(s, rows) == ({"a", "b", "c"}, {})


def test_ready_nodes_are_scheduled_before_speculative_ones():
    """A priority, not a gate. Every claim is attempted; this only decides what
    starts first when there are more of them than workers, and a run that
    cannot start everything should spend the box on the conjecture rather than
    on whatever sorts first alphabetically."""
    from overtone.agent.dag import Sketch, _priority, _route_to

    s = Sketch({"off": ("x", "y", []), "onroute": ("p", "q", []),
                "mid": ("u", "v", ["onroute"]),
                "zz_goal": ("m", "k", ["mid"])})
    route = _route_to(s, "zz_goal")
    assert route == {"zz_goal", "mid", "onroute"}

    order = sorted(s.claims(),
                   key=lambda n: _priority(n, s, proved=set(), route=route))
    # Both parentless nodes are ready; the one on the route goes first. `mid`
    # and the goal are speculative, and are ordered by route then name.
    assert order == ["onroute", "off", "mid", "zz_goal"]

    # Once `onroute` proves, `mid` becomes ready and overtakes the off-route
    # node that is still merely parentless.
    order = sorted(["off", "mid"],
                   key=lambda n: _priority(n, s, proved={"onroute"}, route=route))
    assert order == ["mid", "off"]


def test_the_pool_is_refilled_rather_than_drained_at_a_layer_boundary(tmp_path,
                                                                     monkeypatch):
    """A barrier idles the box whenever a tier is narrower than `workers`.

    The shape here is the one that punished it: one independent node plus a
    chain of four, so every layer after the first held exactly one node and no
    layered schedule could ever run more than two at once. The fake runner
    blocks until three DISTINCT nodes are in flight, so this can only pass if
    speculative work is filling the free slots -- and deadlocks into a timeout
    if it is not.
    """
    import time
    from overtone import runner
    from overtone.agent import dag

    seen = tmp_path / "inflight"
    seen.write_text("")

    class R:
        proved, status, cpu, wall, output = True, "Unsatisfiable", 0.1, 0.1, "x"

    def fake(path, flags, budget, **kw):
        node = Path(path).name.split(".")[0]
        with open(seen, "a") as f:
            f.write(node + "\n")
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if len(set(seen.read_text().split())) >= 3:
                break
            time.sleep(0.02)
        return R()

    monkeypatch.setattr(runner, "run", fake)
    nodes = {"solo": ("multiply(X,X)", "add(X,X)", [])}
    prev = None
    for i in range(4):
        name = f"chain{i}"
        nodes[name] = (f"multiply(X{i},Y)", "add(X,X)", [prev] if prev else [])
        prev = name
    s = Sketch(nodes)

    out = dag.verify("RNG029-5", s, outdir=tmp_path, budget=30, workers=3,
                     directions=["--flatten-goal"], ledger=tmp_path / "l.jsonl")
    assert len(set(seen.read_text().split())) >= 3, \
        "three nodes never ran at once: the pool is still draining per tier"
    assert out["n_proved"] == 5


def test_frontier_depth_counts_hops_to_the_furthest_open_node():
    """The structural successor to the artifact depth, and the measurement it
    has to preserve: both derived-sketch runs opened at 1 -- one obligation,
    running and failing -- subdivided it into intermediates that did not prove,
    and went to 2.
    """
    from overtone.agent.dag import Sketch, frontier_depth

    before = Sketch({"scaffold": ("x", "y", []),
                     "obligation": ("p", "q", ["scaffold"]),
                     "goal": ("u", "v", ["obligation"])})
    assert frontier_depth(before, "goal", {"scaffold"}) == 1

    after = Sketch({"scaffold": ("x", "y", []),
                    "i1": ("a", "b", ["scaffold"]), "i2": ("c", "d", ["scaffold"]),
                    "obligation": ("p", "q", ["i1", "i2"]),
                    "goal": ("u", "v", ["obligation"])})
    assert frontier_depth(after, "goal", {"scaffold"}) == 2, \
        "the subdivide pushed the frontier one hop further from the conjecture"

    # Repairing it is free, and a fully grounded route reads 0.
    assert frontier_depth(after, "goal",
                          {"scaffold", "i1", "i2", "obligation"}) == 0


def test_a_conditional_proof_is_not_progress_and_is_not_supplied(tmp_path,
                                                                 monkeypatch):
    """Three guards on one footgun, end to end.

    A node that proved on an unproved assumption must not satisfy the probe that
    predicted it, must not be handed to the run against the real conjecture, and
    must say so where the agent can read it.
    """
    from overtone import runner
    from overtone.agent import loop as looplib
    from overtone.agent.dag import Sketch
    from overtone.agent.loop import NodeState, score_outcome

    # 1. It does not satisfy an `expect: "prove"` probe.
    cond = NodeState("b", "p", "q", ("a",), "conditional", 1.0, "d",
                     assumes=("a",))
    was = NodeState("b", "p", "q", ("a",), "pending", None, None)
    o = score_outcome({"node": "b", "expect": "prove"}, target={}, nodes=(cond,),
                      prev_nodes=(was,), applied=1)
    assert o["outcome"] == "inconclusive" and "conditional" in o["why"]

    # 2. It never reaches the target attempt, and 3. it is reported.
    class R:
        def __init__(self, ok):
            self.proved = ok
            self.status = "Unsatisfiable" if ok else "Timeout"
            self.cpu = self.wall = 1.0
            self.output = "x"

    monkeypatch.setattr(
        runner, "run",
        lambda path, *a, **k: R(not Path(path).name.startswith("dead.")))

    class Quiet:
        def act(self, state):
            self.seen = state
            return []

    conj = problems.conjecture(problems.problem_path("RNG029-5"))
    s = Sketch({"dead": ("multiply(X,X)", "add(X,X)", []),
                "shaky": ("commutator(X,Y)", "commutator(Y,X)", ["dead"]),
                "rng029-5_goal": (conj[0], conj[1], ["shaky"])})
    agent = Quiet()
    out = looplib.run_loop("RNG029-5", s, agent, outdir=tmp_path,
                           max_iterations=1, directions=["--flatten-goal"],
                           draft=False, ledger=tmp_path / "l.jsonl")

    rec = out["history"][0]
    assert rec["n_proved"] == 0 and rec["n_conditional"] == 2
    assert not _final_inputs(tmp_path), \
        "a conditional lemma must never be supplied to the real conjecture"
    node = {n.name: n for n in agent.seen.nodes}["shaky"]
    assert node.status == "conditional" and node.assumes == ("dead",)
    assert any(f.node == "shaky" and "not yet a theorem" in f.reason
               for f in agent.seen.findings)


# --------------------------------------------------------------- evidence bank

def _artifact(tmp, name, rules, *, proof=()):
    """A stand-in twee output: a search trace, then optionally a proof."""
    lines = [f"({1.0 + i / 10:.1f}) {i + 1}. {r}" for i, r in enumerate(rules)]
    if proof:
        lines.append("Here is a proof.")
        lines += [f"Lemma {i + 1}: {a} = {b}." for i, (a, b) in enumerate(proof)]
        lines.append("Goal 1 (g): a = b.")
        lines.append("= { by lemma 1 }")
    lines.append("RESULT: Unsatisfiable")
    p = tmp / name
    p.write_text("\n".join(lines) + "\n")
    return p


def _row_for(path, node, direction="--flatten-goal", support=()):
    return {"node": node, "direction": direction, "output": str(path),
            "proved": False, "result": "Timeout", "cpu": 60.0,
            "channel": "axioms", "support": list(support)}


def test_the_bank_mines_both_directions_instead_of_stopping_at_the_first(tmp_path):
    """`_candidates` had `if out: break`, so a node's second goal direction was
    never read. On the measured artifact that was 1,043 usable equations thrown
    away, from the search aimed straight at the conjecture."""
    from overtone.agent import evidence

    a = _artifact(tmp_path, "n.flatten.out",
                  ["associator(X,Y,multiply(X,X)) -> associator(Y,X,multiply(X,X))"])
    b = _artifact(tmp_path, "n.noflatten.out",
                  ["multiply(X,commutator(X,Y)) -> commutator(X,multiply(X,Y))"])
    bank = evidence.load(tmp_path)
    bank.update([_row_for(a, "n", "--flatten-goal"),
                 _row_for(b, "n", "--no-flatten-goal")])

    texts = {e.text() for e in bank.all()}
    assert len(texts) == 2, texts
    assert {s["direction"] for e in bank.all() for s in e.sources} == \
        {"--flatten-goal", "--no-flatten-goal"}


def test_the_bank_collapses_orientation_and_renaming(tmp_path):
    """Deduplicated by `eq_key`, like every other comparison here: `a = b` and
    `b = a` under renamed variables are one fact with two sources, and two
    sources is not two candidates to read."""
    from overtone.agent import evidence

    a = _artifact(tmp_path, "one.out", ["multiply(X,Y) -> multiply(Y,X)"])
    b = _artifact(tmp_path, "two.out", ["multiply(B,A) -> multiply(A,B)"])
    bank = evidence.load(tmp_path)
    bank.update([_row_for(a, "p"), _row_for(b, "q")])

    assert len(bank) == 1, [e.text() for e in bank.all()]
    ev = bank.all()[0]
    assert ev.nodes == {"p", "q"} and len(ev.artifacts) == 2


def test_the_bank_drops_run_local_names_forever_but_sketch_matches_only_on_read(
        tmp_path):
    """Two filters with different lifetimes. A rule naming a constant twee
    minted for this run can never be a lemma anywhere, so it is never stored. A
    rule the sketch already states is uninteresting only while that node exists
    -- remove it and the equation is worth having again, which a bank that had
    dropped it could not say."""
    from overtone.agent import evidence

    art = _artifact(tmp_path, "n.out", [
        "add(multiply3,multiply4) -> sk_dag_1",           # run-local: gone
        "multiply(X,Y) -> multiply(Y,X)",                 # already a node
        "commutator(X,add(Y,multiply(X,X))) -> commutator(X,Y)",
    ])
    bank = evidence.load(tmp_path)
    bank.update([_row_for(art, "n")])
    assert len(bank) == 2, [e.text() for e in bank.all()]

    have = Sketch({"c": ("multiply(X,Y)", "multiply(Y,X)", [])})
    assert len(bank.visible(have)) == 1
    assert len(bank.visible(Sketch({}))) == 2, \
        "removing the node makes its equation a candidate again"


def test_universal_equations_are_labelled_not_hidden(tmp_path):
    """Five of the eight equations the old listing showed hold in ANY ring, so
    they say nothing about this problem. But universal is not useless: the most
    valuable node this project added (18x) was a definitional rearrangement,
    which is universal. Hence a label and not a filter."""
    from overtone.agent import evidence

    assert evidence.is_universal("commutator(X,X)", "additive_identity") is True
    assert evidence.is_universal("add(X,add(Y,additive_inverse(X)))", "Y") is True
    # The alternative law is a real axiom of this theory, not a ring identity.
    assert evidence.is_universal("associator(X,X,Y)", "additive_identity") is False

    art = _artifact(tmp_path, "n.out", [
        "commutator(X,X) -> additive_identity",
        "associator(X,X,Y) -> additive_identity",
    ])
    bank = evidence.load(tmp_path)
    bank.update([_row_for(art, "n")])
    fams = bank.families()
    assert [e.text() for e in fams["theory_content"]] == \
        ["associator(X,X,Y) = additive_identity"]
    assert len(bank.all()) == 2, "the universal one is kept, just labelled"


def test_a_mixed_listing_is_not_ordered_by_length(tmp_path):
    """Shortest-first is right inside a facet and wrong across them: the
    shortest equations in any run are the trivial ones, so a plain length sort
    reproduces exactly the score-ordered listing this replaces. Measured on the
    `bridge` node, it returned `commutator(X,X) = 0` first."""
    from overtone.agent import evidence

    art = _artifact(tmp_path, "n.out", [
        "commutator(X,X) -> additive_identity",
        "add(X,add(Y,Z)) -> add(Y,add(X,Z))",
        "associator(X,Y,add(Z,multiply(X,Y))) -> associator(X,Y,Z)",
    ])
    bank = evidence.load(tmp_path)
    bank.update([_row_for(art, "n")])
    first = sorted(bank.all(), key=evidence.relevance)[0]
    assert "multiply" in first.text() and "associator" in first.text(), \
        f"a definition bridge must outrank the short trivia, got {first.text()}"


def test_the_bank_is_incremental_and_survives_a_redraft(tmp_path):
    """Artifacts are 350-550 KB and there are thousands, so each is mined once
    and the fact recorded. And the bank is keyed to the RUN, not the sketch: a
    redraft replaces the decomposition wholesale and used to discard every
    candidate found so far, which is the opposite of what changing approach
    needs."""
    from overtone.agent import evidence

    art = _artifact(tmp_path, "n.out", ["multiply(X,Y) -> multiply(Y,X)"])
    bank = evidence.load(tmp_path)
    assert bank.update([_row_for(art, "n")]) == 1
    assert bank.update([_row_for(art, "n")]) == 0, "an artifact is mined once"

    reloaded = evidence.load(tmp_path)
    assert len(reloaded) == 1 and str(art) in reloaded.mined
    assert reloaded.update([_row_for(art, "n")]) == 0

    # A redraft throws the sketch away; the bank is untouched by that.
    from overtone.agent.loop import apply
    before = Sketch({"a": ("multiply(X,X)", "add(X,X)", [])})
    after = apply(before, {"op": "redraft", "approach": "new",
                           "nodes": [{"name": "z", "lhs": "add(X,Y)",
                                      "rhs": "add(Y,X)"}]})
    assert "a" not in after.nodes
    assert len(evidence.load(tmp_path)) == 1


def test_promote_evidence_copies_the_statement_and_refuses_an_invented_id(tmp_path):
    """The same guard `restate(from_problem=...)` applies to a TPTP conjecture.
    An equation the model transcribes is one it can silently alter, and a mined
    rule is exactly the long term that invites it."""
    from overtone.agent import evidence
    from overtone.agent.loop import apply

    art = _artifact(tmp_path, "n.out",
                    ["associator(X,multiply(X,Y),Z) -> associator(X,Y,multiply(X,Z))"])
    bank = evidence.load(tmp_path)
    bank.update([_row_for(art, "n", support=("p",))])
    ev = bank.all()[0]

    s = Sketch({"p": ("multiply(X,X)", "add(X,X)", [])})
    out = apply(s, {"op": "promote_evidence", "id": ev.id, "name": "bridge_1"},
                bank=bank)
    assert out.nodes["bridge_1"][:2] == (ev.lhs, ev.rhs), "copied, not retyped"
    # Default parents are the support of the run that derived it.
    assert out.nodes["bridge_1"][2] == ["p"]

    with pytest.raises(ValueError, match="no evidence with id"):
        apply(s, {"op": "promote_evidence", "id": "enope", "name": "x"},
              bank=bank)
    with pytest.raises(ValueError, match="evidence bank"):
        apply(s, {"op": "promote_evidence", "id": ev.id, "name": "x"})


def test_a_node_claimed_as_mined_must_actually_have_been_mined(tmp_path):
    """`promote_evidence` copies by id and cannot misquote. The hole is
    `add_node`: a model can type an equation, call it mined, and be believed.
    Both archived runs contain nodes presented that way whose statements appear
    in no artifact -- and provenance is exactly what a reader would trust
    without checking."""
    from overtone.agent import evidence, review

    art = _artifact(tmp_path, "n.out", ["multiply(X,Y) -> multiply(Y,X)"])
    bank = evidence.load(tmp_path)
    bank.update([_row_for(art, "n")])
    s = Sketch({"g": ("add(X,Y)", "add(Y,X)", [])})
    ctx = review.context_for("RNG029-5", s, bank=bank)

    invented = {"op": "add_node", "name": "square_is_double",
                "lhs": "multiply(X,X)", "rhs": "add(X,X)",
                "hypothesis": "mined from the bridge's own run"}
    kept, found = review.review([invented], ctx)
    # The NODE stands -- it may be a fine conjecture -- but the false pedigree
    # is corrected in the record and the agent is told. Rejecting outright cost
    # RNG029-5-told-01 its entire first turn, because it was the only edit.
    assert len(kept) == 1
    assert any(f.reviewer == "provenance" and f.verdict == review.WARN
               for f in found)
    assert "CORRECTED" in kept[0]["hypothesis"], kept[0]["hypothesis"]
    assert "mined from the bridge" in kept[0]["hypothesis"], \
        "the agent's own reasoning is kept beside the correction"

    # The same statement offered as a guess is untouched -- refutation only.
    guess = {**invented, "hypothesis": "worth testing: it would close the gap"}
    kept, found = review.review([guess], ctx)
    assert len(kept) == 1 and not [f for f in found if f.reviewer == "provenance"]

    # And a claim that IS in the bank passes.
    real = {"op": "add_node", "name": "comm", "lhs": "multiply(A,B)",
            "rhs": "multiply(B,A)", "hypothesis": "twee derived this"}
    kept, found = review.review([real], ctx)
    assert not [f for f in found if f.reviewer == "provenance"]


ARCHIVE = Path("logs/loop/RNG029-5-derive-01")


@pytest.mark.skipif(not (ARCHIVE / "iter00/dag.json").exists(),
                    reason="needs the archived run under logs/ (gitignored)")
def test_the_bank_surfaces_what_the_archived_run_could_not_see(tmp_path):
    """The regression this module exists for, on the artifacts that produced it.

    derive-01 iteration 0: the `bridge` node's two searches derived 2,618 and
    3,711 rules, of which 1,099 and 1,043 survive filtering. The planner was
    shown eight, and five of those hold in any ring. The three rules below sat
    at ranks 62, 209 and 210 of the score-ordered listing and never appeared.
    """
    from overtone.agent import evidence

    d = json.loads((ARCHIVE / "iter00/dag.json").read_text())
    sk = Sketch.from_json(json.loads((ARCHIVE / "sketch.00.json").read_text()))
    bank = evidence.load(tmp_path)
    bank.update(d["results"], iteration=0)

    assert len(bank) > 1500, f"only {len(bank)} equations mined"
    fams = bank.families(sk)
    assert len(fams["definition_bridge"]) > 300, len(fams["definition_bridge"])

    have = {e.text() for e in fams["definition_bridge"]}
    for wanted in [
            "associator(X, Y, multiply(X, X)) = associator(Y, X, multiply(X, X))",
            "associator(X, multiply(X, Y), Z) = associator(X, Y, multiply(X, Z))",
            "associator(X, multiply(Y, X), Z) = associator(X, Y, multiply(Z, X))"]:
        assert wanted in have, wanted


def test_paging_the_evidence_bank_costs_a_request_not_an_iteration(tmp_path,
                                                                   monkeypatch):
    """459 candidates cannot be shown and must not cost a turn to look at.

    A read-only lookup is answered mid-exchange from a file the run already
    wrote, and the model is asked again. An action that spent an iteration to
    READ would be worse than the truncated listing it replaces -- the loop gets
    six of them, and two runs spent all ten on one route.
    """
    from overtone.agent import evidence, llm

    art = _artifact(tmp_path, "n.out", [
        "associator(X,multiply(X,Y),Z) -> associator(X,Y,multiply(X,Z))",
        "commutator(X,X) -> additive_identity",
    ])
    bank = evidence.load(tmp_path)
    bank.update([_row_for(art, "bridge")])

    for provider in ("anthropic", "openai"):
        agent = llm.LLMAgent.__new__(llm.LLMAgent)
        agent.provider, agent.model = provider, "m"
        agent.max_tokens, agent.temperature, agent.api_key = 99, 0.0, "k"
        agent.transcript, agent.transcript_dir = [], None
        agent.usage = llm.pricing.Usage()
        agent.attach_bank(bank)

        seen = []

        def fake_post(url, headers, body, _seen=seen, _p=provider):
            _seen.append(body)
            if len(_seen) == 1:              # first turn: ask to look
                if _p == "anthropic":
                    return {"content": [{"type": "tool_use", "id": "t1",
                                         "name": "inspect_evidence",
                                         "input": {"facet": "definition_bridge"}}],
                            "usage": {}}
                return {"choices": [{"message": {"tool_calls": [
                    {"id": "t1", "function": {
                        "name": "inspect_evidence",
                        "arguments": '{"facet": "definition_bridge"}'}}]}}],
                    "usage": {}}
            if _p == "anthropic":            # second turn: commit to an edit
                return {"content": [{"type": "tool_use", "id": "t2",
                                     "name": "remove_node",
                                     "input": {"name": "x"}}], "usage": {}}
            return {"choices": [{"message": {"tool_calls": [
                {"id": "t2", "function": {"name": "remove_node",
                                          "arguments": '{"name": "x"}'}}]}}],
                "usage": {}}

        monkeypatch.setattr(llm, "_post", fake_post)
        actions = agent._call("sys", "state", step="iter00", inspect=True)

        assert len(seen) == 2, f"{provider}: the model was not asked again"
        assert actions == [{"op": "remove_node", "name": "x"}], actions
        # The lookup result reached the model, and it is the bridge -- not the
        # shorter trivial rule a score order would have put first.
        blob = json.dumps(seen[1]["messages"])
        assert "inspect_evidence" not in [a.get("op") for a in actions]
        assert "associator" in blob and "n_matching" in blob, \
            f"{provider}: the tool result was not carried back"


def test_a_lookup_alongside_an_edit_still_answers_every_tool_call(tmp_path,
                                                                  monkeypatch):
    """Both APIs reject a continuation that leaves a tool call unanswered, so a
    model that proposes an edit and a lookup in one response must not wedge the
    turn."""
    from overtone.agent import evidence, llm

    art = _artifact(tmp_path, "n.out", ["multiply(X,Y) -> multiply(Y,X)"])
    bank = evidence.load(tmp_path)
    bank.update([_row_for(art, "n")])

    agent = llm.LLMAgent.__new__(llm.LLMAgent)
    agent.provider, agent.model = "anthropic", "m"
    agent.max_tokens, agent.temperature, agent.api_key = 99, 0.0, "k"
    agent.transcript, agent.transcript_dir = [], None
    agent.usage = llm.pricing.Usage()
    agent.attach_bank(bank)

    seen = []

    def fake_post(url, headers, body):
        seen.append(body)
        if len(seen) == 1:
            return {"content": [
                {"type": "tool_use", "id": "a", "name": "inspect_evidence",
                 "input": {}},
                {"type": "tool_use", "id": "b", "name": "remove_node",
                 "input": {"name": "x"}}], "usage": {}}
        return {"content": [{"type": "tool_use", "id": "c",
                             "name": "remove_node",
                             "input": {"name": "x"}}], "usage": {}}

    monkeypatch.setattr(llm, "_post", fake_post)
    agent._call("sys", "state", step="iter00", inspect=True)

    results = seen[1]["messages"][-1]["content"]
    assert {r["tool_use_id"] for r in results} == {"a", "b"}, \
        "every tool call in the response must be answered, lookup or not"


def test_the_lookup_tool_is_absent_when_there_is_no_bank():
    """Offered and broken is worse than not offered: a tool the model can call
    and that always errors spends its attention on nothing."""
    from overtone.agent import llm

    def names(ts):
        return {t.get("name") or t["function"]["name"] for t in ts}

    assert "inspect_evidence" not in names(llm.tool_schemas("anthropic"))
    assert "inspect_evidence" in names(llm.tool_schemas("anthropic", inspect=True))
    assert "inspect_evidence" in names(llm.tool_schemas("openai", inspect=True))
    # And it is not an EDIT: `loop.apply` must never be handed one.
    from overtone.agent.loop import ACTIONS
    assert "inspect_evidence" not in ACTIONS


def test_the_recall_audit_separates_never_found_from_never_shown(tmp_path):
    """Three numbers, strictly nested, never summed -- the GAPS are the reading.

    Run over the two archived derive runs this reported 21 and 20 of the 29
    manual identities surfaced by the search but only 11 promoted to nodes,
    while 8 and 9 were never produced by any search at all. Those are two
    completely different failures wearing the same "we did not get there": one
    is an attention problem the evidence bank addresses, the other is a search
    problem it cannot.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "recall_audit", Path("scripts/recall_audit.py"))
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)

    # Gold: three identities. One is promoted and grounded, one is derived by a
    # run but never made a node, one never appears anywhere.
    gold = tmp_path / "gold.py"
    gold.write_text(
        "from overtone.agent.dag import Sketch\n"
        "SKETCH = Sketch({\n"
        "  'got':    ('multiply(X,Y)', 'multiply(Y,X)', []),\n"
        "  'unseen': ('commutator(X,add(Y,multiply(X,X)))', 'commutator(X,Y)', []),\n"
        "  'absent': ('associator(X,X,X)', 'additive_identity', []),\n"
        "})\n")

    run = tmp_path / "run"
    (run / "iter00").mkdir(parents=True)
    art = _artifact(run / "iter00", "n.out", [
        "multiply(X,Y) -> multiply(Y,X)",
        "commutator(X,add(Y,multiply(X,X))) -> commutator(X,Y)",
    ])
    rows = [{**_row_for(art, "got"), "proved": True, "result": "Unsatisfiable",
             "cpu": 1.0}]
    (run / "iter00/dag.json").write_text(json.dumps({"results": rows}))
    (run / "loop.json").write_text(json.dumps({
        "proved": False, "iterations": 1,
        "final_sketch": {"got": {"lhs": "multiply(X,Y)",
                                 "rhs": "multiply(Y,X)", "parents": []}}}))

    r = audit.audit(run, gold)
    assert (r["n_surfaced"], r["n_promoted"], r["n_grounded"]) == (2, 1, 1)
    by = {x["gold"]: x for x in r["rows"]}
    assert by["unseen"]["surfaced"] and not by["unseen"]["promoted"], \
        "the search found it and the planner never saw it"
    assert not by["absent"]["surfaced"], "no search ever produced it"
    assert by["got"]["grounded"]


def test_an_empty_lookup_says_which_kind_of_empty_it_is(tmp_path):
    """`n_matching: 0` conflates two opposite answers, and a run paid for it.

    `visible` hides an equation the sketch already states -- right, or a promoted
    node would be re-offered as a candidate forever -- but the planner cannot see
    that from outside. RNG029-5-paged-01 promoted `assoc_push_left_factor` at
    iteration 0, then queried that same shape at iterations 1 through 6 and got a
    bare zero every time; 51 of its 99 lookups came back empty, most of them
    this. It was told "no" and heard "not found" when the answer was "you have
    it already".
    """
    from overtone.agent import evidence

    art = _artifact(tmp_path, "n.out", [
        "associator(X,multiply(X,Y),Z) -> associator(X,Y,multiply(X,Z))",
        "commutator(X,add(Y,multiply(X,X))) -> commutator(X,Y)",
    ])
    bank = evidence.load(tmp_path)
    bank.update([_row_for(art, "n")])

    # 1. Nothing in the bank matches: the search never produced it, which is the
    # only one of the three that means stop looking here.
    r = bank.page(contains="frobnicate(", sketch=Sketch({}))
    assert r["n_matching"] == 0 and "has not produced it" in r["why_empty"]
    assert "already_in_your_sketch" not in r

    # 2. It IS in the bank and the sketch already states it.
    mine = Sketch({"push": ("associator(X,multiply(X,Y),Z)",
                            "associator(X,Y,multiply(X,Z))", [])})
    r = bank.page(contains="associator(X,multiply(X,Y),Z)", sketch=mine)
    assert r["n_matching"] == 0, "correctly hidden -- it is already a node"
    assert "ALREADY STATES" in r["why_empty"]
    assert r["already_in_your_sketch"][0]["node"] == "push"

    # 3. Present and visible, but this query's own filter excluded it.
    r = bank.page(facet="proof_lemma", contains="commutator(X,add(",
                  sketch=Sketch({}))
    assert r["n_matching"] == 0 and "excluded by this query's filters" in r["why_empty"]
    assert r["excluded_by_filters"]

    # 4. A normal hit carries no explanation at all.
    r = bank.page(contains="associator", sketch=Sketch({}))
    assert r["n_matching"] == 1 and "why_empty" not in r
