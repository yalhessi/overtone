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

Then fetch the external corpora:

```bash
./scripts/fetch_external.py --all
```

## Layout

```
bootstrap.sh          one-shot setup; safe to re-run
environment.yml       conda environment
twitch/               submodule: the abstraction-mining pipeline
overtone/             this project's python package
  otter2twee.py       Otter/EQP equations -> twee $hint terms
  rule_usefulness.py  derived-vs-used rule analysis over twee logs
scripts/
  fetch_external.py   ETP, Robbins/Otter, TSTP corpora
experiments/          sweep drivers and configs
data/                 TPTP + external corpora (gitignored)
logs/                 twee output (gitignored; grows to GBs)
docs/FINDINGS.md      measured results and pitfalls -- read before designing runs
```

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
| TSTP | ~23 systems per solved problem | donor proofs for hint mining |
| Robbins/Otter | 4 rungs, 3 hint lists | oracle hints, frontier benchmark |

Evaluation is stratified — negative control (SAT problems), speedup on problems
with baseline >= 1s, near-frontier (solvable only at high budget), frontier
(rating >= 0.9), and OOD (UNK/OPN, report-only, never model selection). Labels
below 1s of baseline runtime are ~70% contaminated by process overhead and should
not be trained on.
