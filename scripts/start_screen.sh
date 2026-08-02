#!/usr/bin/env bash
# Launch the high-budget screen in a detached tmux session.
#
# The screen runs for hours and must survive disconnection, so it lives in tmux
# rather than in a shell. It is resumable -- results already in results.jsonl are
# skipped -- so killing the session and re-running this script is safe and loses
# only the jobs that were in flight.
#
#   ./scripts/start_screen.sh              start (or attach if already running)
#   tmux attach -t overtone                watch it
#   tmux kill-session -t overtone          stop it
set -euo pipefail

SESSION="${SESSION:-overtone}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKERS="${WORKERS:-16}"
BUDGET="${BUDGET:-1000}"
PROBLEMS="${PROBLEMS:-$ROOT/data/lists/screen.txt}"
# Separate outdir/markdown per screen, so a second run at a different budget
# does not overwrite the first one's results or tracker.
OUTDIR="${OUTDIR:-$ROOT/logs/screen}"
MARKDOWN="${MARKDOWN:-$ROOT/docs/RUNS.md}"

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "session '$SESSION' already exists; attach with: tmux attach -t $SESSION"
  exit 0
fi

[ -f "$PROBLEMS" ] || { echo "missing $PROBLEMS -- run ./scripts/make_ueq_list.py" >&2; exit 1; }

mkdir -p "$OUTDIR"

# -d so this returns immediately; the caller may be a non-interactive shell.
tmux new-session -d -s "$SESSION" -c "$ROOT" -n screen \
  "./scripts/screen.py --problems '$PROBLEMS' --budget $BUDGET \
     --workers $WORKERS --outdir '$OUTDIR' --markdown '$MARKDOWN' \
     --keep-proofs 2>&1 | tee -a '$OUTDIR/console.log'"

# Second window for watching the tracker without disturbing the run.
tmux new-window -d -t "$SESSION" -c "$ROOT" -n watch \
  "watch -n 30 'tail -n 40 \"$MARKDOWN\"'"

echo "started '$SESSION': $WORKERS workers, ${BUDGET}s budget, $(wc -l < "$PROBLEMS") problems"
echo "  attach   tmux attach -t $SESSION"
echo "  tracker  $MARKDOWN"
echo "  console  $OUTDIR/console.log"
