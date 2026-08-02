"""Repo paths and environment, resolved in one place.

Hand-rolled rather than `python-dotenv` on purpose: dotenv resolves `.env`
relative to the current working directory, and these scripts run from tmux, from
`ProcessPoolExecutor` workers, and from notebooks. Everything here anchors to the
repo root instead.

Lookups raise rather than calling `sys.exit`. `SystemExit` derives from
`BaseException`, so an `except Exception` in a pool worker will not catch it and
one missing problem takes down a multi-hour sweep; CLIs catch at `main()`.
"""
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
LOGS = Path(os.environ.get("LOG_DIR") or (ROOT / "logs"))
RUNS = ROOT / "runs"
LISTS = DATA / "lists"

# The instrumented binary, when built, lands under this tree.
_INSTRUMENTED_GLOB = "build/twee-instrumented/dist-newstyle/**/twee"


def env(name: str, default: str | None = None) -> str:
    """Read `name` from the environment, falling back to the repo's `.env`."""
    val = os.environ.get(name)
    if not val:
        dotenv = ROOT / ".env"
        if dotenv.exists():
            for line in dotenv.read_text().splitlines():
                line = line.strip()
                if line.startswith(f"{name}=") and not line.startswith("#"):
                    val = line.split("=", 1)[1].strip()
                    break
    if not val:
        val = default
    if not val:
        raise RuntimeError(f"{name} is not set; run ./bootstrap.sh")
    return val


def tptp_root() -> Path:
    """Locate the TPTP distribution, falling back to the newest local copy."""
    try:
        p = Path(env("TPTP_ROOT"))
    except RuntimeError:
        candidates = sorted(DATA.glob("TPTP-v*"))
        if not candidates:
            raise RuntimeError(
                "TPTP_ROOT is not set and no data/TPTP-v* exists; run ./bootstrap.sh"
            ) from None
        p = candidates[-1]
    if not (p / "Problems").is_dir():
        raise RuntimeError(f"{p}/Problems does not exist -- is TPTP_ROOT correct?")
    return p


def twee_path(instrumented: bool = False) -> str:
    """Path to a twee binary.

    The instrumented build counts hint firings and is therefore slower; it is a
    separate binary so that stock twee stays authoritative for every timing.
    `build_instrumented_twee.sh` writes TWEE_INSTRUMENTED_PATH into .env, but we
    also discover the build tree so a fresh checkout works without editing .env.
    """
    if not instrumented:
        return env("TWEE_PATH")
    try:
        return env("TWEE_INSTRUMENTED_PATH")
    except RuntimeError:
        # The glob also matches intermediate directories named `twee`, so filter
        # to executable files and take the most recently built.
        hits = [p for p in ROOT.glob(_INSTRUMENTED_GLOB)
                if p.is_file() and os.access(p, os.X_OK)]
        if not hits:
            raise RuntimeError(
                "no instrumented twee; run ./scripts/build_instrumented_twee.sh"
            ) from None
        return str(max(hits, key=lambda p: p.stat().st_mtime))
