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
# Known-good compiler. Newer GHC pulls a newer base that twee's older transitive
# deps (symbol, uglymemo) have not been updated for.
GHC_VERSION="${GHC_VERSION:-9.6.7}"

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m    ! %s\033[0m\n' "$*"; }
ok()   { printf '\033[32m    ok %s\033[0m\n' "$*"; }
die()  { printf '\033[31m    FAILED: %s\033[0m\n' "$*" >&2; exit 1; }

if [[ "${1:-}" != "--smoke-only" ]]; then

say "0/6  Python environment ($ENV_NAME) -- first, because it supplies GMP"
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

say "1/6  Haskell toolchain (GHC $GHC_VERSION)"
if ! command -v ghcup >/dev/null 2>&1 && [[ ! -x "$HOME/.ghcup/bin/ghcup" ]]; then
  warn "ghcup not found; installing non-interactively"
  curl --proto '=https' --tlsv1.2 -sSf https://get-ghcup.haskell.org \
    | BOOTSTRAP_HASKELL_NONINTERACTIVE=1 BOOTSTRAP_HASKELL_GHC_VERSION="$GHC_VERSION" sh
fi
export PATH="$HOME/.ghcup/bin:$HOME/.cabal/bin:$PATH"
command -v ghcup >/dev/null || die "ghcup not on PATH; source ~/.ghcup/env"
ghcup install ghc "$GHC_VERSION" 2>/dev/null || true
ghcup set ghc "$GHC_VERSION"
command -v cabal >/dev/null || ghcup install cabal --set
ok "cabal $(cabal --version | head -1 | awk '{print $NF}'), ghc $(ghc --version | awk '{print $NF}')"

# GHC links Integer against GMP. Clusters commonly ship the runtime
# (libgmp.so.10) without the libgmp.so symlink from gmp-devel, and then EVERY
# cabal build fails at link time with "cannot find -lgmp" -- including alex, so
# the error surfaces long before twee itself. Point cabal at conda's copy.
say "1b/6 GMP"
GMP_LIB=""
for cand in "$CONDA_PREFIX/lib/libgmp.so" "$CONDA_PREFIX/lib/libgmp.dylib" \
            /usr/lib64/libgmp.so /usr/lib/x86_64-linux-gnu/libgmp.so; do
  [[ -e "$cand" ]] && { GMP_LIB="$(dirname "$cand")"; break; }
done
[[ -n "$GMP_LIB" ]] || die "no libgmp.so found. Install it into the conda env with:
      conda install -n $ENV_NAME -c conda-forge gmp
    or load a cluster module (module avail gmp), or ask for gmp-devel."
CABAL_LIB_FLAGS=(--extra-lib-dirs="$GMP_LIB" --extra-include-dirs="${GMP_LIB%/lib}/include")
# --extra-lib-dirs alone is NOT enough. cabal applies command-line configure flags
# only to the *target* package, never to dependencies resolved from Hackage, so twee
# itself would get the flag while alex, cereal, colour, ... all still die with
# "cannot find -lgmp". (Verified: alex-3.5.4.2 builds with this exact flag when it is
# the target and fails with it when it is a dependency.) LIBRARY_PATH is read by
# gcc/ld directly, so it reaches every compiler invocation cabal spawns.
#
# LIBRARY_PATH is link-time only: the binaries record libgmp's soname (libgmp.so.10)
# and resolve against the system copy at runtime, so this does not put conda's libgmp
# on anything's *runtime* path -- which is what would break Lean (see the Rocq note in
# ~/.zshrc). Keep it that way; do not promote this to LD_LIBRARY_PATH globally.
export LIBRARY_PATH="$GMP_LIB:${LIBRARY_PATH:-}"
export LD_LIBRARY_PATH="$GMP_LIB:${LD_LIBRARY_PATH:-}"
ok "libgmp at $GMP_LIB"

say "2/6  twee $TWEE_VERSION"
if command -v twee >/dev/null 2>&1 && twee --version 2>/dev/null | grep -q "$TWEE_VERSION"; then
  ok "twee $TWEE_VERSION already installed"
else
  cabal update
  cabal install "twee-$TWEE_VERSION" --constraint="$JUKEBOX_CONSTRAINT" \
    "${CABAL_LIB_FLAGS[@]}" --overwrite-policy=always
fi
TWEE_PATH="$(command -v twee)"
# The hint machinery lives behind --expert-help; without it nothing here works.
# twee prints boolean flags in "--(no-)resonance" form, so a literal grep for
# "--resonance" false-negatives on a perfectly good build. Normalise first.
TWEE_HELP="$(twee --expert-help 2>&1 | sed 's/--(no-)/--/g')"
for flag in hint-skel-factor hint-skel-cost resonance max-term-size proof-on-saturation; do
  grep -q -- "--$flag" <<<"$TWEE_HELP" || die "twee lacks --$flag (wrong build?)"
done
ok "twee at $TWEE_PATH with hint support"

say "3/6  Python environment"
ok "created in step 0 (needed for GMP)"
# Editable install so `from overtone import ...` resolves from any directory,
# rather than every script prepending the repo root to sys.path.
pip install -e "$ROOT" --quiet --no-deps
ok "overtone installed (editable)"

# Graphviz, for sketch blueprints (scripts/blueprint.py). Optional: the renderer
# falls back to a built-in layered layout when `dot` is absent. Installed into
# its own prefix because the conda package conflicts with this environment's
# python=3.13 pin.
if command -v dot >/dev/null 2>&1; then
  ok "graphviz already on PATH ($(dot -V 2>&1))"
elif [[ -x "$ROOT/build/gv/bin/dot" ]]; then
  ok "graphviz at build/gv"
else
  conda create -y -q -p "$ROOT/build/gv" graphviz >/dev/null 2>&1 \
    && ok "graphviz installed to build/gv" \
    || echo "    ! graphviz unavailable; blueprints use the built-in renderer"
fi

say "4/6  TPTP v$TPTP_VERSION"
if [[ -d "$TPTP_ROOT/Axioms" ]]; then
  ok "TPTP already at $TPTP_ROOT"
else
  mkdir -p "$ROOT/data"
  curl -L --fail -o "$ROOT/data/TPTP.tgz" \
    "https://tptp.org/TPTP/Archive/TPTP-v$TPTP_VERSION.tgz"
    # "https://www.tptp.org/TPTP/Distribution/TPTP-v$TPTP_VERSION.tgz"
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

  next: ./scripts/make_ueq_list.py             # data/lists/ueq.tsv, offline
        ./scripts/fetch_external.py --all      # ETP, Robbins, Veroff, TSTP
EOF
