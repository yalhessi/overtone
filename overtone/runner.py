"""Running twee with results that cannot be attributed to the wrong run.

Every prior attribution bug in this project came from two runs sharing a path:
the screen wrote both goal directions of a problem to one input file and got
fabricated `Satisfiable` results, and two ladder runs shared an output directory
so a reported 378.2s came from a file the other process had written. Both were
invisible in the results themselves.

The fix here is structural rather than careful: a run allocates its own
directory with an atomic `mkdir`, and everything it produces -- input, raw
output, parsed result, the exact command -- lives in that directory. A directory
is never reused, so no two runs can interleave, and every number can be traced
back to the bytes that produced it.

    twee = Twee()
    r = twee.run("ROB005-1", budget=60, label="smoke")
    print(r.status, r.cpu, r.run_dir)

    rs = twee.repeat("ROB005-1", n=5, budget=60, label="variance")
"""
from __future__ import annotations

import json
import os
import re
import resource
import subprocess
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Applied to every invocation, matching Twitch (twitch/src/utils.py:22).
# Omitting these changes the search and makes results incomparable to the paper.
ALWAYS = ("--kbo-weight0-unary", "--print-score")
BASE_FLAGS = ("--all-lemmas", "--show-peaks")

PROVED = ("Unsatisfiable", "Theorem")
SATURATED = ("Satisfiable", "CounterSatisfiable")

RESULT_RE = re.compile(r"^RESULT:\s*(\w+)", re.MULTILINE)
RULE_RE = re.compile(r"^\([\d.]+\)\s+\d+\.", re.MULTILINE)
HINT_RE = re.compile(r"^HINT_FIRED (\d+) (.+)$", re.MULTILINE)
VARNAME = re.compile(r"\b([A-Z][A-Za-z0-9_]*)\b")


def _env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        dotenv = ROOT / ".env"
        if dotenv.exists():
            for line in dotenv.read_text().splitlines():
                if line.startswith(f"{name}="):
                    val = line.split("=", 1)[1].strip()
                    break
    if not val:
        raise RuntimeError(f"{name} is not set; run ./bootstrap.sh")
    return val


@dataclass(frozen=True)
class TweeResult:
    """One twee invocation. Everything needed to reproduce or audit it."""
    problem: str
    label: str
    run_dir: Path
    status: str
    cpu: float
    wall: float
    budget: int
    flags: tuple
    binary: str
    started: str
    n_rules: int
    n_hints: int
    hint_firings: dict = field(default_factory=dict)
    tag: str | None = None

    @property
    def proved(self) -> bool:
        return self.status in PROVED

    @property
    def saturated(self) -> bool:
        return self.status in SATURATED

    @property
    def timed_out(self) -> bool:
        return self.status == "Timeout"

    @property
    def output(self) -> str:
        return (self.run_dir / "output.txt").read_text(errors="replace")

    def __str__(self) -> str:
        mark = "PROVED" if self.proved else self.status
        return f"{self.problem} [{self.label}] {mark} {self.cpu:.1f}s cpu"

    def to_json(self) -> dict:
        d = asdict(self)
        d["run_dir"] = str(self.run_dir)
        d["flags"] = list(self.flags)
        d["proved"] = self.proved
        return d

    @classmethod
    def load(cls, run_dir: Path) -> "TweeResult":
        d = json.loads((Path(run_dir) / "result.json").read_text())
        d.pop("proved", None)
        d["run_dir"] = Path(d["run_dir"])
        d["flags"] = tuple(d["flags"])
        return cls(**d)


class Twee:
    """Runs twee into per-run directories that are never shared or reused."""

    def __init__(self, binary: str | None = None, tptp_root: str | None = None,
                 runs_root: Path | None = None, instrumented: bool = False):
        key = "TWEE_INSTRUMENTED_PATH" if instrumented else "TWEE_PATH"
        self.binary = binary or _env(key)
        self.tptp_root = Path(tptp_root or _env("TPTP_ROOT"))
        self.runs_root = Path(runs_root or (ROOT / "runs"))
        self.instrumented = instrumented

    # ---------------------------------------------------------------- inputs

    def problem_path(self, name: str) -> Path:
        hit = next((self.tptp_root / "Problems").rglob(f"{name}.p"), None)
        if hit is None:
            raise FileNotFoundError(f"{name}.p not found under TPTP_ROOT/Problems")
        return hit

    @staticmethod
    def as_hint(term: str, i: int) -> str:
        """Byte-identical to Twitch's src/utils.py:160."""
        return f"cnf(hint_{i}, axiom,\n\t $hint( {term} )).\n"

    @staticmethod
    def _skolemise(lhs: str, rhs: str):
        """Fresh constants for goal variables.

        A CNF negated_conjecture with free variables says "for all X, lhs != rhs",
        so refuting it only needs some instantiation -- an instance, not the
        universal law. Constants cannot be instantiated, so a proof generalises.
        """
        names = sorted(set(VARNAME.findall(lhs)) | set(VARNAME.findall(rhs)))
        sub = {v: f"sk_goal_{i}" for i, v in enumerate(names, start=1)}
        rep = lambda s: VARNAME.sub(lambda m: sub.get(m.group(1), m.group(1)), s)
        return rep(lhs), rep(rhs)

    def build_input(self, problem: str, dest: Path, hints=(), extra_axioms=(),
                    goal=None) -> Path:
        """Problem file, optionally with hints, extra axioms, or a new goal.

        `goal` is an (lhs, rhs) pair replacing the problem's conjecture; it is
        Skolemised. `extra_axioms` are (lhs, rhs) equations -- note these enlarge
        the rewrite system and are usually much worse than the same content as
        hints (see FINDINGS.md).
        """
        text = self.problem_path(problem).read_text()
        if goal is None and not extra_axioms:
            body = text
        else:
            keep = [l for l in text.splitlines()
                    if l.strip().startswith("include(")]
            if goal is None:
                keep += [l for l in text.splitlines()
                         if "negated_conjecture" in l or
                         (l.strip() and not l.strip().startswith(("%", "include(")))]
            for i, (lhs, rhs) in enumerate(extra_axioms, start=1):
                keep.append(f"cnf(extra_{i}, axiom,\n    ( {lhs} = {rhs} )).")
            if goal is not None:
                lhs, rhs = self._skolemise(*goal)
                keep.append(f"cnf(goal, negated_conjecture,\n    ( {lhs} != {rhs} )).")
            body = "\n".join(keep) + "\n"
        if hints:
            body += "\n\n" + "".join(self.as_hint(h, i)
                                     for i, h in enumerate(hints, start=1))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body)
        return dest

    # ------------------------------------------------------------- run dirs

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

    # ----------------------------------------------------------------- run

    def run(self, problem: str, *, budget: int, label: str, hints=(),
            extra_axioms=(), goal=None, flags=(), direction: str | None = None,
            tag: str | None = None, use_max_time: bool | None = None) -> TweeResult:
        """Run twee once, into its own directory.

        `use_max_time` passes twee's own `--max-time` instead of killing the
        process externally. The instrumented binary reports hint stats only on
        the normal exit path, so it defaults to True there.
        """
        if use_max_time is None:
            use_max_time = self.instrumented
        flags = tuple(BASE_FLAGS) + tuple(flags)
        if direction:
            flags += (direction,)
        run_dir = self._new_run_dir(label, problem, tag)
        inp = self.build_input(problem, run_dir / "input.p", hints,
                               extra_axioms, goal)

        cmd = [self.binary, str(inp), "--root", str(self.tptp_root)]
        cmd += [f for flag in flags for f in flag.split()]
        cmd += list(ALWAYS)
        if use_max_time:
            cmd += ["--max-time", str(budget)]

        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        started = time.monotonic()
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        try:
            out, _ = proc.communicate(timeout=budget + (30 if use_max_time else 0))
            killed = False
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
            killed = True
        after = resource.getrusage(resource.RUSAGE_CHILDREN)

        m = RESULT_RE.search(out)
        status = m.group(1) if m else ("Timeout" if killed else "NoResult")
        firings = {h: int(n) for n, h in HINT_RE.findall(out)}

        (run_dir / "output.txt").write_text(out)
        (run_dir / "cmd.txt").write_text(" ".join(cmd) + "\n")

        r = TweeResult(
            problem=problem, label=label, run_dir=run_dir, status=status,
            cpu=round((after.ru_utime - before.ru_utime)
                      + (after.ru_stime - before.ru_stime), 3),
            wall=round(time.monotonic() - started, 3), budget=budget,
            flags=flags, binary=self.binary, started=stamp,
            n_rules=len(RULE_RE.findall(out)), n_hints=len(hints),
            hint_firings=firings, tag=tag)
        (run_dir / "result.json").write_text(json.dumps(r.to_json(), indent=2))
        return r

    def repeat(self, problem: str, n: int, **kw) -> list[TweeResult]:
        """Run the same configuration n times, each into its own directory."""
        return [self.run(problem, tag=f"rep{i:02d}", **kw) for i in range(1, n + 1)]
