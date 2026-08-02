"""Running twee and reading its result, in one place.

Two things here are easy to get wrong and are the reason this is shared rather
than reimplemented per script:

  * twee exits 0 whether or not it found a proof. The outcome is the final
    `RESULT: <status>` line, and only `Unsatisfiable`/`Theorem` mean a proof.
    Checking the exit code silently counts saturations as successes.
  * Twitch appends `--kbo-weight0-unary --print-score` to every invocation
    (`twitch/src/utils.py:22`) and these are not in any stored config. Omitting
    them changes the search, so any run meant to be comparable to Twitch's
    numbers must include them.

See docs/FINDINGS.md.
"""
import os
import re
import resource
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Applied to every invocation, matching Twitch.
ALWAYS = ["--kbo-weight0-unary", "--print-score"]
# Twitch's base flags, shared by baseline and hinted runs.
BASE_FLAGS = ["--all-lemmas", "--show-peaks"]

PROVED = ("Unsatisfiable", "Theorem")
SATURATED = ("Satisfiable", "CounterSatisfiable")


def env(name: str) -> str:
    """Read `name` from the environment, falling back to the repo's .env."""
    val = os.environ.get(name)
    if not val:
        dotenv = ROOT / ".env"
        if dotenv.exists():
            for line in dotenv.read_text().splitlines():
                if line.startswith(f"{name}="):
                    val = line.split("=", 1)[1].strip()
                    break
    if not val:
        sys.exit(f"{name} is not set; run ./bootstrap.sh")
    return val


def problem_path(name: str) -> Path:
    """Locate a TPTP problem by bare name, e.g. ROB034-1."""
    hit = next((Path(env("TPTP_ROOT")) / "Problems").rglob(f"{name}.p"), None)
    if hit is None:
        sys.exit(f"{name}.p not found under TPTP_ROOT/Problems")
    return hit


def as_cnf_hint(term: str, i: int) -> str:
    """Byte-identical to Twitch's src/utils.py:160."""
    return f"cnf(hint_{i}, axiom,\n\t $hint( {term} )).\n"


def build_input(name: str, hints, dest: Path) -> Path:
    """Write `name`'s problem file with `hints` appended as $hint clauses.

    Written atomically. `write_text` truncates before it writes, so a concurrent
    reader can otherwise open a half-written file -- twee then parses a shorter
    problem and reports `Satisfiable` in milliseconds, or emits no RESULT line at
    all. Both look like real outcomes in a results table. Renaming into place
    means a reader sees either the old file or the complete new one.
    """
    body = problem_path(name).read_text()
    if hints:
        body += "\n\n" + "\n".join(as_cnf_hint(h, i)
                                   for i, h in enumerate(hints, start=1))
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.{os.getpid()}.tmp")
    tmp.write_text(body)
    tmp.replace(dest)
    return dest


def run(path: Path, flags, timeout: int) -> dict:
    """Run twee on `path`; return status, CPU and wall time, and output.

    CPU time is measured over RUSAGE_CHILDREN, so it is only meaningful when no
    other child processes finish concurrently in the same process -- run one
    twee per worker process, not several per thread.
    """
    cmd = ([env("TWEE_PATH"), str(path), "--root", env("TPTP_ROOT")]
           + [f for flag in flags for f in flag.split()] + ALWAYS)
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.monotonic()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True)
    try:
        out, _ = proc.communicate(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
        timed_out = True
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    m = re.search(r"^RESULT:\s*(\w+)", out, re.MULTILINE)
    result = m.group(1) if m else ("Timeout" if timed_out else "None")
    return {
        "result": result,
        "proved": result in PROVED,
        "saturated": result in SATURATED,
        "cpu": ((after.ru_utime - before.ru_utime)
                + (after.ru_stime - before.ru_stime)),
        "wall": time.monotonic() - started,
        "timed_out": timed_out,
        "output": out,
        "cmd": cmd,
    }
