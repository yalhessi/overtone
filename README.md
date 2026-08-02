# Overtone

Learned guidance for equational theorem proving with [twee](https://hackage.haskell.org/package/twee).

Overtone is the experiment platform around Twitch. Twitch itself (Stitch-based
abstraction mining) is vendored as a submodule; this repo adds the corpora, the
sweep infrastructure, the analysis, and the learned components.

## Scope

Three lines of work, in the order the evidence currently supports:

1. **Rule usefulness.** 91–98% of the rewrite rules twee derives never appear in
   the proof it finds, and useful ones cluster in the first few percent of a run.
   Every derived rule in an existing log is a labelled example, so this is a
   large supervised dataset requiring no new prover runs.
2. **Hint weighting.** twee's hint cost is a fixed function of hint size
   (`Twee.hs:618`); nothing lets an external model say *this* hint is worth more
   than that one. Per-hint weights are a small patch and the natural interface
   for a learned scorer. Whether the hint channel has enough ceiling to matter is
   still being measured — see `docs/FINDINGS.md`.
3. **The Robbins ladder.** A chain of TPTP problems of graded difficulty with
   published oracle proofs and hint lists, ending at problems no prover has
   solved. Used as the frontier benchmark and for calibration.

## Setup

```bash
git clone --recurse-submodules git@github.com:yalhessi/overtone.git
cd overtone
./bootstrap.sh
```

`bootstrap.sh` installs the Haskell toolchain if absent, builds twee with the
required jukebox constraint, creates the conda environment, downloads TPTP,
writes `.env`, and runs a smoke test that verifies hints actually change the
search. It is idempotent; `./bootstrap.sh --smoke-only` re-verifies an existing
install.

Then build the problem lists and fetch the external corpora:

```bash
./scripts/make_ueq_list.py          # data/lists/ueq.tsv + per-status name lists
./scripts/fetch_external.py --all   # ETP, Robbins, Veroff, TSTP
```

`make_ueq_list.py` reads the `% SPC :` header of every problem in the local TPTP
distribution, so it runs offline and cannot drift from what is on disk. TSTP has
no bulk download, so its arm is a ~5700-request crawl of tptp.org's CGI at a
deliberately polite rate — budget ~1.5h, and it resumes if interrupted.

## Layout

```
bootstrap.sh          one-shot setup; safe to re-run
pyproject.toml        editable install, so `from overtone import ...` just works
environment.yml       conda environment
twitch/               submodule: the abstraction-mining pipeline
overtone/             this project's python package
  config.py           paths and .env, resolved in one place
  problems.py         locating and reading TPTP problems
  terms.py            TPTP terms: parse, alpha-normalise, symbols, similarity
  runner.py           running twee; TweeResult; per-run directories
  proofs.py           parsing twee output
  batch.py            resumable parallel sweeps + the results.jsonl format
  otter.py            Otter/EQP equations -> twee $hint terms
  agent/              the sketch loop -- isolated and deletable; core never
                      imports it (deletion contract in agent/__init__.py)
scripts/              thin CLIs over the package
  make_ueq_list.py    enumerate TPTP UEQ problems from the local distribution
  fetch_external.py   ETP, Robbins/Otter, Veroff, TSTP corpora
  replicate_twitch.py re-run a recorded Twitch success and compare times
  screen.py           high-budget baseline screen, both goal directions
  start_screen.sh     launch the screen in a detached tmux session
  variance.py         run-to-run reproducibility of twee timings
  rule_usefulness.py  derived-vs-used rule statistics over saved proofs
  sketch_transfer.py  donor-proof hints for resisted problems      [agent]
  ladder.py           run a sketch as a ladder of goals            [agent]
  build_instrumented_twee.sh   twee patched to count hint firings
examples/sketch_loop/ tracked sketch bundles; also the regression harness
data/                 TPTP + external corpora (gitignored)
logs/                 sweep output (gitignored; grows to GBs)
runs/                 per-run twee directories (gitignored)
docs/FINDINGS.md      measured results and pitfalls -- read before designing runs
docs/EXPECTATIONS.md  what neural guidance can realistically deliver here
docs/SKETCH_LOOP.md   design for transferring proof sketches into hints
docs/RUNS.md          live tracker for the screen; also its pre-registration
```

Regenerating `examples/sketch_loop/` is the repo's regression test: it exercises
env resolution, problem lookup, include handling, term parsing, similarity, hint
adaptation and input building in one command.

```bash
./scripts/sketch_transfer.py MVA005-1 LCL054-10 LCL231-10 LAT138-1 \
    GRP673-10 GRP674-11 KLE096-10 COL003-1
git diff --stat examples/          # expected to be empty
```

Note `sketch.md` embeds the current screen baselines, so it legitimately changes
when a new sweep completes.

## Before you run anything

`docs/FINDINGS.md` documents results that are cheap to rediscover expensively.
The three that most often invalidate an experiment:

- **`--hint-skel-factor 0` is harmful**, measured four independent ways. Use 0.5.
- **Screen at a realistic budget.** A 30s screen mislabels problems that need
  400–800s, and goal direction alone can flip a problem between solved and never.
- **Always pair a baseline run with the treatment**, in the same batch.

## Data

| corpus | size | role |
|---|---|---|
| TPTP UEQ | 1140 UNS, 260 SAT, 48 UNK, 7 OPN | primary train/eval |
| ETP | ~2400 non-trivial, 1062 unresolved | uniform-signature transfer |
| TSTP | 3990 derivations, 930/1140 problems | donor proofs; only 5.8% of the >=0.9 band |
| Veroff | 175 inputs, ~2.4M hints, 196 proofs | human oracle hints at the frontier |
| Robbins/Otter | 4 rungs, 3 hint lists | oracle hints, frontier benchmark |

Splits must not be random over problems. The intended hint source is donor
proofs from structurally similar problems — which is what Twitch's
`veroff_hints` path does at axiom-similarity >= 0.9 — so a random split puts
near-duplicate siblings on both sides and scores memorisation of a donor the
model should never have seen. Split by axiom-signature cluster or by theory.

Evaluation is stratified — negative control (SAT problems), speedup on problems
with baseline >= 1s, near-frontier (solvable only at high budget), frontier
(rating >= 0.9), and OOD (UNK/OPN, report-only, never model selection). Labels
below 1s of baseline runtime are ~70% contaminated by process overhead and should
not be trained on.
