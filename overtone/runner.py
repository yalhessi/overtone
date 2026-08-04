"""Running twee, with results that cannot be attributed to the wrong run.

Every prior attribution bug in this project came from two runs sharing a path:
the screen wrote both goal directions of a problem to one input file and got
fabricated `Satisfiable` results, and two ladder runs shared an output directory
so a reported 378.2s came from a file the other process had written. Both were
invisible in the results themselves.

Two levels, because experiments need different things:

  `run(path, flags, budget)`   the primitive. Takes a prepared file, owns no
                               directory, returns a TweeResult with no run_dir.
                               Use when the caller manages its own layout.

  `Twee(...).run(problem, …)`  the facade. Allocates a fresh directory with an
                               atomic mkdir and stores input, output, command and
                               parsed result together, so no two runs can
                               interleave and every number is traceable.

    tw = Twee()
    r  = tw.run("ROB005-1", budget=60, label="smoke")
    rs = tw.repeat("ROB005-1", n=5, budget=60, label="variance")
    print(summarise(rs))
"""
from __future__ import annotations

import json
import os
import re
import resource
import statistics
import subprocess
import threading
import time
from dataclasses import dataclass, asdict, field, fields, replace
from datetime import datetime, timezone
from pathlib import Path

from overtone import config, proofs
from overtone.problems import problem_path

ROOT = config.ROOT

# Applied to every invocation, matching Twitch (twitch/src/utils.py:22).
# Omitting these changes the search and makes results incomparable to the paper.
ALWAYS = ("--kbo-weight0-unary", "--print-score")
# Twitch's base flags, shared by baseline and hinted runs.
BASE_FLAGS = ("--all-lemmas", "--show-peaks")

PROVED = proofs.PROVED
SATURATED = proofs.SATURATED

VARNAME = re.compile(r"\b([A-Z][A-Za-z0-9_]*)\b")


# ------------------------------------------------------------------- writing

def as_cnf_hint(term: str, i: int) -> str:
    """Byte-identical to Twitch's src/utils.py:160."""
    return f"cnf(hint_{i}, axiom,\n\t $hint( {term} )).\n"


def skolemise(lhs: str, rhs: str, prefix: str = "sk_goal_"):
    """Replace goal variables with fresh constants.

    A CNF negated_conjecture with free variables says "for all X, lhs != rhs",
    so refuting it only needs *some* instantiation -- that proves an instance,
    not the universal law, and promoting the variable-form equation back as an
    axiom would then be unsound. Constants cannot be instantiated, so a proof
    establishes the universal statement and the promotion generalises.

    Precondition: `lhs`/`rhs` are TPTP CNF, where capitalised means variable.
    Do not point this at Otter output (see overtone/otter.py), whose translator
    emits uppercase constants.
    """
    names = sorted(set(VARNAME.findall(lhs)) | set(VARNAME.findall(rhs)))
    sub = {v: f"{prefix}{i}" for i, v in enumerate(names, start=1)}

    def rep(s):
        return VARNAME.sub(lambda m: sub.get(m.group(1), m.group(1)), s)

    return rep(lhs), rep(rhs)


def write_problem(problem: str, dest: Path, *, hints=(), extra_axioms=(),
                  goal=None, goal_prefix: str = "sk_goal_",
                  axiom_prefix: str = "extra") -> Path:
    """Write `problem` to `dest`, optionally with hints, axioms, or a new goal.

    Keyword-only after `dest` on purpose: this replaced a `build_input` whose
    two implementations took (name, hints, dest) and (problem, dest, hints) --
    a positional call cannot silently mean the wrong thing now.

    `extra_axioms` are (lhs, rhs) equations. Note these enlarge the rewrite
    system, forming critical pairs with every existing rule, and are usually
    much worse than the same content passed as `hints` (docs/FINDINGS.md).

    Written atomically: `write_text` truncates before it writes, so a concurrent
    reader can otherwise open a half-written file -- twee then parses a shorter
    problem and reports `Satisfiable` in milliseconds, which looks like a real
    outcome in a results table.
    """
    text = problem_path(problem).read_text()
    if goal is None and not extra_axioms:
        body = text
    else:
        lines = [ln for ln in text.splitlines()
                 if ln.strip().startswith("include(")]
        # Non-include clauses of the original problem. Dropped only when the
        # caller supplies its own goal, and even then the axioms must survive:
        # self-contained problems carry them inline rather than via include().
        for role, clause in _original_clauses(text):
            if role == "negated_conjecture" and goal is not None:
                continue
            lines.append(clause)
        for i, (lhs, rhs) in enumerate(extra_axioms, start=1):
            lines.append(f"cnf({axiom_prefix}_{i}, axiom,\n    ( {lhs} = {rhs} )).")
        if goal is not None:
            lhs, rhs = skolemise(*goal, prefix=goal_prefix)
            lines.append(f"cnf(goal, negated_conjecture,\n    ( {lhs} != {rhs} )).")
        body = "\n".join(lines) + "\n"
    if hints:
        body += "\n\n" + "\n".join(as_cnf_hint(h, i)
                                   for i, h in enumerate(hints, start=1))
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.{os.getpid()}.tmp")
    tmp.write_text(body)
    tmp.replace(dest)
    return dest


def _original_clauses(text: str):
    """(role, source text) for each cnf(...) clause, preserving formatting."""
    for m in re.finditer(r"cnf\s*\(", text):
        i, depth = m.end(), 1
        while i < len(text) and depth:
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
            i += 1
        end = text.find(".", i)
        end = i if end == -1 else end + 1
        parts = text[m.end():i - 1].split(",", 2)
        if len(parts) == 3:
            yield parts[1].strip(), text[m.start():end]


# -------------------------------------------------------------------- result

@dataclass(frozen=True)
class TweeResult:
    """One twee invocation. Everything needed to reproduce or audit it."""
    problem: str
    status: str
    cpu: float
    wall: float
    budget: int
    flags: tuple
    binary: str
    started: str
    n_rules: int
    n_hints: int = 0
    hint_firings: dict = field(default_factory=dict)
    label: str | None = None
    tag: str | None = None
    run_dir: Path | None = None
    output: str = field(default="", repr=False, compare=False)

    @property
    def proved(self) -> bool:
        return self.status in PROVED

    @property
    def saturated(self) -> bool:
        return self.status in SATURATED

    @property
    def timed_out(self) -> bool:
        return self.status == "Timeout"

    def __str__(self) -> str:
        mark = "PROVED" if self.proved else self.status
        where = f" [{self.label}]" if self.label else ""
        return f"{self.problem}{where} {mark} {self.cpu:.1f}s cpu"

    def to_json(self) -> dict:
        """Serialisable form. `output` is excluded -- it is megabytes."""
        d = {k: v for k, v in asdict(self).items() if k != "output"}
        d["run_dir"] = str(self.run_dir) if self.run_dir else None
        d["flags"] = list(self.flags)
        d["proved"] = self.proved
        return d

    @classmethod
    def load(cls, run_dir: Path) -> "TweeResult":
        """Read a stored result, tolerating older and newer field sets."""
        d = json.loads((Path(run_dir) / "result.json").read_text())
        known = {f.name for f in fields(cls)}
        d = {k: v for k, v in d.items() if k in known}
        if d.get("run_dir"):
            d["run_dir"] = Path(d["run_dir"])
        if "flags" in d:
            d["flags"] = tuple(d["flags"])
        return cls(**d)


def summarise(rs: list[TweeResult]) -> dict:
    """Aggregate repeats of one configuration.

    twee is not reproducible run to run -- it schedules maintenance by CPU time
    (`Twee.hs:824-848`), so repeats derive different rule sets and, on some
    problems, wildly different runtimes (cv 0.5% on REL029-1, 67.7% on
    MVA006-1). Report mean+-sd rather than a single number, and treat a
    differing `n_rules` as expected rather than as a bug.
    """
    if not rs:
        return {}
    cpus = [r.cpu for r in rs]
    mean = statistics.mean(cpus)
    sd = statistics.stdev(cpus) if len(cpus) > 1 else 0.0
    return {
        "n": len(rs),
        "status": sorted({r.status for r in rs}),
        "n_rules": sorted({r.n_rules for r in rs}),
        "cpu_mean": round(mean, 2),
        "cpu_sd": round(sd, 3),
        "cpu_cv_pct": round(100 * sd / mean, 2) if mean else 0.0,
        "cpu_min": round(min(cpus), 2),
        "cpu_max": round(max(cpus), 2),
        "cpu_spread_pct": round(100 * (max(cpus) - min(cpus)) / mean, 2) if mean else 0.0,
        "wall_mean": round(statistics.mean(r.wall for r in rs), 2),
    }


# ----------------------------------------------------------------- the runs

def run(path: Path, flags=(), budget: int = 1000, *, binary: str | None = None,
        tptp_root: Path | None = None, use_max_time: bool = False,
        problem: str | None = None, n_hints: int = 0, cancel=None) -> TweeResult:
    """Run twee on a prepared file. Owns no directory; `output` is in memory.

    `use_max_time` passes twee's own `--max-time` instead of killing the process
    externally. Leave it False for anything meant to be comparable with existing
    records -- the 592 screen results and the Twitch replication timings were all
    produced with an external timeout and no such flag. The instrumented build
    needs it True, since it reports hint stats only on the normal exit path.

    `cancel` is anything with `.is_set()`. When it becomes set the child is
    killed and the result is reported as "Cancelled" -- distinct from a timeout,
    because a cancelled run answered nothing and must never be recorded as
    though it had. It exists so a node's two goal directions can race and the
    loser can be stopped the moment the winner proves.

    CPU is a RUSAGE_CHILDREN delta, which is process-wide, so this stays correct
    only while one twee child runs per process. Race the directions in separate
    processes, not threads.
    """
    binary = binary or config.twee_path()
    tptp_root = Path(tptp_root or config.tptp_root())
    cmd = [binary, str(path), "--root", str(tptp_root)]
    cmd += [f for flag in flags for f in flag.split()]
    cmd += list(ALWAYS)
    if use_max_time:
        cmd += ["--max-time", str(budget)]

    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.monotonic()
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True)
    proc_timeout = budget + 30 if use_max_time else budget
    killed = cancelled = False
    if cancel is None:
        try:
            out, _ = proc.communicate(timeout=proc_timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
            killed = True
    else:
        # Drain on a thread while polling `cancel`. twee writes megabytes, so
        # polling without draining fills the pipe buffer and deadlocks the child.
        box = {}
        drain = threading.Thread(target=lambda: box.update(o=proc.communicate()[0]),
                                 daemon=True)
        drain.start()
        deadline = time.monotonic() + proc_timeout
        while drain.is_alive():
            if cancel.is_set():
                proc.kill()
                cancelled = True
                break
            if time.monotonic() >= deadline:
                proc.kill()
                killed = True
                break
            drain.join(0.1)
        drain.join()
        out = box.get("o", "")
    after = resource.getrusage(resource.RUSAGE_CHILDREN)

    return TweeResult(
        problem=problem or Path(path).stem,
        status="Cancelled" if cancelled else proofs.parse_status(out, killed),
        cpu=round((after.ru_utime - before.ru_utime)
                  + (after.ru_stime - before.ru_stime), 3),
        wall=round(time.monotonic() - started, 3),
        budget=budget, flags=tuple(flags), binary=binary, started=stamp,
        n_rules=proofs.count_rule_lines(out), n_hints=n_hints,
        hint_firings=proofs.hint_firings(out), output=out)


class Twee:
    """Runs twee into per-run directories that are never shared or reused."""

    def __init__(self, binary: str | None = None, tptp_root: str | None = None,
                 runs_root: Path | None = None, instrumented: bool = False):
        self.binary = binary or config.twee_path(instrumented)
        self.tptp_root = Path(tptp_root or config.tptp_root())
        self.runs_root = Path(runs_root or config.RUNS)
        self.instrumented = instrumented

    # kept as methods so callers with a configured instance need nothing else
    problem_path = staticmethod(problem_path)
    as_hint = staticmethod(as_cnf_hint)

    def write_problem(self, problem: str, dest: Path, **kw) -> Path:
        return write_problem(problem, dest, **kw)

    def _new_run_dir(self, label: str, problem: str, tag: str | None) -> Path:
        """Allocate a fresh directory. `mkdir` is atomic, so two concurrent
        callers cannot be handed the same one."""
        base = self.runs_root / label
        base.mkdir(parents=True, exist_ok=True)
        name = f"{problem}__{tag}" if tag else problem
        for n in range(1, 100000):
            d = base / f"{n:04d}_{name}"
            try:
                d.mkdir()
                return d
            except FileExistsError:
                continue
        raise RuntimeError(f"could not allocate a run dir under {base}")

    def run(self, problem: str, *, budget: int, label: str, hints=(),
            extra_axioms=(), goal=None, flags=(), direction: str | None = None,
            tag: str | None = None,
            use_max_time: bool | None = None) -> TweeResult:
        """Run twee once, into its own directory."""
        if use_max_time is None:
            use_max_time = self.instrumented
        flags = tuple(BASE_FLAGS) + tuple(flags)
        if direction:
            flags += (direction,)
        run_dir = self._new_run_dir(label, problem, tag)
        inp = write_problem(problem, run_dir / "input.p", hints=hints,
                            extra_axioms=extra_axioms, goal=goal)

        r = replace(run(inp, flags, budget, binary=self.binary,
                        tptp_root=self.tptp_root, use_max_time=use_max_time,
                        problem=problem, n_hints=len(hints)),
                    run_dir=run_dir, label=label, tag=tag)

        (run_dir / "output.txt").write_text(r.output)
        (run_dir / "cmd.txt").write_text(
            " ".join([self.binary, str(inp), "--root", str(self.tptp_root),
                      *[f for flag in flags for f in flag.split()], *ALWAYS]
                     + (["--max-time", str(budget)] if use_max_time else [])) + "\n")
        (run_dir / "result.json").write_text(json.dumps(r.to_json(), indent=2))
        return r

    def repeat(self, problem: str, n: int, **kw) -> list[TweeResult]:
        """Run the same configuration n times, each into its own directory."""
        return [self.run(problem, tag=f"rep{i:02d}", **kw) for i in range(1, n + 1)]
