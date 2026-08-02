#!/usr/bin/env bash
# Build a hint-firing-instrumented twee, alongside the stock one.
#
# WHY A SEPARATE BINARY: counting in twee's scoring hot path costs time. If we
# replaced $TWEE_PATH, every timing in docs/FINDINGS.md would silently shift.
# Stock twee stays authoritative for timings; this build is only ever used to
# measure whether hints fire.
#
# WHAT IT MEASURES: hints are matched inside CP.score, which runs on every
# critical pair scored -- including ones never kept -- so firing leaves no trace
# in twee's normal output. twee's author wrote a `trace` at that exact site and
# commented it out (Twee/CP.hs:261); this restores it as a counter.
#
# USAGE: ./scripts/build_instrumented_twee.sh
#        then run with --max-time N, NOT an external timeout: the stats print on
#        the normal exit path, so a SIGKILLed run reports nothing.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$ROOT/build/twee-instrumented"
GHC_VER="${GHC_VER:-9.6.7}"
LIB=twee-lib-2.6.1
EXE=twee-2.6.1

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

say "0/4  Sources"
mkdir -p "$BUILD"
cd "$BUILD"
for pkg in "$LIB" "$EXE"; do
  name="${pkg%-*}"
  tgz="$HOME/.cabal/packages/hackage.haskell.org/$name/2.6.1/$pkg.tar.gz"
  if [[ -d "$pkg" ]]; then
    echo "    have $pkg"
  elif [[ -f "$tgz" ]]; then
    tar xzf "$tgz" && echo "    unpacked $pkg from the cabal cache"
  else
    cabal get "$name-2.6.1" && echo "    fetched $pkg"
  fi
done

say "1/4  Patching Twee/CP.hs (hint-firing counter)"
python3 - "$LIB" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1]) / "Twee" / "CP.hs"
s = p.read_text()
if "recordHintMatch" in s:
    print("    already patched"); raise SystemExit

imp = "import Data.Bits\nimport Data.Serialize\n"
assert imp in s, "import anchor not found -- twee source changed?"
s = s.replace(imp, imp +
  "import Data.IORef\nimport System.IO.Unsafe(unsafePerformIO)\n"
  "import qualified Data.Map.Strict as HintStats\n", 1)

anchor = "{-# INLINEABLE score #-}"
assert anchor in s, "score anchor not found -- twee source changed?"
s = s.replace(anchor, '''-- Hint-firing instrumentation (Overtone).
-- Follows the Debug.Trace idiom for running IO from pure code.
{-# NOINLINE hintStatsRef #-}
hintStatsRef :: IORef (HintStats.Map String Int)
hintStatsRef = unsafePerformIO (newIORef HintStats.empty)

{-# NOINLINE recordHintMatch #-}
recordHintMatch :: String -> a -> a
recordHintMatch key expr = unsafePerformIO $ do
  modifyIORef' hintStatsRef (HintStats.insertWith (+) key 1)
  return expr

getHintStats :: IO [(String, Int)]
getHintStats = HintStats.toList <$> readIORef hintStatsRef

''' + anchor, 1)

fire = """        size' (n + hint_cost) ts (map snd (Term.substToList' sub) ++ us)
        --trace ("hint: len " ++ show (len t) ++ ", new cost " ++ show new_cost ++ ": " ++ prettyShow t) $"""
assert fire in s, "firing site not found -- twee source changed?"
s = s.replace(fire, """        recordHintMatch (prettyShow hint_term) $
        size' (n + hint_cost) ts (map snd (Term.substToList' sub) ++ us)""", 1)
p.write_text(s)
print("    patched")
PY

say "2/4  Patching SequentialMain.hs (report on exit)"
python3 - "$EXE" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1]) / "executable" / "SequentialMain.hs"
s = p.read_text()
if "getHintStats" in s:
    print("    already patched"); raise SystemExit
old = "  return $\n    if solved state then Unsat Unsatisfiable Nothing"
assert old in s, "return anchor not found -- twee source changed?"
s = s.replace(old, '''  hintStats <- CP.getHintStats
  unless (null hintStats) $ do
    putStrLn ""
    putStrLn "% SZS output start HintStats"
    forM_ (sortBy (comparing (negate . snd)) hintStats) $ \\(h, n) ->
      putStrLn ("HINT_FIRED " ++ show n ++ " " ++ h)
    putStrLn ("HINT_FIRED_TOTAL " ++ show (sum (map snd hintStats)) ++
              " over " ++ show (length hintStats) ++ " distinct hints")
    putStrLn "% SZS output end HintStats"

''' + old, 1)
p.write_text(s)
print("    patched")
PY

say "3/4  Building"
cat > cabal.project <<EOF
packages: $EXE/ $LIB/
constraints: jukebox < 0.5.12
EOF

# Same GMP dance as bootstrap.sh: clusters ship libgmp.so.10 without libgmp.so.
GMP_LIB=""
for cand in "${CONDA_PREFIX:-}/lib/libgmp.so" \
            "$HOME/miniconda3/envs/overtone/lib/libgmp.so" \
            /usr/lib64/libgmp.so /usr/lib/x86_64-linux-gnu/libgmp.so; do
  [[ -e "$cand" ]] && { GMP_LIB="$(dirname "$cand")"; break; }
done
[[ -n "$GMP_LIB" ]] || { echo "no libgmp.so found; conda install -c conda-forge gmp" >&2; exit 1; }

cabal build twee -w "ghc-$GHC_VER" \
  --extra-lib-dirs="$GMP_LIB" --extra-include-dirs="${GMP_LIB%/lib}/include"

BIN="$(cabal list-bin twee -w "ghc-$GHC_VER" 2>/dev/null || \
  find "$BUILD/dist-newstyle" -type f -name twee -perm -u+x | head -1)"

say "4/4  Done"
echo "  binary: $BIN"
echo
echo "  Add to .env (do NOT overwrite TWEE_PATH):"
echo "    TWEE_INSTRUMENTED_PATH=$BIN"
echo
echo "  Run with --max-time N, not an external timeout."
