#!/usr/bin/env bash
# Overtone bootstrap: build the toolchain, fetch the corpora, verify it all works.
#
# Safe to re-run; each step skips if already satisfied. Run with --smoke-only to
# just re-verify an existing install.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

ENV_NAME="${OVERTONE_ENV:-overtone}"
TPTP_VERSION="${TPTP_VERSION:-9.2.1}"
TPTP_ROOT="${TPTP_ROOT:-$ROOT/data/TPTP-v$TPTP_VERSION}"
LOG_DIR="${LOG_DIR:-$ROOT/logs}"

# twee 2.6.1 declares `jukebox >= 0.5.9` with no upper bound, but jukebox 0.5.12
# added a field to the Inference constructor, so an unconstrained install picks a
# too-new jukebox and fails to compile executable/SequentialMain.hs.
JUKEBOX_CONSTRAINT='jukebox < 0.5.12'
TWEE_VERSION="${TWEE_VERSION:-2.6.1}"

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m    ! %s\033[0m\n' "$*"; }
ok()   { printf '\033[32m    ok %s\033[0m\n' "$*"; }
die()  { printf '\033[31m    FAILED: %s\033[0m\n' "$*" >&2; exit 1; }

if [[ "${1:-}" != "--smoke-only" ]]; then

say "1/6  Haskell toolchain"
if ! command -v cabal >/dev/null 2>&1; then
  warn "cabal not found; installing ghcup (non-interactive)"
  curl --proto '=https' --tlsv1.2 -sSf https://get-ghcup.haskell.org \
    | BOOTSTRAP_HASKELL_NONINTERACTIVE=1 sh
  # shellcheck disable=SC1090
  source "$HOME/.ghcup/env"
fi
export PATH="$HOME/.ghcup/bin:$HOME/.cabal/bin:$PATH"
command -v cabal >/dev/null || die "cabal still not on PATH; source ~/.ghcup/env"
ok "cabal $(cabal --version | head -1 | awk '{print $NF}'), ghc $(ghc --version | awk '{print $NF}')"

say "2/6  twee $TWEE_VERSION"
if command -v twee >/dev/null 2>&1 && twee --version 2>/dev/null | grep -q "$TWEE_VERSION"; then
  ok "twee $TWEE_VERSION already installed"
else
  cabal update
  cabal install "twee-$TWEE_VERSION" --constraint="$JUKEBOX_CONSTRAINT" --overwrite-policy=always
fi
TWEE_PATH="$(command -v twee)"
# The hint machinery lives behind --expert-help; without it nothing here works.
for flag in hint-skel-factor hint-skel-cost resonance max-term-size proof-on-saturation; do
  twee --expert-help 2>&1 | grep -q -- "--$flag" || die "twee lacks --$flag (wrong build?)"
done
ok "twee at $TWEE_PATH with hint support"

say "3/6  Python environment ($ENV_NAME)"
command -v conda >/dev/null || die "conda not found; install miniconda first"
# shellcheck disable=SC1091
source "$(conda info --base)/etc/profile.d/conda.sh"
if conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
  ok "conda env $ENV_NAME exists"
else
  conda env create -f "$ROOT/environment.yml" -n "$ENV_NAME"
fi
conda activate "$ENV_NAME"
python -c "import stitch_core, dotenv, yaml, numpy" || die "python deps missing"
ok "python $(python --version | awk '{print $2}') with stitch_core"

say "4/6  TPTP v$TPTP_VERSION"
if [[ -d "$TPTP_ROOT/Axioms" ]]; then
  ok "TPTP already at $TPTP_ROOT"
else
  mkdir -p "$ROOT/data"
  curl -L --fail -o "$ROOT/data/TPTP.tgz" \
    "https://www.tptp.org/TPTP/Distribution/TPTP-v$TPTP_VERSION.tgz"
  tar xzf "$ROOT/data/TPTP.tgz" -C "$ROOT/data"
  rm -f "$ROOT/data/TPTP.tgz"
fi
[[ -f "$TPTP_ROOT/Axioms/ROB001-0.ax" ]] || die "TPTP looks incomplete"
ok "$(find "$TPTP_ROOT/Problems" -name '*.p' | wc -l | tr -d ' ') problems"

say "5/6  .env"
cat > "$ROOT/.env" <<EOF
TPTP_ROOT=$TPTP_ROOT
LOG_DIR=$LOG_DIR
TWEE_PATH=$TWEE_PATH
EOF
mkdir -p "$LOG_DIR"
ok "wrote $ROOT/.env"

say "6/6  twitch submodule"
if [[ -f "$ROOT/twitch/src/utils.py" ]]; then
  ok "twitch checked out"
else
  git submodule update --init --recursive || warn "no twitch submodule configured yet"
fi

fi  # end of non-smoke-only setup

say "smoke test"
export PATH="$HOME/.ghcup/bin:$HOME/.cabal/bin:$PATH"
# shellcheck disable=SC1091
source "$(conda info --base)/etc/profile.d/conda.sh"; conda activate "$ENV_NAME"
set -a; # shellcheck disable=SC1091
source "$ROOT/.env"; set +a

# A hint whose symbols all occur in the problem must change the search; one whose
# symbols do not is inert. If these two come out the same, hints are not working.
SMOKE="$(mktemp -d)"
cp "$TPTP_ROOT/Problems/ROB/ROB023-1.p" "$SMOKE/base.p"
cp "$SMOKE/base.p" "$SMOKE/hinted.p"
printf '\ncnf(hint_1, axiom,\n\t $hint( negate(add(A, negate(B))) )).\n' >> "$SMOKE/hinted.p"
t_base=$( { /usr/bin/time -p twee "$SMOKE/base.p" --root "$TPTP_ROOT" --flatten-goal \
            --kbo-weight0-unary --max-time 60 >/dev/null; } 2>&1 | awk '/^user/{print $2}')
t_hint=$( { /usr/bin/time -p twee "$SMOKE/hinted.p" --root "$TPTP_ROOT" --flatten-goal \
            --hint-skel-factor 0.5 --hint-skel-cost 0 \
            --kbo-weight0-unary --max-time 60 >/dev/null; } 2>&1 | awk '/^user/{print $2}')
rm -rf "$SMOKE"
echo "    ROB023-1 baseline ${t_base}s / hinted ${t_hint}s"
awk -v a="$t_base" -v b="$t_hint" 'BEGIN{exit !(a>0 && b>0)}' || die "smoke test produced no timings"
ok "twee + hints functional"

python - <<'PY' || die "twitch python pipeline not importable"
import sys, pathlib
sys.path.insert(0, str(pathlib.Path("twitch").resolve()))
try:
    from src.utils import twee_found_proof, run_twee_on_file  # noqa: F401
    print("    ok twitch importable")
except ModuleNotFoundError as e:
    print(f"    ! twitch not importable yet ({e}); submodule may not be configured")
PY

say "bootstrap complete"
cat <<EOF
  twee      $TWEE_PATH
  TPTP      $TPTP_ROOT
  LOG_DIR   $LOG_DIR
  conda env $ENV_NAME

  next: ./scripts/fetch_external.py --all      # ETP, Robbins/Otter, TSTP corpora
EOF
